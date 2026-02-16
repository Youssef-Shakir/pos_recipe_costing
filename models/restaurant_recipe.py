# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


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

    _sql_constraints = [
        ('product_unique', 'unique(product_id)', 'A recipe already exists for this product!')
    ]

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

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for record in records:
            if record.ingredient_line_ids:
                record._sync_bom()
        return records

    def write(self, vals):
        res = super().write(vals)
        # Sync BOM if ingredients or product changed
        if 'ingredient_line_ids' in vals or 'product_id' in vals or 'portion_size' in vals:
            for record in self:
                record._sync_bom()
        return res

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
