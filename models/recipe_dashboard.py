# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class RecipeDashboard(models.Model):
    _name = 'recipe.dashboard'
    _description = 'Recipe Dashboard'

    name = fields.Char(default='Dashboard')

    @api.model
    def action_open_dashboard(self):
        """Open or create the dashboard singleton record"""
        dashboard = self.search([], limit=1)
        if not dashboard:
            dashboard = self.create({'name': 'Recipe Dashboard'})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipe Dashboard'),
            'res_model': 'recipe.dashboard',
            'view_mode': 'form',
            'res_id': dashboard.id,
            'target': 'current',
            'context': {'create': False},
        }

    # Statistics
    recipe_count = fields.Integer(compute='_compute_stats')
    ingredient_count = fields.Integer(compute='_compute_stats')
    pos_product_count = fields.Integer(compute='_compute_stats')
    products_without_recipe = fields.Integer(compute='_compute_stats')
    avg_food_cost = fields.Float(compute='_compute_stats')
    low_margin_count = fields.Integer(compute='_compute_stats')
    variants_without_recipe_count = fields.Integer(compute='_compute_stats')
    pos_template_count = fields.Integer(compute='_compute_stats')
    component_count = fields.Integer(compute='_compute_stats', string='Components')
    kitchen_made_count = fields.Integer(compute='_compute_stats', string='Kitchen Made')
    buy_sell_count = fields.Integer(compute='_compute_stats', string='Buy & Sell')

    # Waste statistics
    waste_count = fields.Integer(compute='_compute_stats', string='Waste Records')
    waste_value = fields.Float(compute='_compute_stats', string='Waste Value')

    # Consumption statistics
    this_month_consumption_value = fields.Float(
        compute='_compute_stats',
        string='This Month Consumption'
    )
    consumption_line_count = fields.Integer(
        compute='_compute_stats',
        string='Consumption Lines'
    )

    # Cost history statistics
    cost_changes_this_month = fields.Integer(
        compute='_compute_stats',
        string='Cost Changes This Month'
    )
    avg_price_increase = fields.Float(
        compute='_compute_stats',
        string='Avg Price Increase %'
    )
    ingredient_cost_changes = fields.Integer(
        compute='_compute_stats',
        string='Ingredient Cost Changes'
    )
    recipe_cost_changes = fields.Integer(
        compute='_compute_stats',
        string='Recipe Cost Changes'
    )

    def _compute_stats(self):
        Recipe = self.env['restaurant.recipe']
        Product = self.env['product.product']
        ProductTemplate = self.env['product.template']
        Waste = self.env['ingredient.waste']
        ConsumptionLine = self.env['ingredient.consumption.line']
        IngredientCostHistory = self.env['ingredient.cost.history']
        RecipeCostHistory = self.env['recipe.cost.history']

        ICP = self.env['ir.config_parameter'].sudo()
        threshold = float(ICP.get_param('pos_recipe_costing.high_food_cost_threshold', 35))

        recipes = Recipe.search([])
        components = Recipe.search([('recipe_type', '=', 'component')])
        ingredients = Product.search([('is_ingredient', '=', True)])
        pos_menu_items = Product.search([
            ('available_in_pos', '=', True),
            ('is_ingredient', '=', False)
        ])
        products_with_recipe = recipes.mapped('product_id')
        variants_without = pos_menu_items - products_with_recipe

        # Count by production type
        kitchen_made = ProductTemplate.search_count([
            ('available_in_pos', '=', True),
            ('production_type', '=', 'kitchen')
        ])
        buy_sell = ProductTemplate.search_count([
            ('available_in_pos', '=', True),
            ('production_type', '=', 'buy_sell')
        ])

        # Waste statistics (this month)
        from datetime import date, datetime
        first_of_month = date.today().replace(day=1)
        first_of_month_dt = datetime.combine(first_of_month, datetime.min.time())
        waste_records = Waste.search([
            ('state', '=', 'confirmed'),
            ('date', '>=', first_of_month)
        ])
        waste_total_value = sum(waste_records.mapped('cost'))

        # Consumption statistics (this month)
        consumption_lines = ConsumptionLine.search([
            ('date', '>=', first_of_month)
        ])
        consumption_total_value = sum(consumption_lines.mapped('cost'))

        # Cost history statistics (this month)
        ingredient_cost_changes = IngredientCostHistory.search([
            ('change_date', '>=', first_of_month_dt)
        ])
        recipe_cost_changes = RecipeCostHistory.search([
            ('change_date', '>=', first_of_month_dt)
        ])

        # Calculate average price increase (only positive changes)
        positive_changes = ingredient_cost_changes.filtered(lambda c: c.change_percentage > 0)
        avg_increase = sum(positive_changes.mapped('change_percentage')) / len(positive_changes) if positive_changes else 0

        for rec in self:
            rec.recipe_count = len(recipes)
            rec.ingredient_count = len(ingredients)
            rec.pos_product_count = len(pos_menu_items)
            rec.products_without_recipe = len(variants_without)
            rec.avg_food_cost = sum(recipes.mapped('food_cost_percentage')) / len(recipes) if recipes else 0
            rec.low_margin_count = len(recipes.filtered(lambda r: r.food_cost_percentage > threshold))
            rec.variants_without_recipe_count = len(variants_without)
            rec.pos_template_count = len(pos_menu_items.mapped('product_tmpl_id'))
            rec.component_count = len(components)
            rec.kitchen_made_count = kitchen_made
            rec.buy_sell_count = buy_sell
            rec.waste_count = len(waste_records)
            rec.waste_value = waste_total_value
            rec.this_month_consumption_value = consumption_total_value
            rec.consumption_line_count = len(consumption_lines)
            # Cost history stats
            rec.ingredient_cost_changes = len(ingredient_cost_changes)
            rec.recipe_cost_changes = len(recipe_cost_changes)
            rec.cost_changes_this_month = len(ingredient_cost_changes) + len(recipe_cost_changes)
            rec.avg_price_increase = avg_increase

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
            'domain': [('available_in_pos', '=', True), ('is_ingredient', '=', False)],
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
            'domain': [
                ('available_in_pos', '=', True),
                ('is_ingredient', '=', False),
                ('id', 'not in', products_with_recipe.ids)
            ],
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

    def action_new_stocktake(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Stocktake'),
            'res_model': 'ingredient.stocktake',
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_stocktakes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredient Stocktakes'),
            'res_model': 'ingredient.stocktake',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_print_all_recipes(self):
        recipes = self.env['restaurant.recipe'].search([])
        if not recipes:
            from odoo.exceptions import UserError
            raise UserError(_('No recipes found to print.'))
        return self.env.ref('pos_recipe_costing.action_report_all_recipes').report_action(recipes)

    def action_setup_variant_recipes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Setup Variant Recipes'),
            'res_model': 'recipe.variant.setup',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_edit_variant_recipes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit Variant Recipes'),
            'res_model': 'recipe.variant.editor',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_attributes(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Product Attributes & Default Ingredients'),
            'res_model': 'product.attribute',
            'view_mode': 'list,form',
            'target': 'current',
        }

    def action_variants_without_recipe(self):
        Recipe = self.env['restaurant.recipe']
        products_with_recipe_ids = Recipe.search([]).mapped('product_id').ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Variants Without a Recipe'),
            'res_model': 'product.product',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('pos_recipe_costing.view_pos_product_recipe_list').id, 'list'),
                (False, 'form'),
            ],
            'domain': [
                ('available_in_pos', '=', True),
                ('is_ingredient', '=', False),
                ('id', 'not in', products_with_recipe_ids),
            ],
            'target': 'current',
        }

    def action_view_components(self):
        """View all component/sub-recipes (sauces, bases, etc.)"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Components / Sub-Recipes'),
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('recipe_type', '=', 'component')],
            'context': {'default_recipe_type': 'component'},
            'target': 'current',
        }

    def action_add_component(self):
        """Quick add a new component/sub-recipe"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('New Component'),
            'res_model': 'restaurant.recipe',
            'view_mode': 'form',
            'context': {'default_recipe_type': 'component'},
            'target': 'current',
        }

    def action_view_kitchen_made(self):
        """View products made in kitchen"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Kitchen Made Products'),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [
                ('available_in_pos', '=', True),
                ('production_type', '=', 'kitchen')
            ],
            'target': 'current',
        }

    def action_view_buy_sell(self):
        """View buy & sell products"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Buy & Sell Products'),
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [
                ('available_in_pos', '=', True),
                ('production_type', '=', 'buy_sell')
            ],
            'target': 'current',
        }

    def action_new_waste(self):
        """Create a new waste record"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Record Waste'),
            'res_model': 'ingredient.waste',
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_waste(self):
        """View all waste records"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredient Waste'),
            'res_model': 'ingredient.waste',
            'view_mode': 'list,form,graph,pivot',
            'target': 'current',
        }

    def action_view_waste_analysis(self):
        """View waste analysis graph"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Waste Analysis'),
            'res_model': 'ingredient.waste',
            'view_mode': 'graph,pivot,list',
            'domain': [('state', '=', 'confirmed')],
            'context': {'search_default_filter_this_month': 1},
            'target': 'current',
        }

    def action_consumption_report(self):
        """Open the consumption report wizard"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Consumption Report'),
            'res_model': 'consumption.report.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_view_consumption_lines(self):
        """View all consumption lines"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredient Consumption'),
            'res_model': 'ingredient.consumption.line',
            'view_mode': 'list,pivot,graph,form',
            'context': {'search_default_group_by_category': 1},
            'target': 'current',
        }

    def action_view_this_month_consumption(self):
        """View this month's consumption"""
        from datetime import date
        first_of_month = date.today().replace(day=1)
        return {
            'type': 'ir.actions.act_window',
            'name': _('This Month Consumption'),
            'res_model': 'ingredient.consumption.line',
            'view_mode': 'list,pivot,graph,form',
            'domain': [('date', '>=', first_of_month)],
            'context': {'search_default_group_by_category': 1},
            'target': 'current',
        }

    def action_view_ingredient_cost_history(self):
        """View ingredient cost history"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredient Cost History'),
            'res_model': 'ingredient.cost.history',
            'view_mode': 'list,graph,pivot,form',
            'context': {'search_default_filter_this_month': 1},
            'target': 'current',
        }

    def action_view_recipe_cost_history(self):
        """View recipe cost history"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipe Cost History'),
            'res_model': 'recipe.cost.history',
            'view_mode': 'list,graph,pivot,form',
            'context': {'search_default_filter_this_month': 1},
            'target': 'current',
        }

    def action_view_all_cost_history(self):
        """View all cost changes this month"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('All Cost History'),
            'res_model': 'ingredient.cost.history',
            'view_mode': 'list,graph,pivot,form',
            'context': {'search_default_filter_this_month': 1},
            'target': 'current',
        }

    def action_view_price_increases(self):
        """View price increases this month"""
        return {
            'type': 'ir.actions.act_window',
            'name': _('Price Increases'),
            'res_model': 'ingredient.cost.history',
            'view_mode': 'list,graph,pivot,form',
            'context': {
                'search_default_filter_this_month': 1,
                'search_default_filter_increases': 1,
            },
            'target': 'current',
        }
