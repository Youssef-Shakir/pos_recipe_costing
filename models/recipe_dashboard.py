# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class RecipeDashboard(models.Model):
    _name = 'recipe.dashboard'
    _description = 'Recipe Dashboard'

    name = fields.Char(default='Dashboard')

    # Statistics
    recipe_count = fields.Integer(compute='_compute_stats')
    ingredient_count = fields.Integer(compute='_compute_stats')
    pos_product_count = fields.Integer(compute='_compute_stats')
    products_without_recipe = fields.Integer(compute='_compute_stats')
    avg_food_cost = fields.Float(compute='_compute_stats')
    low_margin_count = fields.Integer(compute='_compute_stats')

    def _compute_stats(self):
        Recipe = self.env['restaurant.recipe']
        Product = self.env['product.product']

        # Get threshold from settings
        ICP = self.env['ir.config_parameter'].sudo()
        threshold = float(ICP.get_param('pos_recipe_costing.high_food_cost_threshold', 35))

        recipes = Recipe.search([])
        ingredients = Product.search([('is_ingredient', '=', True)])
        pos_products = Product.search([('available_in_pos', '=', True)])
        products_with_recipe = recipes.mapped('product_id')

        for rec in self:
            rec.recipe_count = len(recipes)
            rec.ingredient_count = len(ingredients)
            rec.pos_product_count = len(pos_products)
            rec.products_without_recipe = len(pos_products - products_with_recipe)
            rec.avg_food_cost = sum(recipes.mapped('food_cost_percentage')) / len(recipes) if recipes else 0
            rec.low_margin_count = len(recipes.filtered(lambda r: r.food_cost_percentage > threshold))

    # Action methods
    def action_view_recipes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipes'),
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_view_ingredients(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredients'),
            'res_model': 'product.product',
            'view_mode': 'list,form',
            'domain': [('is_ingredient', '=', True)],
            'context': {'default_is_ingredient': True, 'default_type': 'consu', 'default_is_storable': True},
            'target': 'current',
        }

    def action_view_pos_products(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('POS Menu Items'),
            'res_model': 'product.product',
            'view_mode': 'list,form',
            'view_id': False,
            'views': [
                (self.env.ref('pos_recipe_costing.view_pos_product_recipe_list').id, 'list'),
                (False, 'form'),
            ],
            'domain': [('available_in_pos', '=', True)],
            'context': {'default_available_in_pos': True},
            'target': 'current',
        }

    def action_products_without_recipe(self):
        Recipe = self.env['restaurant.recipe']
        products_with_recipe = Recipe.search([]).mapped('product_id')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Products Without Recipe'),
            'res_model': 'product.product',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('pos_recipe_costing.view_pos_product_recipe_list').id, 'list'),
                (False, 'form'),
            ],
            'domain': [('available_in_pos', '=', True), ('id', 'not in', products_with_recipe.ids)],
            'target': 'current',
        }

    def action_low_margin_recipes(self):
        ICP = self.env['ir.config_parameter'].sudo()
        threshold = float(ICP.get_param('pos_recipe_costing.high_food_cost_threshold', 35))
        return {
            'type': 'ir.actions.act_window',
            'name': _('High Food Cost Recipes (>%s%%)') % int(threshold),
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('food_cost_percentage', '>', threshold)],
            'target': 'current',
        }

    def action_add_ingredient(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Ingredient'),
            'res_model': 'recipe.quick.ingredient',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_add_menu_item(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Menu Item'),
            'res_model': 'recipe.quick.product',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_open_settings(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Settings'),
            'res_model': 'res.config.settings',
            'view_mode': 'form',
            'target': 'inline',
            'context': {'module': 'pos_recipe_costing'},
        }

    def action_view_boms(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipe BOMs'),
            'res_model': 'mrp.bom',
            'view_mode': 'list,form',
            'domain': [('code', 'like', 'RECIPE-')],
            'target': 'current',
        }
