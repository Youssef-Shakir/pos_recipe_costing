# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IngredientStocktake(models.Model):
    _name = 'ingredient.stocktake'
    _description = 'Ingredient Stocktake'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True,
                       default=lambda self: _('New'))
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user)
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('in_progress', 'In Progress'),
        ('done', 'Validated'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)

    line_ids = fields.One2many('ingredient.stocktake.line', 'stocktake_id', string='Lines')

    gain_account_id = fields.Many2one(
        'account.account',
        string='Gain Account',
        default=lambda self: self._default_gain_account(),
        help="Account for inventory gains (counted > system)"
    )
    loss_account_id = fields.Many2one(
        'account.account',
        string='Loss Account',
        default=lambda self: self._default_loss_account(),
        help="Account for inventory losses (counted < system)"
    )
    # Stocktakes validated before 18.0.4.6.0 posted their own entry; newer ones only adjust stock
    account_move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)
    stock_move_ids = fields.Many2many('stock.move', string='Stock Moves', readonly=True, copy=False)
    valuation_move_count = fields.Integer(compute='_compute_valuation_move_count', string='Entries')

    @api.model
    def _default_gain_account(self):
        ICP = self.env['ir.config_parameter'].sudo()
        account_id = ICP.get_param('pos_recipe_costing.stocktake_gain_account_id')
        if account_id:
            return int(account_id)
        return False

    @api.model
    def _default_loss_account(self):
        ICP = self.env['ir.config_parameter'].sudo()
        account_id = ICP.get_param('pos_recipe_costing.stocktake_loss_account_id')
        if account_id:
            return int(account_id)
        return False

    notes = fields.Text(string='Notes')

    total_system_value = fields.Monetary(compute='_compute_totals', string='System Value', currency_field='currency_id', store=True)
    total_counted_value = fields.Monetary(compute='_compute_totals', string='Counted Value', currency_field='currency_id', store=True)
    total_variance = fields.Monetary(compute='_compute_totals', string='Variance', currency_field='currency_id', store=True)
    total_variance_value = fields.Monetary(compute='_compute_totals', string='Variance Value', currency_field='currency_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')

    line_count = fields.Integer(compute='_compute_totals', string='Items', store=True)
    counted_count = fields.Integer(compute='_compute_totals', string='Counted', store=True)
    pending_count = fields.Integer(compute='_compute_totals', string='Pending', store=True)
    variance_count = fields.Integer(compute='_compute_totals', string='Variances', store=True)

    @api.depends('line_ids.system_value', 'line_ids.counted_value', 'line_ids.variance_value', 'line_ids.is_counted')
    def _compute_totals(self):
        for stocktake in self:
            lines = stocktake.line_ids
            stocktake.total_system_value = sum(lines.mapped('system_value'))
            stocktake.total_counted_value = sum(lines.mapped('counted_value'))
            stocktake.total_variance = sum(lines.mapped('variance_qty'))
            stocktake.total_variance_value = sum(lines.mapped('variance_value'))
            stocktake.line_count = len(lines)
            stocktake.counted_count = len(lines.filtered(lambda l: l.is_counted))
            stocktake.pending_count = len(lines.filtered(lambda l: not l.is_counted))
            stocktake.variance_count = len(lines.filtered(lambda l: l.variance_qty != 0 and l.is_counted))

    @api.depends('stock_move_ids.account_move_ids')
    def _compute_valuation_move_count(self):
        for stocktake in self:
            stocktake.valuation_move_count = len(stocktake.stock_move_ids.account_move_ids)

    def action_view_valuation_entries(self):
        self.ensure_one()
        return {
            'name': _('Stocktake Entries'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.stock_move_ids.account_move_ids.ids)],
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('ingredient.stocktake') or _('New')
        return super().create(vals_list)

    def action_start(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_('Please add ingredients to count before starting.'))
        # The snapshot the count is compared with is taken now, not when the lines were loaded
        for line in self.line_ids:
            line.system_qty = line.product_id.qty_available
        self.state = 'in_progress'

    def action_load_all_ingredients(self):
        """Load all storable ingredients into the stocktake."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only load ingredients in draft state.'))

        ingredients = self.env['product.product'].search([
            ('is_ingredient', '=', True),
        ])

        existing_products = self.line_ids.mapped('product_id')
        new_lines = []

        for ingredient in ingredients:
            if ingredient not in existing_products:
                new_lines.append({
                    'stocktake_id': self.id,
                    'product_id': ingredient.id,
                })

        if new_lines:
            self.env['ingredient.stocktake.line'].create(new_lines)

        return True

    def action_load_by_category(self):
        """Open wizard to select categories to load."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only load ingredients in draft state.'))

        return {
            'name': _('Select Categories'),
            'type': 'ir.actions.act_window',
            'res_model': 'stocktake.category.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_stocktake_id': self.id,
            }
        }

    def action_copy_system_to_counted(self):
        """Copy all system quantities to counted quantities as starting point."""
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(_('Can only copy quantities while counting is in progress.'))

        for line in self.line_ids:
            line.counted_qty = line.system_qty

        return True

    def action_validate(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(_('Stocktake must be in progress to validate.'))

        issues = self._get_plausibility_issues()
        if issues and not self.env.context.get('stocktake_skip_checks'):
            wizard = self.env['ingredient.stocktake.check.wizard'].create({
                'stocktake_id': self.id,
                'message': '\n'.join(issues),
            })
            return {
                'name': _('Check before validating'),
                'type': 'ir.actions.act_window',
                'res_model': 'ingredient.stocktake.check.wizard',
                'res_id': wizard.id,
                'view_mode': 'form',
                'target': 'new',
            }

        lines = self._lines_to_apply()
        if lines:
            self._check_adjustment_accounts(lines)
            self._apply_counted_quantities(lines)

        self.state = 'done'
        return True

    def _lines_to_apply(self):
        # Only counted lines move stock: a pending or skipped line has no count, not a count of 0
        return self.line_ids.filtered(
            lambda l: l.is_counted and l.count_status != 'skipped' and l.variance_qty != 0)

    def _check_adjustment_accounts(self, lines):
        """Odoo posts the differences on the Inventory adjustment location's accounts.
        Without them it would fall back to Stock Incoming / Outgoing, the purchase and POS
        clearing accounts, which is what this module must not touch."""
        self.env['stock.location']._recipe_sync_adjustment_accounts()
        for location in lines.product_id.with_company(self.company_id).mapped('property_stock_inventory'):
            if lines.filtered(lambda l: l.variance_qty > 0) and not location.valuation_out_account_id:
                raise UserError(_('Set the Inventory Gain Account in Settings › Recipe Costing › Stocktake Accounts. '
                                  'It is used for the location "%s".', location.complete_name))
            if lines.filtered(lambda l: l.variance_qty < 0) and not location.valuation_in_account_id:
                raise UserError(_('Set the Inventory Loss Account in Settings › Recipe Costing › Stocktake Accounts. '
                                  'It is used for the location "%s".', location.complete_name))

    def _apply_counted_quantities(self, lines):
        """One posting per difference, made by Odoo on the count date.

        The difference (counted - snapshot at the start of the count) is added to the
        stock of now, so sales and receipts since the count are kept."""
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
        if not warehouse.lot_stock_id:
            raise UserError(_('No warehouse stock location found for %s.', self.company_id.name))
        stock_location = warehouse.lot_stock_id

        StockQuant = self.env['stock.quant'].with_context(inventory_mode=True)
        quants = StockQuant.browse()
        for line in lines:
            quant = StockQuant.search([
                ('product_id', '=', line.product_id.id),
                ('location_id', '=', stock_location.id),
                ('lot_id', '=', False),
                ('package_id', '=', False),
                ('owner_id', '=', False),
            ], limit=1)
            if not quant:
                quant = StockQuant.create({'product_id': line.product_id.id, 'location_id': stock_location.id})
            quant.write({
                'inventory_quantity': quant.quantity + line.variance_qty,
                'accounting_date': self.date,
            })
            quants |= quant

        last_move = self.env['stock.move'].search([], order='id desc', limit=1).id or 0
        reference = _('Stocktake %s', self.name)
        quants.with_context(inventory_name=reference)._apply_inventory()
        self.stock_move_ids = self.env['stock.move'].search([
            ('id', '>', last_move),
            ('product_id', 'in', lines.product_id.ids),
            ('is_inventory', '=', True),
        ])

    def _get_plausibility_issues(self):
        """Lines whose value or unit cost look wrong (e.g. a unit-of-measure mistake)."""
        ICP = self.env['ir.config_parameter'].sudo()
        max_value = float(ICP.get_param('pos_recipe_costing.stocktake_max_line_value') or 1000000.0)
        ratio = float(ICP.get_param('pos_recipe_costing.stocktake_cost_ratio') or 3.0)
        currency = self.currency_id
        issues = []
        for line in self.line_ids.filtered(lambda l: l.is_counted and l.count_status != 'skipped'):
            name = line.product_id.display_name
            if line.counted_qty > 0 and line.unit_cost <= 0:
                issues.append(_('%s: no unit cost, so the count has no value.', name))
            biggest = max(abs(line.counted_value), abs(line.variance_value))
            if max_value and biggest > max_value:
                issues.append(_('%(name)s: value %(value)s is above %(max)s.',
                                name=name, value=currency.format(biggest), max=currency.format(max_value)))
            last_price = line._last_purchase_unit_price()
            if ratio > 1 and last_price and line.unit_cost > 0 and \
                    (line.unit_cost > last_price * ratio or line.unit_cost < last_price / ratio):
                issues.append(_('%(name)s: unit cost %(cost)s per %(uom)s, last purchase %(last)s.',
                                name=name, cost=currency.format(line.unit_cost), uom=line.uom_id.name,
                                last=currency.format(last_price)))
        return issues

    def action_cancel(self):
        self.ensure_one()
        if self.state == 'done':
            raise UserError(_('Cannot cancel a validated stocktake.'))
        self.state = 'cancelled'

    def action_reset_to_draft(self):
        self.ensure_one()
        if self.state != 'cancelled':
            raise UserError(_('Can only reset cancelled stocktakes to draft.'))
        self.state = 'draft'


class IngredientStocktakeLine(models.Model):
    _name = 'ingredient.stocktake.line'
    _description = 'Ingredient Stocktake Line'
    _order = 'product_categ_id, product_id'

    stocktake_id = fields.Many2one('ingredient.stocktake', string='Stocktake', required=True, ondelete='cascade')
    sequence = fields.Integer(string='Sequence', default=10)
    product_id = fields.Many2one('product.product', string='Ingredient', required=True,
                                  domain=[('is_ingredient', '=', True)])
    product_categ_id = fields.Many2one(related='product_id.categ_id', string='Category', store=True)
    uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')

    system_qty = fields.Float(string='System Qty', compute='_compute_system_qty', store=True)
    counted_qty = fields.Float(string='Counted Qty', digits='Product Unit of Measure')
    is_counted = fields.Boolean(string='Counted', default=False,
                                 help="True if user has entered a count (even if zero)")
    count_status = fields.Selection([
        ('pending', 'Pending'),
        ('counted', 'Counted'),
        ('skipped', 'Skipped'),
    ], string='Status', default='pending', compute='_compute_count_status', store=True)
    variance_qty = fields.Float(string='Variance', compute='_compute_variance', store=True)

    unit_cost = fields.Float(related='product_id.standard_price', string='Unit Cost')
    currency_id = fields.Many2one(related='stocktake_id.currency_id')

    system_value = fields.Monetary(compute='_compute_values', string='System Value', store=True)
    counted_value = fields.Monetary(compute='_compute_values', string='Counted Value', store=True)
    variance_value = fields.Monetary(compute='_compute_values', string='Variance Value', store=True)

    notes = fields.Char(string='Notes')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # a line created with a count is counted (the web client may send 0 as a default)
            if vals.get('counted_qty') and 'is_counted' not in vals:
                vals['is_counted'] = True
        return super().create(vals_list)

    def write(self, vals):
        # entering a count marks the line counted, whatever view or API wrote it
        if 'counted_qty' in vals and 'is_counted' not in vals:
            vals = dict(vals, is_counted=True)
        return super().write(vals)

    @api.depends('product_id')
    def _compute_system_qty(self):
        for line in self:
            if line.product_id:
                line.system_qty = line.product_id.qty_available
            else:
                line.system_qty = 0

    @api.depends('is_counted')
    def _compute_count_status(self):
        for line in self:
            if line.is_counted:
                line.count_status = 'counted'
            else:
                line.count_status = 'pending'

    @api.depends('system_qty', 'counted_qty')
    def _compute_variance(self):
        for line in self:
            line.variance_qty = line.counted_qty - line.system_qty

    @api.depends('system_qty', 'counted_qty', 'unit_cost')
    def _compute_values(self):
        for line in self:
            line.system_value = line.system_qty * line.unit_cost
            line.counted_value = line.counted_qty * line.unit_cost
            line.variance_value = line.variance_qty * line.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        """Don't auto-fill counted_qty - leave it for manual entry."""
        pass

    @api.onchange('counted_qty')
    def _onchange_counted_qty(self):
        """Mark as counted when user enters a value."""
        self.is_counted = True

    def _last_purchase_unit_price(self):
        """Price of the last confirmed purchase, per the product's unit and in company currency."""
        self.ensure_one()
        if 'purchase.order.line' not in self.env:
            return 0.0
        po_line = self.env['purchase.order.line'].sudo().search([
            ('product_id', '=', self.product_id.id),
            ('order_id.state', 'in', ('purchase', 'done')),
            ('price_unit', '>', 0),
        ], order='date_order desc, id desc', limit=1)
        if not po_line:
            return 0.0
        price = po_line.product_uom._compute_price(po_line.price_unit, self.product_id.uom_id)
        company = self.stocktake_id.company_id
        return po_line.currency_id._convert(price, company.currency_id, company, po_line.date_order or fields.Date.today())

    def action_match_system(self):
        """Quick action: copy system qty to counted qty and mark as counted."""
        for line in self:
            line.counted_qty = line.system_qty
            line.is_counted = True
        return True

    def action_mark_skipped(self):
        """Mark item as skipped (won't be counted)."""
        for line in self:
            line.is_counted = True
            line.count_status = 'skipped'
        return True

    def action_reset_count(self):
        """Reset item to pending state."""
        for line in self:
            line.counted_qty = 0
            line.is_counted = False
        return True


class StocktakeCheckWizard(models.TransientModel):
    _name = 'ingredient.stocktake.check.wizard'
    _description = 'Stocktake Validation Check'

    stocktake_id = fields.Many2one('ingredient.stocktake', string='Stocktake', required=True)
    message = fields.Text(string='Check', readonly=True)

    def action_validate_anyway(self):
        self.ensure_one()
        return self.stocktake_id.with_context(stocktake_skip_checks=True).action_validate()


class StocktakeCategoryWizard(models.TransientModel):
    _name = 'stocktake.category.wizard'
    _description = 'Stocktake Category Selection Wizard'

    stocktake_id = fields.Many2one('ingredient.stocktake', string='Stocktake', required=True)
    category_ids = fields.Many2many('product.category', string='Categories',
                                     help="Select categories to load ingredients from")

    def action_load(self):
        """Load ingredients from selected categories."""
        self.ensure_one()
        if not self.category_ids:
            raise UserError(_('Please select at least one category.'))

        stocktake = self.stocktake_id
        if stocktake.state != 'draft':
            raise UserError(_('Can only load ingredients in draft state.'))

        ingredients = self.env['product.product'].search([
            ('is_ingredient', '=', True),
            ('categ_id', 'child_of', self.category_ids.ids),
        ])

        existing_products = stocktake.line_ids.mapped('product_id')
        new_lines = []

        for ingredient in ingredients:
            if ingredient not in existing_products:
                new_lines.append({
                    'stocktake_id': stocktake.id,
                    'product_id': ingredient.id,
                })

        if new_lines:
            self.env['ingredient.stocktake.line'].create(new_lines)

        return {'type': 'ir.actions.act_window_close'}
