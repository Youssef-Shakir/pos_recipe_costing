# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.tools import float_compare


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # Cost history fields
    cost_history_count = fields.Integer(
        string='Cost History Count',
        compute='_compute_cost_history_count'
    )

    def _compute_cost_history_count(self):
        CostHistory = self.env['ingredient.cost.history']
        for template in self:
            template.cost_history_count = CostHistory.search_count([
                ('product_tmpl_id', '=', template.id)
            ])

    def action_view_cost_history(self):
        """View cost history for this product template."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cost History - %s') % self.name,
            'res_model': 'ingredient.cost.history',
            'view_mode': 'list,graph,pivot',
            'domain': [('product_tmpl_id', '=', self.id)],
            'context': {'default_product_id': self.product_variant_id.id},
        }

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

    # Production type - determines how product is handled
    production_type = fields.Selection([
        ('buy_sell', 'Buy & Sell'),
        ('kitchen', 'Made in Kitchen'),
        ('component', 'Component/Sub-Recipe'),
    ], string='Production Type', default='kitchen',
       help="Buy & Sell: Purchased and resold as-is (tracked inventory, no recipe needed)\n"
            "Made in Kitchen: Prepared on-site, needs recipe for costing\n"
            "Component/Sub-Recipe: Made in-house and used in other recipes (sauces, bases)")

    @api.onchange('production_type')
    def _onchange_production_type(self):
        """Set product type based on production type.

        Buy & Sell items need inventory tracking (storable product).
        Kitchen made items use BOM/Kit consumption (consumable).
        """
        if self.production_type == 'buy_sell':
            # Buy & Sell needs inventory tracking
            self.detailed_type = 'product'  # Storable product
        elif self.production_type in ('kitchen', 'component'):
            # Kitchen made uses BOM consumption
            self.detailed_type = 'consu'  # Consumable

    # Ingredient categorization
    is_ingredient = fields.Boolean(
        string='Is Ingredient',
        help="Check if this product is used as an ingredient in recipes"
    )
    is_component = fields.Boolean(
        string='Is Component',
        compute='_compute_is_component',
        store=True,
        help="Automatically set when product has a component recipe"
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
        ('component', 'Prepared Component'),
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

    @api.depends('recipe_ids', 'recipe_ids.recipe_type')
    def _compute_is_component(self):
        """Set is_component True if product has a component-type recipe."""
        for product in self:
            product.is_component = any(
                r.recipe_type == 'component' for r in product.recipe_ids
            )

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

    def action_open_variant_recipe_setup(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Setup Variant Recipes'),
            'res_model': 'recipe.variant.setup',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_product_tmpl_id': self.id},
        }

    def action_open_variant_recipe_editor(self):
        """Open the variant recipe editor wizard."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit Variant Recipes'),
            'res_model': 'recipe.variant.editor',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_product_tmpl_id': self.id},
        }

    def action_print_variant_recipes(self):
        """Print variant recipe comparison report."""
        self.ensure_one()
        if not self.recipe_ids:
            from odoo.exceptions import UserError
            raise UserError(_('No recipes found for this product template.'))

        return self.env.ref(
            'pos_recipe_costing.action_report_variant_recipes'
        ).report_action(self)

    def action_print_kitchen_cards(self):
        """Print kitchen-friendly recipe cards for all variants."""
        self.ensure_one()
        if not self.recipe_ids:
            from odoo.exceptions import UserError
            raise UserError(_('No recipes found for this product template.'))

        return self.env.ref(
            'pos_recipe_costing.action_report_variant_recipes_kitchen'
        ).report_action(self)

    def _get_variant_comparison_data(self):
        """Get comparison data for all variant recipes of this product template.

        Returns a dictionary containing:
        - common_ingredients: List of ingredients present in ALL variants with same quantity
        - unique_ingredients: Dict mapping recipe_id to list of unique ingredients
        - all_ingredients: List of all ingredients with variant presence info
        - quantity_differences: Ingredients with different quantities across variants

        This method is called from the report template.
        """
        self.ensure_one()
        recipes = self.recipe_ids
        if not recipes:
            return {
                'common_ingredients': [],
                'unique_ingredients': {},
                'all_ingredients': [],
            }

        # Build ingredient data structure
        # Key: product_id, Value: dict with recipe_id -> {quantity, uom, name}
        ingredient_map = {}
        for recipe in recipes:
            for line in recipe.ingredient_line_ids:
                prod_id = line.product_id.id
                if prod_id not in ingredient_map:
                    ingredient_map[prod_id] = {
                        'name': line.product_id.name,
                        'variants': {},
                        'uom': line.uom_id.name,
                    }
                ingredient_map[prod_id]['variants'][recipe.id] = line.quantity

        # Analyze common vs unique ingredients
        recipe_ids = recipes.ids
        recipe_count = len(recipe_ids)

        common_ingredients = []
        unique_ingredients = {r.id: [] for r in recipes}
        all_ingredients = []

        for prod_id, data in ingredient_map.items():
            variants_present = data['variants']
            present_count = len(variants_present)

            # Check if quantity varies across variants
            quantities = list(variants_present.values())
            quantity_varies = len(set(quantities)) > 1 if quantities else False

            ing_info = {
                'product_id': prod_id,
                'name': data['name'],
                'uom': data['uom'],
                'variants': variants_present,
                'quantity_varies': quantity_varies,
            }
            all_ingredients.append(ing_info)

            if present_count == recipe_count and not quantity_varies:
                # Present in all variants with same quantity
                common_ingredients.append({
                    'product_id': prod_id,
                    'name': data['name'],
                    'quantity': quantities[0] if quantities else 0,
                    'uom': data['uom'],
                })
            elif present_count < recipe_count:
                # Unique to some variants
                for recipe_id, qty in variants_present.items():
                    unique_ingredients[recipe_id].append({
                        'product_id': prod_id,
                        'name': data['name'],
                        'quantity': qty,
                        'uom': data['uom'],
                    })

        # Sort ingredients by name
        common_ingredients.sort(key=lambda x: x['name'])
        all_ingredients.sort(key=lambda x: x['name'])
        for recipe_id in unique_ingredients:
            unique_ingredients[recipe_id].sort(key=lambda x: x['name'])

        return {
            'common_ingredients': common_ingredients,
            'unique_ingredients': unique_ingredients,
            'all_ingredients': all_ingredients,
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
    cost_history_count = fields.Integer(
        string='Cost History Count',
        compute='_compute_cost_history_count'
    )

    # Context field for cost change reason (used when updating price via wizard)
    _cost_change_reason = None
    _cost_change_notes = None

    def _compute_cost_history_count(self):
        CostHistory = self.env['ingredient.cost.history']
        for product in self:
            product.cost_history_count = CostHistory.search_count([
                ('product_id', '=', product.id)
            ])

    def write(self, vals):
        """Override write to track standard_price changes."""
        if 'standard_price' in vals:
            # Track cost changes for ingredient products
            CostHistory = self.env['ingredient.cost.history']
            for product in self:
                old_cost = product.standard_price
                new_cost = vals.get('standard_price', old_cost)

                # Only create history if cost actually changed
                if float_compare(old_cost, new_cost, precision_digits=4) != 0:
                    # Determine reason from context or default
                    reason = self.env.context.get('cost_change_reason', 'manual_adjustment')
                    notes = self.env.context.get('cost_change_notes', '')

                    CostHistory.create({
                        'product_id': product.id,
                        'old_cost': old_cost,
                        'new_cost': new_cost,
                        'reason': reason,
                        'notes': notes,
                        'changed_by': self.env.user.id,
                    })

        return super().write(vals)

    def action_view_cost_history(self):
        """View cost history for this product."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cost History - %s') % self.name,
            'res_model': 'ingredient.cost.history',
            'view_mode': 'list,graph,pivot',
            'domain': [('product_id', '=', self.id)],
            'context': {'default_product_id': self.id},
        }

    def get_price_trend(self, days=30):
        """Get the price trend for this product."""
        self.ensure_one()
        return self.env['ingredient.cost.history'].get_price_trend(self.id, days)

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
