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
    account_move_id = fields.Many2one('account.move', string='Journal Entry', readonly=True)

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

    total_system_value = fields.Monetary(compute='_compute_totals', string='System Value', currency_field='currency_id')
    total_counted_value = fields.Monetary(compute='_compute_totals', string='Counted Value', currency_field='currency_id')
    total_variance = fields.Monetary(compute='_compute_totals', string='Variance', currency_field='currency_id')
    total_variance_value = fields.Monetary(compute='_compute_totals', string='Variance Value', currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')

    line_count = fields.Integer(compute='_compute_totals', string='Items')
    variance_count = fields.Integer(compute='_compute_totals', string='Variances')

    @api.depends('line_ids.system_value', 'line_ids.counted_value', 'line_ids.variance_value')
    def _compute_totals(self):
        for stocktake in self:
            lines = stocktake.line_ids
            stocktake.total_system_value = sum(lines.mapped('system_value'))
            stocktake.total_counted_value = sum(lines.mapped('counted_value'))
            stocktake.total_variance = sum(lines.mapped('variance_qty'))
            stocktake.total_variance_value = sum(lines.mapped('variance_value'))
            stocktake.line_count = len(lines)
            stocktake.variance_count = len(lines.filtered(lambda l: l.variance_qty != 0))

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
        self.state = 'in_progress'

    def action_load_all_ingredients(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Can only load ingredients in draft state.'))

        ingredients = self.env['product.product'].search([
            ('is_ingredient', '=', True),
            ('type', '=', 'consu'),
            ('is_storable', '=', True),
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

    def action_validate(self):
        self.ensure_one()
        if self.state != 'in_progress':
            raise UserError(_('Stocktake must be in progress to validate.'))

        lines_with_variance = self.line_ids.filtered(lambda l: l.variance_qty != 0)
        lines_with_gain = lines_with_variance.filtered(lambda l: l.variance_qty > 0)
        lines_with_loss = lines_with_variance.filtered(lambda l: l.variance_qty < 0)

        if lines_with_gain and not self.gain_account_id:
            raise UserError(_('Please configure Inventory Gain Account in Settings or select one here.'))

        if lines_with_loss and not self.loss_account_id:
            raise UserError(_('Please configure Inventory Loss Account in Settings or select one here.'))

        if lines_with_variance:
            self._create_inventory_adjustment()
            self._create_account_move()

        self.state = 'done'

    def _create_inventory_adjustment(self):
        """Adjust inventory using stock.quant"""
        warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.company_id.id)], limit=1)
        if not warehouse:
            return

        stock_location = warehouse.lot_stock_id
        if not stock_location:
            return

        StockQuant = self.env['stock.quant']

        for line in self.line_ids.filtered(lambda l: l.variance_qty != 0):
            product = line.product_id

            # Find or create quant for this product/location
            quant = StockQuant.search([
                ('product_id', '=', product.id),
                ('location_id', '=', stock_location.id),
            ], limit=1)

            if quant:
                # Update existing quant with inventory adjustment
                quant.with_context(inventory_mode=True).write({
                    'inventory_quantity': line.counted_qty,
                })
                quant.action_apply_inventory()
            else:
                # Create new quant with counted quantity
                quant = StockQuant.with_context(inventory_mode=True).create({
                    'product_id': product.id,
                    'location_id': stock_location.id,
                    'inventory_quantity': line.counted_qty,
                })
                quant.action_apply_inventory()

    def _create_account_move(self):
        lines_with_variance = self.line_ids.filtered(lambda l: l.variance_qty != 0)
        if not lines_with_variance:
            return

        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if not journal:
            raise UserError(_('No general journal found for posting adjustments.'))

        total_variance = sum(lines_with_variance.mapped('variance_value'))

        move_lines = []

        for line in lines_with_variance:
            if not line.product_id.categ_id.property_stock_valuation_account_id:
                continue

            stock_account = line.product_id.categ_id.property_stock_valuation_account_id

            if line.variance_value > 0:
                # Gain: Debit Stock, Credit Gain Account
                move_lines.append((0, 0, {
                    'name': f"Stocktake gain: {line.product_id.name}",
                    'account_id': stock_account.id,
                    'debit': abs(line.variance_value),
                    'credit': 0,
                }))
                move_lines.append((0, 0, {
                    'name': f"Stocktake gain: {line.product_id.name}",
                    'account_id': self.gain_account_id.id,
                    'debit': 0,
                    'credit': abs(line.variance_value),
                }))
            else:
                # Loss: Debit Loss Account, Credit Stock
                move_lines.append((0, 0, {
                    'name': f"Stocktake loss: {line.product_id.name}",
                    'account_id': self.loss_account_id.id,
                    'debit': abs(line.variance_value),
                    'credit': 0,
                }))
                move_lines.append((0, 0, {
                    'name': f"Stocktake loss: {line.product_id.name}",
                    'account_id': stock_account.id,
                    'debit': 0,
                    'credit': abs(line.variance_value),
                }))

        if move_lines:
            account_move = self.env['account.move'].create({
                'journal_id': journal.id,
                'date': self.date,
                'ref': f"Stocktake: {self.name}",
                'line_ids': move_lines,
            })
            account_move.action_post()
            self.account_move_id = account_move

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

    stocktake_id = fields.Many2one('ingredient.stocktake', string='Stocktake', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Ingredient', required=True,
                                  domain=[('is_ingredient', '=', True)])
    uom_id = fields.Many2one(related='product_id.uom_id', string='UoM')

    system_qty = fields.Float(string='System Qty', compute='_compute_system_qty', store=True)
    counted_qty = fields.Float(string='Counted Qty', digits='Product Unit of Measure')
    variance_qty = fields.Float(string='Variance', compute='_compute_variance', store=True)

    unit_cost = fields.Float(related='product_id.standard_price', string='Unit Cost')
    currency_id = fields.Many2one(related='stocktake_id.currency_id')

    system_value = fields.Monetary(compute='_compute_values', string='System Value', store=True)
    counted_value = fields.Monetary(compute='_compute_values', string='Counted Value', store=True)
    variance_value = fields.Monetary(compute='_compute_values', string='Variance Value', store=True)

    notes = fields.Char(string='Notes')

    @api.depends('product_id')
    def _compute_system_qty(self):
        for line in self:
            if line.product_id:
                line.system_qty = line.product_id.qty_available
            else:
                line.system_qty = 0

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
        if self.product_id:
            self.counted_qty = self.product_id.qty_available
