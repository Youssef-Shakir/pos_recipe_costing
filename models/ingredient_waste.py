# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class IngredientWaste(models.Model):
    _name = 'ingredient.waste'
    _description = 'Ingredient Waste Tracking'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'date desc, id desc'

    name = fields.Char(
        string='Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    date = fields.Date(
        string='Date',
        required=True,
        default=fields.Date.context_today,
        tracking=True
    )
    product_id = fields.Many2one(
        'product.product',
        string='Ingredient',
        required=True,
        domain=[('is_ingredient', '=', True)],
        tracking=True
    )
    quantity = fields.Float(
        string='Quantity',
        required=True,
        digits='Product Unit of Measure',
        tracking=True
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        store=True,
        readonly=True
    )
    reason = fields.Selection([
        ('expired', 'Expired'),
        ('spoiled', 'Spoiled'),
        ('damaged', 'Damaged'),
        ('overproduction', 'Overproduction'),
        ('other', 'Other'),
    ], string='Reason', required=True, default='spoiled', tracking=True)
    notes = fields.Text(string='Notes')

    # Cost fields
    unit_cost = fields.Float(
        string='Unit Cost',
        related='product_id.standard_price',
        store=True,
        readonly=True
    )
    cost = fields.Monetary(
        string='Total Cost',
        compute='_compute_cost',
        store=True,
        currency_field='currency_id'
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        store=True,
        readonly=True
    )

    # User and company
    recorded_by = fields.Many2one(
        'res.users',
        string='Recorded By',
        default=lambda self: self.env.user,
        required=True,
        tracking=True
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True
    )

    # State management
    state = fields.Selection([
        ('draft', 'Draft'),
        ('confirmed', 'Confirmed'),
    ], string='Status', default='draft', tracking=True)

    # Stock and accounting links
    stock_move_id = fields.Many2one(
        'stock.move',
        string='Stock Move',
        readonly=True,
        copy=False
    )
    account_move_id = fields.Many2one(
        'account.move',
        string='Journal Entry',
        readonly=True,
        copy=False
    )
    waste_account_id = fields.Many2one(
        'account.account',
        string='Waste Account',
        default=lambda self: self._default_waste_account(),
        help="Account for recording waste expenses"
    )

    @api.model
    def _default_waste_account(self):
        """Get default waste account from settings"""
        ICP = self.env['ir.config_parameter'].sudo()
        account_id = ICP.get_param('pos_recipe_costing.waste_account_id')
        if account_id:
            return int(account_id)
        return False

    @api.depends('quantity', 'unit_cost')
    def _compute_cost(self):
        for record in self:
            record.cost = record.quantity * record.unit_cost

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('ingredient.waste') or _('New')
        return super().create(vals_list)

    def action_confirm(self):
        """Confirm waste record and create stock adjustment"""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Only draft records can be confirmed.'))

        if self.quantity <= 0:
            raise UserError(_('Quantity must be greater than zero.'))

        if not self.waste_account_id:
            raise UserError(_('Please configure a Waste Account in Settings or select one here.'))

        # Create stock adjustment
        self._create_stock_adjustment()

        # Create accounting entry
        self._create_account_move()

        self.state = 'confirmed'
        return True

    def action_reset_to_draft(self):
        """Reset to draft (only if no stock/accounting moves)"""
        self.ensure_one()
        if self.stock_move_id or self.account_move_id:
            raise UserError(_('Cannot reset to draft - stock and accounting entries have been created.'))
        self.state = 'draft'
        return True

    def _create_stock_adjustment(self):
        """Create stock move to remove wasted quantity from inventory"""
        self.ensure_one()

        warehouse = self.env['stock.warehouse'].search([
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if not warehouse:
            raise UserError(_('No warehouse found for company %s.') % self.company_id.name)

        stock_location = warehouse.lot_stock_id
        if not stock_location:
            raise UserError(_('No stock location found for warehouse %s.') % warehouse.name)

        # Get inventory loss location (virtual location for scrapping)
        scrap_location = self.env['stock.location'].search([
            ('scrap_location', '=', True),
            ('company_id', 'in', [self.company_id.id, False])
        ], limit=1)

        if not scrap_location:
            # Try to find any scrap location
            scrap_location = self.env['stock.location'].search([
                ('scrap_location', '=', True)
            ], limit=1)

        if not scrap_location:
            raise UserError(_('No scrap location found. Please configure a scrap location.'))

        # Update stock using quants (similar to stocktake approach)
        StockQuant = self.env['stock.quant']

        quant = StockQuant.search([
            ('product_id', '=', self.product_id.id),
            ('location_id', '=', stock_location.id),
        ], limit=1)

        if quant:
            current_qty = quant.quantity
            new_qty = current_qty - self.quantity
            if new_qty < 0:
                new_qty = 0  # Don't go negative

            quant.with_context(inventory_mode=True).write({
                'inventory_quantity': new_qty,
            })
            quant.action_apply_inventory()
        else:
            # No existing quant - nothing to reduce
            pass

    def _create_account_move(self):
        """Create journal entry for waste expense"""
        self.ensure_one()

        if self.cost <= 0:
            return  # No cost to record

        journal = self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.company_id.id)
        ], limit=1)

        if not journal:
            raise UserError(_('No general journal found for posting waste entries.'))

        # Get stock interim account from product category
        categ = self.product_id.categ_id
        stock_output_account = categ.property_stock_account_output_categ_id

        if not stock_output_account:
            raise UserError(_(
                'Please configure Stock Interim (Delivered) account on product category "%s".'
            ) % categ.name)

        reason_labels = dict(self._fields['reason'].selection)
        reason_label = reason_labels.get(self.reason, self.reason)

        move_lines = [
            # Debit: Waste Expense Account
            (0, 0, {
                'name': _('Waste: %s (%s)') % (self.product_id.name, reason_label),
                'account_id': self.waste_account_id.id,
                'debit': self.cost,
                'credit': 0,
            }),
            # Credit: Stock Interim (Delivered) Account
            (0, 0, {
                'name': _('Waste: %s (%s)') % (self.product_id.name, reason_label),
                'account_id': stock_output_account.id,
                'debit': 0,
                'credit': self.cost,
            }),
        ]

        account_move = self.env['account.move'].create({
            'journal_id': journal.id,
            'date': self.date,
            'ref': _('Waste: %s') % self.name,
            'line_ids': move_lines,
        })
        account_move.action_post()
        self.account_move_id = account_move

    def action_view_journal_entry(self):
        """Open the related journal entry"""
        self.ensure_one()
        if not self.account_move_id:
            raise UserError(_('No journal entry has been created yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': self.account_move_id.id,
            'target': 'current',
        }
