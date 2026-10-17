# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools import float_compare


class RestaurantRecipe(models.Model):
    _name = 'restaurant.recipe'
    _description = 'Restaurant Recipe'
    _order = 'name'

    name = fields.Char(string='Recipe Name', required=True)
    product_id = fields.Many2one(
        'product.product',
        string='Menu Item',
        required=True,
        domain="[('available_in_pos', '=', True)]"
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        related='product_id.product_tmpl_id',
        store=True
    )

    active = fields.Boolean(default=True)
    recipe_type = fields.Selection([
        ('dish', 'Dish/Menu Item'),
        ('component', 'Component/Sub-Recipe'),
        ('drink', 'Beverage'),
        ('dessert', 'Dessert'),
    ], string='Type', default='dish', required=True)

    portion_size = fields.Float(string='Portions', default=1.0, help="Number of portions this recipe yields")

    # Ingredient lines (BOM/Kit)
    ingredient_line_ids = fields.One2many(
        'recipe.ingredient.line',
        'recipe_id',
        string='Ingredients'
    )
    ingredient_count = fields.Integer(
        string='Ingredient Count',
        compute='_compute_ingredient_count'
    )

    # MRP BOM Integration
    bom_id = fields.Many2one(
        'mrp.bom',
        string='Bill of Materials',
        readonly=True,
        copy=False
    )
    bom_type = fields.Selection(
        related='bom_id.type',
        string='BOM Type'
    )

    # Cost fields
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id
    )
    total_cost = fields.Float(
        string='Total Recipe Cost',
        compute='_compute_total_cost',
        store=True
    )
    cost_per_portion = fields.Float(
        string='Cost per Portion',
        compute='_compute_costs',
        store=True
    )
    selling_price = fields.Float(
        string='Selling Price',
        related='product_id.lst_price'
    )
    food_cost_percentage = fields.Float(
        string='Food Cost %',
        compute='_compute_costs',
        store=True
    )
    profit_margin = fields.Float(
        string='Profit Margin',
        compute='_compute_costs',
        store=True
    )

    # Preparation info
    prep_time = fields.Float(string='Prep Time (mins)')
    cook_time = fields.Float(string='Cook Time (mins)')
    instructions = fields.Html(string='Preparation Instructions')

    # Linked variant recipes (other recipes for the same product template)
    variant_recipe_ids = fields.Many2many(
        'restaurant.recipe',
        string='Other Variant Recipes',
        compute='_compute_variant_recipes',
    )
    variant_recipe_count = fields.Integer(
        string='Variant Recipes',
        compute='_compute_variant_recipes',
    )

    _sql_constraints = [
        ('product_unique', 'unique(product_id)', 'A recipe already exists for this product!')
    ]

    # Cost history
    cost_history_count = fields.Integer(
        string='Cost History Count',
        compute='_compute_cost_history_count'
    )
    # Store previous cost for tracking changes
    _previous_cost_per_portion = fields.Float(copy=False)
    _previous_portion_size = fields.Float(copy=False)

    def _compute_cost_history_count(self):
        CostHistory = self.env['recipe.cost.history']
        for recipe in self:
            recipe.cost_history_count = CostHistory.search_count([
                ('recipe_id', '=', recipe.id)
            ])

    @api.depends('ingredient_line_ids')
    def _compute_ingredient_count(self):
        for recipe in self:
            recipe.ingredient_count = len(recipe.ingredient_line_ids)

    @api.depends('ingredient_line_ids.cost')
    def _compute_total_cost(self):
        for recipe in self:
            recipe.total_cost = sum(recipe.ingredient_line_ids.mapped('cost'))

    @api.depends('total_cost', 'portion_size', 'selling_price')
    def _compute_costs(self):
        for recipe in self:
            if recipe.portion_size:
                recipe.cost_per_portion = recipe.total_cost / recipe.portion_size
            else:
                recipe.cost_per_portion = recipe.total_cost

            if recipe.selling_price:
                recipe.food_cost_percentage = (recipe.cost_per_portion / recipe.selling_price) * 100
                recipe.profit_margin = recipe.selling_price - recipe.cost_per_portion
            else:
                recipe.food_cost_percentage = 0
                recipe.profit_margin = 0

    @api.depends('product_tmpl_id', 'product_tmpl_id.recipe_ids')
    def _compute_variant_recipes(self):
        for recipe in self:
            siblings = recipe.product_tmpl_id.recipe_ids.filtered(
                lambda r: r.id != recipe._origin.id
            )
            recipe.variant_recipe_ids = siblings
            recipe.variant_recipe_count = len(siblings)

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.ingredient_line_ids:
                record._sync_bom()
            # Store initial values for tracking
            record._previous_cost_per_portion = record.cost_per_portion
            record._previous_portion_size = record.portion_size
        return records

    def write(self, vals):
        # Capture old values before write for cost history tracking
        old_values = {}
        track_cost = 'ingredient_line_ids' in vals or 'portion_size' in vals
        if track_cost:
            for record in self:
                old_values[record.id] = {
                    'cost_per_portion': record.cost_per_portion,
                    'portion_size': record.portion_size,
                    'food_cost_percentage': record.food_cost_percentage,
                }

        res = super().write(vals)

        # Sync BOM if ingredients or product changed
        if 'ingredient_line_ids' in vals or 'product_id' in vals or 'portion_size' in vals:
            for record in self:
                record._sync_bom()

        # Track cost changes
        if track_cost:
            self._track_cost_changes(vals, old_values)

        return res

    def _track_cost_changes(self, vals, old_values):
        """Track recipe cost changes and create history records."""
        CostHistory = self.env['recipe.cost.history']

        # Determine trigger
        if 'portion_size' in vals:
            trigger = 'portion_change'
        elif 'ingredient_line_ids' in vals:
            trigger = 'recipe_edit'
        else:
            trigger = 'ingredient_change'

        for record in self:
            old_data = old_values.get(record.id, {})
            old_cost = old_data.get('cost_per_portion', 0)
            new_cost = record.cost_per_portion

            # Only create history if cost actually changed
            if float_compare(old_cost, new_cost, precision_digits=4) != 0:
                CostHistory.create({
                    'recipe_id': record.id,
                    'old_cost': old_cost,
                    'new_cost': new_cost,
                    'trigger': trigger,
                    'old_portion_size': old_data.get('portion_size', record.portion_size),
                    'new_portion_size': record.portion_size,
                    'old_food_cost_percentage': old_data.get('food_cost_percentage', 0),
                    'new_food_cost_percentage': record.food_cost_percentage,
                    'changed_by': self.env.user.id,
                })

    def _trigger_cost_history_from_ingredient(self, ingredient_product_ids):
        """Called when ingredient prices change to track recipe cost impact.

        This method should be called from ingredient.cost.history or
        product write to propagate cost changes to affected recipes.
        """
        CostHistory = self.env['recipe.cost.history']
        RecipeLine = self.env['recipe.ingredient.line']

        # Find recipes using these ingredients
        lines = RecipeLine.search([
            ('product_id', 'in', ingredient_product_ids)
        ])
        recipe_ids = lines.mapped('recipe_id').ids

        for recipe in self.browse(recipe_ids):
            # Get the stored previous cost
            old_cost = recipe._previous_cost_per_portion or 0

            # Recompute costs
            recipe._compute_total_cost()
            recipe._compute_costs()
            new_cost = recipe.cost_per_portion

            if float_compare(old_cost, new_cost, precision_digits=4) != 0:
                CostHistory.create({
                    'recipe_id': recipe.id,
                    'old_cost': old_cost,
                    'new_cost': new_cost,
                    'trigger': 'ingredient_change',
                    'old_portion_size': recipe.portion_size,
                    'new_portion_size': recipe.portion_size,
                    'old_food_cost_percentage': (old_cost / recipe.selling_price * 100) if recipe.selling_price else 0,
                    'new_food_cost_percentage': recipe.food_cost_percentage,
                    'notes': _('Triggered by ingredient price change'),
                })

                # Update stored cost
                recipe._previous_cost_per_portion = new_cost

    def unlink(self):
        # Delete associated BOMs
        boms = self.mapped('bom_id')
        res = super().unlink()
        boms.unlink()
        return res

    def _sync_bom(self):
        """Create or update the MRP BOM from recipe ingredients"""
        self.ensure_one()

        if not self.ingredient_line_ids:
            # No ingredients, delete BOM if exists
            if self.bom_id:
                self.bom_id.unlink()
                self.bom_id = False
            return

        BOM = self.env['mrp.bom']
        BOMLine = self.env['mrp.bom.line']

        # Prepare BOM values
        bom_vals = {
            'product_tmpl_id': self.product_tmpl_id.id,
            'product_id': self.product_id.id,
            'product_qty': self.portion_size or 1.0,
            'type': 'phantom',  # Kit - auto consumes on sale
            'code': f'RECIPE-{self.id}',
        }

        if self.bom_id:
            # Update existing BOM
            self.bom_id.write(bom_vals)
            # Remove old lines and create new ones
            self.bom_id.bom_line_ids.unlink()
        else:
            # Create new BOM
            self.bom_id = BOM.create(bom_vals)

        # Create BOM lines from recipe ingredients
        for line in self.ingredient_line_ids:
            BOMLine.create({
                'bom_id': self.bom_id.id,
                'product_id': line.product_id.id,
                'product_qty': line.quantity,
                'product_uom_id': line.uom_id.id,
            })

    def action_view_bom(self):
        """Open the linked BOM"""
        self.ensure_one()
        if not self.bom_id:
            raise UserError(_('No BOM exists for this recipe. Add ingredients first.'))
        return {
            'type': 'ir.actions.act_window',
            'name': 'Bill of Materials',
            'res_model': 'mrp.bom',
            'view_mode': 'form',
            'res_id': self.bom_id.id,
        }

    def action_create_bom(self):
        """Force create/sync BOM"""
        for recipe in self:
            if not recipe.ingredient_line_ids:
                raise UserError(_('Add ingredients before creating a BOM.'))
            recipe._sync_bom()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('BOM Synced'),
                'message': _('Bill of Materials has been created/updated.'),
                'type': 'success',
            }
        }

    def action_recalculate_costs(self):
        """Force recalculate all costs"""
        for recipe in self:
            recipe.ingredient_line_ids._compute_cost()
            recipe._compute_total_cost()
            recipe._compute_costs()
        return True

    def action_update_product_cost(self):
        """Update the linked product's standard price with recipe cost"""
        for recipe in self:
            if recipe.product_id and recipe.cost_per_portion:
                recipe.product_id.standard_price = recipe.cost_per_portion
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cost Updated'),
                'message': _('Product cost has been updated from recipe.'),
                'type': 'success',
            }
        }

    def action_open_variant_recipe_setup(self):
        """Open the variant recipe setup wizard.

        Works from both the form (single record) and the list header (one or more selected).
        Pre-fills the product template from the first selected record if available.
        """
        tmpl_id = self[:1].product_tmpl_id.id if self else False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Setup Variant Recipes'),
            'res_model': 'recipe.variant.setup',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_tmpl_id': tmpl_id,
            },
        }

    def action_open_variant_recipe_editor(self):
        """Open the variant recipe editor wizard.

        Allows editing existing recipes for all variants of a product template.
        """
        tmpl_id = self[:1].product_tmpl_id.id if self else False
        return {
            'type': 'ir.actions.act_window',
            'name': _('Edit Variant Recipes'),
            'res_model': 'recipe.variant.editor',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_product_tmpl_id': tmpl_id,
            },
        }

    def action_view_variant_recipes(self):
        self.ensure_one()
        sibling_ids = self.product_tmpl_id.recipe_ids.filtered(
            lambda r: r.id != self.id
        ).ids
        return {
            'type': 'ir.actions.act_window',
            'name': _('Variant Recipes — %s') % self.product_tmpl_id.name,
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('id', 'in', sibling_ids)],
            'target': 'current',
        }

    def action_view_cost_history(self):
        """View cost history for this recipe."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cost History - %s') % self.name,
            'res_model': 'recipe.cost.history',
            'view_mode': 'list,graph,pivot',
            'domain': [('recipe_id', '=', self.id)],
            'context': {'default_recipe_id': self.id},
        }

    def get_cost_trend(self, days=30):
        """Get the cost trend for this recipe."""
        self.ensure_one()
        return self.env['recipe.cost.history'].get_recipe_trend(self.id, days)

    def action_print_variant_recipes(self):
        """Print all variant recipes for the same product template.

        This action prints a comprehensive comparison report showing all
        variant recipes, highlighting common and unique ingredients.
        """
        self.ensure_one()
        if not self.product_tmpl_id:
            raise UserError(_('No product template linked to this recipe.'))

        # Get all recipes for this product template
        all_recipes = self.product_tmpl_id.recipe_ids
        if not all_recipes:
            raise UserError(_('No recipes found for this product template.'))

        # Return the report action for the product template
        return self.env.ref(
            'pos_recipe_costing.action_report_variant_recipes'
        ).report_action(self.product_tmpl_id)

    def action_print_kitchen_cards(self):
        """Print kitchen-friendly recipe cards for all variants.

        Generates large, easy-to-read recipe cards suitable for kitchen use.
        """
        self.ensure_one()
        if not self.product_tmpl_id:
            raise UserError(_('No product template linked to this recipe.'))

        return self.env.ref(
            'pos_recipe_costing.action_report_variant_recipes_kitchen'
        ).report_action(self.product_tmpl_id)

    def get_variant_comparison_data(self):
        """Get comparison data for all variant recipes of the same product template.

        Returns a dictionary containing:
        - common_ingredients: List of ingredients present in ALL variants with same quantity
        - unique_ingredients: Dict mapping recipe_id to list of unique ingredients
        - all_ingredients: List of all ingredients with variant presence info
        - quantity_differences: Ingredients with different quantities across variants

        This method is called from the report template.
        """
        self.ensure_one()
        return self.product_tmpl_id._get_variant_comparison_data()
