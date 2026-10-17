# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class IngredientConsumptionLine(models.Model):
    _name = 'ingredient.consumption.line'
    _description = 'Ingredient Consumption Line'
    _order = 'date desc, cost desc'
    _rec_name = 'product_id'

    date = fields.Date(
        string='Date',
        required=True,
        index=True,
        default=fields.Date.today
    )
    date_from = fields.Date(
        string='Period Start',
        help="Start date of the consumption period"
    )
    date_to = fields.Date(
        string='Period End',
        help="End date of the consumption period"
    )
    product_id = fields.Many2one(
        'product.product',
        string='Ingredient',
        required=True,
        index=True,
        domain="[('is_ingredient', '=', True)]"
    )
    product_categ_id = fields.Many2one(
        'product.category',
        string='Category',
        related='product_id.categ_id',
        store=True,
        index=True
    )
    quantity = fields.Float(
        string='Quantity Consumed',
        digits='Product Unit of Measure',
        required=True
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True
    )
    cost = fields.Float(
        string='Total Cost',
        digits='Product Price',
        help="Total cost of consumed quantity"
    )
    unit_cost = fields.Float(
        string='Unit Cost',
        compute='_compute_unit_cost',
        store=True,
        digits='Product Price'
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )
    recipe_ids = fields.Many2many(
        'restaurant.recipe',
        'consumption_line_recipe_rel',
        'line_id',
        'recipe_id',
        string='Used in Recipes'
    )
    recipe_names = fields.Char(
        string='Recipes',
        compute='_compute_recipe_names',
        store=True
    )
    source_move_ids = fields.Many2many(
        'stock.move',
        'consumption_line_move_rel',
        'line_id',
        'move_id',
        string='Source Stock Moves'
    )
    pos_order_ids = fields.Many2many(
        'pos.order',
        'consumption_line_pos_order_rel',
        'line_id',
        'order_id',
        string='POS Orders'
    )
    notes = fields.Text(string='Notes')

    @api.depends('cost', 'quantity')
    def _compute_unit_cost(self):
        for line in self:
            if line.quantity:
                line.unit_cost = line.cost / line.quantity
            else:
                line.unit_cost = 0.0

    @api.depends('recipe_ids', 'recipe_ids.name')
    def _compute_recipe_names(self):
        for line in self:
            if line.recipe_ids:
                line.recipe_names = ', '.join(line.recipe_ids.mapped('name'))
            else:
                # Fall back to searching recipes that use this ingredient
                recipes = self.env['restaurant.recipe'].search([
                    ('ingredient_line_ids.product_id', '=', line.product_id.id)
                ])
                line.recipe_names = ', '.join(recipes.mapped('name')) if recipes else ''

    def action_view_stock_moves(self):
        """View the stock moves that generated this consumption"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Stock Moves - %s') % self.product_id.display_name,
            'res_model': 'stock.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.source_move_ids.ids)],
            'target': 'current',
        }

    def action_view_pos_orders(self):
        """View POS orders that consumed this ingredient"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('POS Orders - %s') % self.product_id.display_name,
            'res_model': 'pos.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.pos_order_ids.ids)],
            'target': 'current',
        }

    def action_view_recipes(self):
        """View recipes using this ingredient"""
        self.ensure_one()
        recipes = self.recipe_ids
        if not recipes:
            recipes = self.env['restaurant.recipe'].search([
                ('ingredient_line_ids.product_id', '=', self.product_id.id)
            ])
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipes using %s') % self.product_id.display_name,
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('id', 'in', recipes.ids)],
            'target': 'current',
        }

    @api.model
    def get_consumption_summary(self, date_from, date_to, product_ids=None, category_ids=None):
        """
        Get consumption summary for reporting.
        Returns aggregated data suitable for dashboards.
        """
        domain = [
            ('date', '>=', date_from),
            ('date', '<=', date_to),
        ]
        if product_ids:
            domain.append(('product_id', 'in', product_ids))
        if category_ids:
            domain.append(('product_categ_id', 'child_of', category_ids))

        lines = self.search(domain)

        # Aggregate by product
        product_summary = {}
        for line in lines:
            pid = line.product_id.id
            if pid not in product_summary:
                product_summary[pid] = {
                    'product_id': line.product_id,
                    'product_name': line.product_id.display_name,
                    'category': line.product_categ_id.complete_name,
                    'uom': line.uom_id.name,
                    'total_qty': 0.0,
                    'total_cost': 0.0,
                }
            product_summary[pid]['total_qty'] += line.quantity
            product_summary[pid]['total_cost'] += line.cost

        return {
            'total_cost': sum(l.cost for l in lines),
            'total_items': len(lines),
            'unique_ingredients': len(product_summary),
            'by_product': list(product_summary.values()),
        }
