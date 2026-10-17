# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools import float_compare


class IngredientCostHistory(models.Model):
    _name = 'ingredient.cost.history'
    _description = 'Ingredient Cost History'
    _order = 'change_date desc, id desc'

    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        ondelete='cascade',
        index=True
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        related='product_id.product_tmpl_id',
        store=True,
        string='Product Template'
    )
    old_cost = fields.Float(
        string='Previous Cost',
        digits='Product Price'
    )
    new_cost = fields.Float(
        string='New Cost',
        digits='Product Price'
    )
    change_date = fields.Datetime(
        string='Change Date',
        default=fields.Datetime.now,
        required=True,
        index=True
    )
    change_percentage = fields.Float(
        string='Change %',
        compute='_compute_change_percentage',
        store=True
    )
    changed_by = fields.Many2one(
        'res.users',
        string='Changed By',
        default=lambda self: self.env.user,
        required=True
    )
    reason = fields.Selection([
        ('supplier_change', 'Supplier Change'),
        ('market_price', 'Market Price Adjustment'),
        ('manual_adjustment', 'Manual Adjustment'),
        ('bulk_update', 'Bulk Update'),
    ], string='Reason', default='manual_adjustment')
    notes = fields.Text(string='Notes')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )

    @api.depends('old_cost', 'new_cost')
    def _compute_change_percentage(self):
        for record in self:
            if record.old_cost and float_compare(record.old_cost, 0, precision_digits=2) != 0:
                record.change_percentage = ((record.new_cost - record.old_cost) / record.old_cost) * 100
            else:
                record.change_percentage = 100.0 if record.new_cost else 0.0

    @api.model
    def get_price_trend(self, product_id, days=30):
        """Get price trend for a product over the specified number of days.

        Args:
            product_id: The product.product id to get trend for
            days: Number of days to look back (default 30)

        Returns:
            dict with trend data including:
            - history: list of cost changes
            - avg_cost: average cost over period
            - min_cost: minimum cost over period
            - max_cost: maximum cost over period
            - total_change: total percentage change
            - trend: 'up', 'down', or 'stable'
        """
        from datetime import timedelta
        date_from = fields.Datetime.now() - timedelta(days=days)

        history = self.search([
            ('product_id', '=', product_id),
            ('change_date', '>=', date_from)
        ], order='change_date asc')

        if not history:
            product = self.env['product.product'].browse(product_id)
            return {
                'history': [],
                'avg_cost': product.standard_price if product else 0,
                'min_cost': product.standard_price if product else 0,
                'max_cost': product.standard_price if product else 0,
                'total_change': 0,
                'trend': 'stable',
                'change_count': 0
            }

        costs = history.mapped('new_cost')
        first_cost = history[0].old_cost or history[0].new_cost
        last_cost = history[-1].new_cost

        if first_cost and float_compare(first_cost, 0, precision_digits=2) != 0:
            total_change = ((last_cost - first_cost) / first_cost) * 100
        else:
            total_change = 0

        if float_compare(total_change, 5, precision_digits=2) > 0:
            trend = 'up'
        elif float_compare(total_change, -5, precision_digits=2) < 0:
            trend = 'down'
        else:
            trend = 'stable'

        return {
            'history': [{
                'date': h.change_date,
                'old_cost': h.old_cost,
                'new_cost': h.new_cost,
                'change_percentage': h.change_percentage,
                'reason': h.reason,
            } for h in history],
            'avg_cost': sum(costs) / len(costs) if costs else 0,
            'min_cost': min(costs) if costs else 0,
            'max_cost': max(costs) if costs else 0,
            'total_change': total_change,
            'trend': trend,
            'change_count': len(history)
        }

    @api.model
    def get_recent_changes(self, limit=10):
        """Get the most recent cost changes across all ingredients."""
        return self.search([], limit=limit, order='change_date desc')

    @api.model
    def get_monthly_stats(self):
        """Get cost change statistics for the current month."""
        from datetime import datetime
        today = fields.Date.today()
        month_start = today.replace(day=1)

        changes = self.search([
            ('change_date', '>=', datetime.combine(month_start, datetime.min.time()))
        ])

        if not changes:
            return {
                'total_changes': 0,
                'avg_increase': 0,
                'avg_decrease': 0,
                'products_affected': 0
            }

        increases = changes.filtered(lambda c: c.change_percentage > 0)
        decreases = changes.filtered(lambda c: c.change_percentage < 0)

        return {
            'total_changes': len(changes),
            'avg_increase': sum(increases.mapped('change_percentage')) / len(increases) if increases else 0,
            'avg_decrease': sum(decreases.mapped('change_percentage')) / len(decreases) if decreases else 0,
            'products_affected': len(changes.mapped('product_id'))
        }
