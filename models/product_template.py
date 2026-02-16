# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Recipe link
    recipe_ids = fields.One2many(
        'restaurant.recipe',
        'product_tmpl_id',
        string='Recipes'
    )
    has_recipe = fields.Boolean(
        string='Has Recipe',
        compute='_compute_has_recipe',
        store=True
    )
    recipe_count = fields.Integer(
        string='Recipe Count',
        compute='_compute_has_recipe'
    )

    # Food cost fields
    food_cost = fields.Float(
        string='Food Cost',
        compute='_compute_food_cost'
    )
    food_cost_percentage = fields.Float(
        string='Food Cost %',
        compute='_compute_food_cost'
    )
    profit_margin = fields.Float(
        string='Profit Margin',
        compute='_compute_food_cost'
    )

    # Ingredient categorization
    is_ingredient = fields.Boolean(
        string='Is Ingredient',
        help="Check if this product is used as an ingredient in recipes"
    )
    ingredient_category = fields.Selection([
        ('protein', 'Protein'),
        ('vegetable', 'Vegetable'),
        ('dairy', 'Dairy'),
        ('grain', 'Grain/Starch'),
        ('spice', 'Spice/Seasoning'),
        ('sauce', 'Sauce/Condiment'),
        ('beverage', 'Beverage'),
        ('packaging', 'Packaging'),
        ('other', 'Other'),
    ], string='Ingredient Category')

    # Usage tracking
    used_in_recipe_count = fields.Integer(
        string='Used in Recipes',
        compute='_compute_used_in_recipes'
    )

    @api.depends('recipe_ids')
    def _compute_has_recipe(self):
        for product in self:
            product.recipe_count = len(product.recipe_ids)
            product.has_recipe = product.recipe_count > 0

    @api.depends('recipe_ids.cost_per_portion', 'recipe_ids.food_cost_percentage',
                 'recipe_ids.profit_margin', 'list_price')
    def _compute_food_cost(self):
        for product in self:
            recipe = product.recipe_ids[:1]
            if recipe:
                product.food_cost = recipe.cost_per_portion
                product.food_cost_percentage = recipe.food_cost_percentage
                product.profit_margin = recipe.profit_margin
            else:
                product.food_cost = 0
                product.food_cost_percentage = 0
                product.profit_margin = product.list_price

    def _compute_used_in_recipes(self):
        RecipeLine = self.env['recipe.ingredient.line']
        for product in self:
            count = RecipeLine.search_count([
                ('product_id.product_tmpl_id', '=', product.id)
            ])
            product.used_in_recipe_count = count

    def action_view_recipes(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Recipes',
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('product_tmpl_id', '=', self.id)],
            'context': {
                'default_product_id': self.product_variant_id.id,
                'default_name': self.name,
            }
        }

    def action_create_recipe(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Create Recipe',
            'res_model': 'restaurant.recipe',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_product_id': self.product_variant_id.id,
                'default_name': self.name,
            }
        }

    def action_view_used_in_recipes(self):
        self.ensure_one()
        lines = self.env['recipe.ingredient.line'].search([
            ('product_id.product_tmpl_id', '=', self.id)
        ])
        recipe_ids = lines.mapped('recipe_id').ids
        return {
            'type': 'ir.actions.act_window',
            'name': 'Used in Recipes',
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('id', 'in', recipe_ids)],
        }


class ProductProduct(models.Model):
    _inherit = 'product.product'

    recipe_id = fields.Many2one(
        'restaurant.recipe',
        string='Recipe',
        compute='_compute_recipe_id'
    )
    has_recipe = fields.Boolean(
        related='product_tmpl_id.has_recipe',
        store=True
    )
    food_cost_percentage = fields.Float(
        related='product_tmpl_id.food_cost_percentage'
    )
    used_in_recipe_count = fields.Integer(
        related='product_tmpl_id.used_in_recipe_count'
    )

    def _compute_recipe_id(self):
        Recipe = self.env['restaurant.recipe']
        for product in self:
            product.recipe_id = Recipe.search([
                ('product_id', '=', product.id)
            ], limit=1)

    def action_create_recipe(self):
        """Create a recipe for this product"""
        self.ensure_one()
        # Check if recipe already exists
        existing = self.env['restaurant.recipe'].search([
            ('product_id', '=', self.id)
        ], limit=1)
        if existing:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Recipe'),
                'res_model': 'restaurant.recipe',
                'view_mode': 'form',
                'res_id': existing.id,
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Create Recipe'),
            'res_model': 'restaurant.recipe',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_product_id': self.id,
                'default_name': self.name,
            }
        }

    def action_view_recipes(self):
        """View recipes for this product"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipes'),
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('product_id', '=', self.id)],
            'target': 'current',
        }

    def action_create_recipe_bulk(self):
        """Create recipes for multiple products at once"""
        Recipe = self.env['restaurant.recipe']
        created = 0
        for product in self:
            # Skip if recipe already exists
            existing = Recipe.search([('product_id', '=', product.id)], limit=1)
            if not existing:
                Recipe.create({
                    'name': product.name,
                    'product_id': product.id,
                    'recipe_type': 'dish',
                })
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recipes Created'),
                'message': _('%d recipes have been created.') % created,
                'type': 'success',
                'sticky': False,
            }
        }
