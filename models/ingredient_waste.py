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

        # One posting, made by Odoo: the scrap moves the stock to the Scrap location,
        # whose accounts (set from Settings) receive the waste expense
        self._create_stock_adjustment()

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

        self.env['stock.location']._recipe_sync_adjustment_accounts()
        if not scrap_location.valuation_in_account_id:
            raise UserError(_('Set the Waste Expense Account in Settings › Recipe Costing › Waste Tracking. '
                              'It is used for the location "%s".', scrap_location.complete_name))

        reason_labels = dict(self._fields['reason'].selection)
        scrap = self.env['stock.scrap'].create({
            'product_id': self.product_id.id,
            'product_uom_id': self.product_id.uom_id.id,
            'scrap_qty': self.quantity,
            'location_id': stock_location.id,
            'scrap_location_id': scrap_location.id,
            'company_id': self.company_id.id,
            'origin': '%s (%s)' % (self.name, reason_labels.get(self.reason, self.reason)),
        })
        # do_scrap skips the "not enough stock" wizard; the entry is dated on the waste date
        scrap.with_context(force_period_date=self.date).do_scrap()
        self.stock_move_id = scrap.move_ids[:1]

    def action_view_journal_entry(self):
        """Open the related journal entry"""
        self.ensure_one()
        # Records confirmed before 18.0.4.6.0 have their own entry, newer ones the scrap's
        moves = self.account_move_id | self.stock_move_id.account_move_ids
        if not moves:
            raise UserError(_('No journal entry has been created yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Entry'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': moves[:1].id,
            'target': 'current',
        }
