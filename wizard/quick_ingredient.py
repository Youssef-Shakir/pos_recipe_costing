# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class QuickIngredient(models.TransientModel):
    _name = 'recipe.quick.ingredient'
    _description = 'Quick Add Ingredient'

    name = fields.Char(string='Ingredient Name', required=True)
    category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        default=lambda self: self._default_category()
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
    ], string='Ingredient Type', default='other')
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        required=True,
        default=lambda self: self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
    )
    uom_po_id = fields.Many2one(
        'uom.uom',
        string='Purchase UoM',
        help="Unit of measure for purchasing (e.g., kg, box)"
    )
    cost = fields.Float(string='Cost Price', required=True)
    supplier_id = fields.Many2one(
        'res.partner',
        string='Supplier',
        domain="[('is_company', '=', True)]"
    )
    barcode = fields.Char(string='Barcode')
    internal_reference = fields.Char(string='Internal Reference')

    @api.model
    def _default_category(self):
        ICP = self.env['ir.config_parameter'].sudo()
        category_id = ICP.get_param('pos_recipe_costing.ingredient_category_id')
        if category_id:
            return int(category_id)
        return False

    @api.onchange('uom_id')
    def _onchange_uom_id(self):
        if self.uom_id and not self.uom_po_id:
            self.uom_po_id = self.uom_id

    def action_create_ingredient(self):
        """Create the ingredient product"""
        self.ensure_one()

        product_vals = {
            'name': self.name,
            'type': 'consu',
            'is_storable': True,
            'is_ingredient': True,
            'available_in_pos': True,
            'ingredient_category': self.ingredient_category,
            'categ_id': self.category_id.id if self.category_id else self.env.ref('product.product_category_all').id,
            'uom_id': self.uom_id.id,
            'uom_po_id': self.uom_po_id.id if self.uom_po_id else self.uom_id.id,
            'standard_price': self.cost,
            'barcode': self.barcode,
            'default_code': self.internal_reference,
        }

        product = self.env['product.product'].create(product_vals)

        # Add supplier if specified
        if self.supplier_id:
            self.env['product.supplierinfo'].create({
                'product_tmpl_id': product.product_tmpl_id.id,
                'partner_id': self.supplier_id.id,
                'price': self.cost,
            })

        # Return action to view the created product
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredient Created'),
            'res_model': 'product.product',
            'view_mode': 'form',
            'res_id': product.id,
            'target': 'current',
        }

    def action_create_and_new(self):
        """Create ingredient and open form for another"""
        self.action_create_ingredient()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quick Add Ingredient'),
            'res_model': 'recipe.quick.ingredient',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
