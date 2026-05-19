# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    default_ingredient_id = fields.Many2one(
        'product.product',
        string='Default Ingredient',
        domain="[('is_ingredient', '=', True)]",
        help='Auto-filled in the variant recipe setup wizard when this attribute value is selected.'
    )
