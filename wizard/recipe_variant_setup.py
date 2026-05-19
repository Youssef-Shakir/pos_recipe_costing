# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RecipeVariantSetup(models.TransientModel):
    _name = 'recipe.variant.setup'
    _description = 'Bulk Recipe Setup for Product Variants'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        domain="[('available_in_pos', '=', True)]"
    )
    recipe_type = fields.Selection([
        ('dish', 'Dish/Menu Item'),
        ('component', 'Component/Sub-Recipe'),
        ('drink', 'Beverage'),
        ('dessert', 'Dessert'),
    ], string='Recipe Type', default='dish', required=True)
    portion_size = fields.Float(string='Portions per Recipe', default=1.0)

    copy_from_recipe_id = fields.Many2one(
        'restaurant.recipe',
        string='Copy Ingredients From',
        help='Load ingredients from an existing recipe as a starting point'
    )

    # Common ingredients — copied to every variant recipe
    ingredient_line_ids = fields.One2many(
        'recipe.variant.setup.ingredient', 'wizard_id',
        string='Base Ingredients'
    )

    # Per-variant extras — only added to the specific variant's recipe
    extra_line_ids = fields.One2many(
        'recipe.variant.setup.extra', 'wizard_id',
        string='Variant-Specific Extras'
    )

    # Many2many is reliable across dialog saves — variant_id in extra lines is editable so no issue
    selected_variant_ids = fields.Many2many(
        'product.product',
        'recipe_setup_sel_variant_rel',
        'wizard_id', 'product_id',
        string='Create Recipes For',
        domain="[('product_tmpl_id', '=', product_tmpl_id), ('available_in_pos', '=', True)]"
    )

    existing_recipe_variant_ids = fields.Many2many(
        'product.product',
        'recipe_setup_exist_variant_rel',
        'wizard_id', 'product_id',
        string='Already Have a Recipe',
        compute='_compute_existing_recipe_variants',
    )

    selected_count = fields.Integer(compute='_compute_selected_count')

    @api.depends('selected_variant_ids')
    def _compute_selected_count(self):
        for wiz in self:
            wiz.selected_count = len(wiz.selected_variant_ids)

    @api.depends('product_tmpl_id')
    def _compute_existing_recipe_variants(self):
        for wiz in self:
            if not wiz.product_tmpl_id:
                wiz.existing_recipe_variant_ids = False
                continue
            existing = self.env['restaurant.recipe'].search([
                ('product_tmpl_id', '=', wiz.product_tmpl_id.id)
            ]).mapped('product_id')
            wiz.existing_recipe_variant_ids = existing

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        tmpl_id = res.get('product_tmpl_id') or self.env.context.get('default_product_tmpl_id')
        if tmpl_id:
            tmpl = self.env['product.template'].browse(tmpl_id)
            existing_ids = self.env['restaurant.recipe'].search([
                ('product_tmpl_id', '=', tmpl.id)
            ]).mapped('product_id').ids
            without_recipe = tmpl.product_variant_ids.filtered(
                lambda v: v.id not in existing_ids
            )
            if 'selected_variant_ids' in fields_list:
                res['selected_variant_ids'] = [(6, 0, without_recipe.ids)]
        return res

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        self.selected_variant_ids = False
        self.copy_from_recipe_id = False
        self.ingredient_line_ids = [(5,)]
        self.extra_line_ids = [(5,)]
        if not self.product_tmpl_id:
            return
        existing_ids = self.env['restaurant.recipe'].search([
            ('product_tmpl_id', '=', self.product_tmpl_id.id)
        ]).mapped('product_id').ids
        self.selected_variant_ids = self.product_tmpl_id.product_variant_ids.filtered(
            lambda v: v.id not in existing_ids
        )

    @api.onchange('copy_from_recipe_id')
    def _onchange_copy_from_recipe_id(self):
        if not self.copy_from_recipe_id:
            return
        self.ingredient_line_ids = [(5,)]
        lines = []
        for line in self.copy_from_recipe_id.ingredient_line_ids:
            lines.append((0, 0, {
                'product_id': line.product_id.id,
                'quantity': line.quantity,
                'uom_id': line.uom_id.id,
            }))
        self.ingredient_line_ids = lines
        self.recipe_type = self.copy_from_recipe_id.recipe_type
        self.portion_size = self.copy_from_recipe_id.portion_size

    def action_create_recipes(self):
        self.ensure_one()

        if not self.selected_variant_ids:
            raise UserError(_('Please select at least one variant to create a recipe for.'))

        base_ingredient_vals = [
            (0, 0, {
                'product_id': ing.product_id.id,
                'quantity': ing.quantity,
                'uom_id': ing.uom_id.id,
            })
            for ing in self.ingredient_line_ids
            if ing.product_id and ing.uom_id
        ]

        # Index extras by attribute value ID for O(1) lookup per variant
        extras_by_attr_val = {}
        for extra in self.extra_line_ids:
            if extra.attribute_value_id and extra.product_id and extra.uom_id:
                extras_by_attr_val.setdefault(extra.attribute_value_id.id, []).append(extra)

        Recipe = self.env['restaurant.recipe']
        created_ids = []
        skipped = []

        for variant in self.selected_variant_ids:
            existing = Recipe.search([('product_id', '=', variant.id)], limit=1)
            if existing:
                skipped.append(variant.display_name)
                continue

            # Start with base ingredients, then add every extra whose attribute value
            # is present on this variant (handles milk/flavor/shots independently)
            ingredient_vals = list(base_ingredient_vals)
            variant_attr_val_ids = set(variant.product_template_attribute_value_ids.ids)
            for attr_val_id, extras in extras_by_attr_val.items():
                if attr_val_id in variant_attr_val_ids:
                    for extra in extras:
                        ingredient_vals.append((0, 0, {
                            'product_id': extra.product_id.id,
                            'quantity': extra.quantity,
                            'uom_id': extra.uom_id.id,
                        }))

            recipe = Recipe.create({
                'name': variant.display_name,
                'product_id': variant.id,
                'recipe_type': self.recipe_type,
                'portion_size': self.portion_size,
                'ingredient_line_ids': ingredient_vals,
            })
            created_ids.append(recipe.id)

        if not created_ids:
            raise UserError(_(
                'No recipes were created. All selected variants already have a recipe:\n%s'
            ) % '\n'.join(skipped))

        if len(created_ids) == 1:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Recipe'),
                'res_model': 'restaurant.recipe',
                'view_mode': 'form',
                'res_id': created_ids[0],
                'target': 'current',
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Created Recipes (%d)') % len(created_ids),
            'res_model': 'restaurant.recipe',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created_ids)],
            'target': 'current',
        }


class RecipeVariantSetupIngredient(models.TransientModel):
    _name = 'recipe.variant.setup.ingredient'
    _description = 'Base Ingredient Line for Variant Recipe Setup'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('recipe.variant.setup', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one(
        'product.product', string='Ingredient', required=True,
        domain="[('is_ingredient', '=', True)]",
        context="{'default_is_ingredient': True}"
    )
    quantity = fields.Float(string='Quantity', required=True, default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit', required=True)
    unit_cost = fields.Float(related='product_id.standard_price', string='Unit Cost', readonly=True)
    cost = fields.Float(string='Cost', compute='_compute_cost', store=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id
    )

    @api.depends('quantity', 'unit_cost')
    def _compute_cost(self):
        for line in self:
            line.cost = line.quantity * line.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id


class RecipeVariantSetupExtra(models.TransientModel):
    _name = 'recipe.variant.setup.extra'
    _description = 'Per-Attribute-Value Extra Ingredient for Recipe Setup'
    _order = 'sequence, id'

    wizard_id = fields.Many2one('recipe.variant.setup', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)

    # Target an attribute VALUE (e.g. "Oat Milk"), not a full variant combination.
    # This row then applies to every variant that carries that attribute value.
    # attribute_value_id is editable (required) so it IS sent back on dialog save.
    attribute_value_id = fields.Many2one(
        'product.template.attribute.value',
        string='When Attribute Is',
        required=True,
        domain="[('product_tmpl_id', '=', parent.product_tmpl_id)]",
        help='Pick one attribute value (e.g. "Oat Milk"). '
             'The ingredient below will be added to every variant that includes it.'
    )
    # Shown readonly so the user understands which axis this rule belongs to
    attribute_id = fields.Many2one(
        'product.attribute',
        related='attribute_value_id.attribute_id',
        string='Attribute',
        readonly=True,
    )

    product_id = fields.Many2one(
        'product.product', string='Add Ingredient', required=True,
        domain="[('is_ingredient', '=', True)]",
        context="{'default_is_ingredient': True}"
    )
    quantity = fields.Float(string='Quantity', required=True, default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit', required=True)
    unit_cost = fields.Float(related='product_id.standard_price', string='Unit Cost', readonly=True)
    currency_id = fields.Many2one(
        'res.currency', default=lambda self: self.env.company.currency_id
    )

    @api.onchange('attribute_value_id')
    def _onchange_attribute_value_id(self):
        if not self.attribute_value_id:
            return
        # product.template.attribute.value → product.attribute.value → default_ingredient_id
        base_val = self.attribute_value_id.product_attribute_value_id
        if base_val.default_ingredient_id:
            self.product_id = base_val.default_ingredient_id
            self.uom_id = base_val.default_ingredient_id.uom_id

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
