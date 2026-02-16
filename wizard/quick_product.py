# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class QuickProduct(models.TransientModel):
    _name = 'recipe.quick.product'
    _description = 'Quick Add Menu Item'

    name = fields.Char(string='Menu Item Name', required=True)
    category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        default=lambda self: self._default_category()
    )
    pos_categ_id = fields.Many2one(
        'pos.category',
        string='POS Category',
        default=lambda self: self._default_pos_category()
    )
    recipe_type = fields.Selection([
        ('dish', 'Dish/Menu Item'),
        ('drink', 'Beverage'),
        ('dessert', 'Dessert'),
        ('component', 'Component/Sub-Recipe'),
    ], string='Type', default='dish', required=True)
    selling_price = fields.Float(string='Selling Price', required=True)
    image = fields.Binary(string='Image')
    description = fields.Text(string='Description')
    barcode = fields.Char(string='Barcode')
    internal_reference = fields.Char(string='Internal Reference')

    # Recipe fields
    create_recipe = fields.Boolean(string='Create Recipe', default=True)
    portion_size = fields.Float(string='Portions', default=1.0)

    @api.model
    def _default_category(self):
        ICP = self.env['ir.config_parameter'].sudo()
        category_id = ICP.get_param('pos_recipe_costing.product_category_id')
        if category_id:
            return int(category_id)
        return False

    @api.model
    def _default_pos_category(self):
        ICP = self.env['ir.config_parameter'].sudo()
        pos_category_id = ICP.get_param('pos_recipe_costing.pos_category_id')
        if pos_category_id:
            return int(pos_category_id)
        return False

    def action_create_product(self):
        """Create the menu item product and optionally a recipe"""
        self.ensure_one()

        product_vals = {
            'name': self.name,
            'type': 'consu',  # Consumable - BOM handles stock
            'available_in_pos': True,
            'categ_id': self.category_id.id if self.category_id else self.env.ref('product.product_category_all').id,
            'list_price': self.selling_price,
            'image_1920': self.image,
            'description_sale': self.description,
            'barcode': self.barcode,
            'default_code': self.internal_reference,
        }

        if self.pos_categ_id:
            product_vals['pos_categ_ids'] = [(4, self.pos_categ_id.id)]

        product = self.env['product.product'].create(product_vals)

        # Create recipe if requested
        if self.create_recipe:
            recipe = self.env['restaurant.recipe'].create({
                'name': self.name,
                'product_id': product.id,
                'recipe_type': self.recipe_type,
                'portion_size': self.portion_size,
            })
            # Return action to edit the recipe (add ingredients)
            return {
                'type': 'ir.actions.act_window',
                'name': _('Add Ingredients to Recipe'),
                'res_model': 'restaurant.recipe',
                'view_mode': 'form',
                'res_id': recipe.id,
                'target': 'current',
            }

        # Return action to view the created product
        return {
            'type': 'ir.actions.act_window',
            'name': _('Menu Item Created'),
            'res_model': 'product.product',
            'view_mode': 'form',
            'res_id': product.id,
            'target': 'current',
        }

    def action_create_and_new(self):
        """Create product and open form for another"""
        result = self.action_create_product()
        # If we created a recipe, still allow creating another product
        return {
            'type': 'ir.actions.act_window',
            'name': _('Quick Add Menu Item'),
            'res_model': 'recipe.quick.product',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }
