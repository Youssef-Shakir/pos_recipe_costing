# -*- coding: utf-8 -*-
from odoo import api, fields, models


class RecipeIngredientLine(models.Model):
    _name = 'recipe.ingredient.line'
    _description = 'Recipe Ingredient Line'
    _order = 'sequence, id'

    recipe_id = fields.Many2one(
        'restaurant.recipe',
        string='Recipe',
        required=True,
        ondelete='cascade'
    )
    sequence = fields.Integer(string='Sequence', default=10)

    # Ingredient product
    product_id = fields.Many2one(
        'product.product',
        string='Ingredient',
        required=True,
        domain="[('is_ingredient', '=', True)]"
    )

    # Quantity and UoM
    quantity = fields.Float(string='Quantity', required=True, default=1.0)
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True
    )

    # Cost fields
    unit_cost = fields.Float(
        string='Unit Cost',
        related='product_id.standard_price',
        readonly=True
    )
    currency_id = fields.Many2one(
        related='recipe_id.currency_id',
        depends=['recipe_id.currency_id']
    )
    cost = fields.Float(
        string='Cost',
        compute='_compute_cost',
        store=True
    )

    # Stock tracking
    available_qty = fields.Float(
        string='Available',
        related='product_id.qty_available',
        readonly=True
    )

    @api.depends('quantity', 'unit_cost', 'product_id.standard_price')
    def _compute_cost(self):
        for line in self:
            line.cost = line.quantity * line.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
