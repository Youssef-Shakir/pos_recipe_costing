# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools import float_compare


class RecipeCostHistory(models.Model):
    _name = 'recipe.cost.history'
    _description = 'Recipe Cost History'
    _order = 'change_date desc, id desc'

    recipe_id = fields.Many2one(
        'restaurant.recipe',
        string='Recipe',
        required=True,
        ondelete='cascade',
        index=True
    )
    recipe_name = fields.Char(
        related='recipe_id.name',
        store=True,
        string='Recipe Name'
    )
    product_id = fields.Many2one(
        'product.product',
        related='recipe_id.product_id',
        store=True,
        string='Menu Item'
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
    trigger = fields.Selection([
        ('ingredient_change', 'Ingredient Price Change'),
        ('portion_change', 'Portion Size Change'),
        ('recipe_edit', 'Recipe Edit'),
    ], string='Trigger', default='recipe_edit')
    changed_by = fields.Many2one(
        'res.users',
        string='Changed By',
        default=lambda self: self.env.user
    )
    notes = fields.Text(string='Notes')
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )

    # Additional context fields
    old_portion_size = fields.Float(string='Previous Portion Size')
    new_portion_size = fields.Float(string='New Portion Size')
    selling_price = fields.Float(
        string='Selling Price',
        related='recipe_id.selling_price',
        store=True
    )
    old_food_cost_percentage = fields.Float(string='Previous Food Cost %')
    new_food_cost_percentage = fields.Float(string='New Food Cost %')

    @api.depends('old_cost', 'new_cost')
    def _compute_change_percentage(self):
        for record in self:
            if record.old_cost and float_compare(record.old_cost, 0, precision_digits=2) != 0:
                record.change_percentage = ((record.new_cost - record.old_cost) / record.old_cost) * 100
            else:
                record.change_percentage = 100.0 if record.new_cost else 0.0

    @api.model
    def get_recipe_trend(self, recipe_id, days=30):
        """Get cost trend for a recipe over the specified number of days.

        Args:
            recipe_id: The restaurant.recipe id to get trend for
            days: Number of days to look back (default 30)

        Returns:
            dict with trend data
        """
        from datetime import timedelta
        date_from = fields.Datetime.now() - timedelta(days=days)

        history = self.search([
            ('recipe_id', '=', recipe_id),
            ('change_date', '>=', date_from)
        ], order='change_date asc')

        if not history:
            recipe = self.env['restaurant.recipe'].browse(recipe_id)
            return {
                'history': [],
                'avg_cost': recipe.cost_per_portion if recipe else 0,
                'min_cost': recipe.cost_per_portion if recipe else 0,
                'max_cost': recipe.cost_per_portion if recipe else 0,
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
                'trigger': h.trigger,
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
        """Get the most recent cost changes across all recipes."""
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
                'recipes_affected': 0
            }

        increases = changes.filtered(lambda c: c.change_percentage > 0)
        decreases = changes.filtered(lambda c: c.change_percentage < 0)

        return {
            'total_changes': len(changes),
            'avg_increase': sum(increases.mapped('change_percentage')) / len(increases) if increases else 0,
            'avg_decrease': sum(decreases.mapped('change_percentage')) / len(decreases) if decreases else 0,
            'recipes_affected': len(changes.mapped('recipe_id'))
        }
