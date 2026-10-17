# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RecipeVariantEditor(models.TransientModel):
    """Wizard for editing existing variant recipes in bulk.

    Provides a visual matrix-like interface showing all variants for a product
    template with their recipes, allowing quick edits and ingredient management.
    """
    _name = 'recipe.variant.editor'
    _description = 'Edit Variant Recipes'

    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product',
        required=True,
        domain="[('available_in_pos', '=', True)]"
    )

    # Recipe lines for each variant
    variant_line_ids = fields.One2many(
        'recipe.variant.editor.line', 'wizard_id',
        string='Variant Recipes'
    )

    # Summary counts
    total_variants = fields.Integer(compute='_compute_counts')
    variants_with_recipe = fields.Integer(compute='_compute_counts')
    variants_without_recipe = fields.Integer(compute='_compute_counts')

    @api.depends('variant_line_ids', 'variant_line_ids.recipe_id')
    def _compute_counts(self):
        for wiz in self:
            lines = wiz.variant_line_ids
            wiz.total_variants = len(lines)
            wiz.variants_with_recipe = len(lines.filtered('recipe_id'))
            wiz.variants_without_recipe = wiz.total_variants - wiz.variants_with_recipe

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        tmpl_id = res.get('product_tmpl_id') or self.env.context.get('default_product_tmpl_id')
        if tmpl_id and 'variant_line_ids' in fields_list:
            res['variant_line_ids'] = self._prepare_variant_lines(tmpl_id)
        return res

    def _prepare_variant_lines(self, tmpl_id):
        """Prepare variant lines with existing recipes pre-loaded."""
        tmpl = self.env['product.template'].browse(tmpl_id)
        Recipe = self.env['restaurant.recipe']
        lines = []

        for variant in tmpl.product_variant_ids.filtered('available_in_pos'):
            recipe = Recipe.search([('product_id', '=', variant.id)], limit=1)

            # Build attribute description
            attr_desc = ', '.join(
                variant.product_template_attribute_value_ids.mapped('name')
            ) or 'Default'

            vals = {
                'variant_id': variant.id,
                'variant_name': variant.name,
                'attribute_values': attr_desc,
                'recipe_id': recipe.id if recipe else False,
                'has_recipe': bool(recipe),
            }

            # If recipe exists, load its ingredients into the line
            if recipe:
                vals['ingredient_line_ids'] = [
                    (0, 0, {
                        'source_line_id': line.id,
                        'product_id': line.product_id.id,
                        'quantity': line.quantity,
                        'uom_id': line.uom_id.id,
                    })
                    for line in recipe.ingredient_line_ids
                ]

            lines.append((0, 0, vals))

        return lines

    @api.onchange('product_tmpl_id')
    def _onchange_product_tmpl_id(self):
        if not self.product_tmpl_id:
            self.variant_line_ids = [(5,)]
            return

        self.variant_line_ids = self._prepare_variant_lines(self.product_tmpl_id.id)

    def action_save_all_recipes(self):
        """Save changes to all variant recipes."""
        self.ensure_one()

        Recipe = self.env['restaurant.recipe']
        IngredientLine = self.env['recipe.ingredient.line']
        created = 0
        updated = 0

        for line in self.variant_line_ids:
            if not line.variant_id:
                continue

            # Check if we have any ingredients defined
            has_ingredients = bool(line.ingredient_line_ids)

            if line.recipe_id:
                # Update existing recipe
                if has_ingredients:
                    # Delete old ingredient lines and create new ones
                    line.recipe_id.ingredient_line_ids.unlink()
                    for ing in line.ingredient_line_ids:
                        if ing.product_id and ing.uom_id:
                            IngredientLine.create({
                                'recipe_id': line.recipe_id.id,
                                'product_id': ing.product_id.id,
                                'quantity': ing.quantity,
                                'uom_id': ing.uom_id.id,
                            })
                    updated += 1
            elif has_ingredients:
                # Create new recipe
                recipe_vals = {
                    'name': line.variant_name,
                    'product_id': line.variant_id.id,
                    'recipe_type': 'dish',
                    'portion_size': 1.0,
                    'ingredient_line_ids': [
                        (0, 0, {
                            'product_id': ing.product_id.id,
                            'quantity': ing.quantity,
                            'uom_id': ing.uom_id.id,
                        })
                        for ing in line.ingredient_line_ids
                        if ing.product_id and ing.uom_id
                    ],
                }
                Recipe.create(recipe_vals)
                created += 1

        msg_parts = []
        if created:
            msg_parts.append(_('%d recipes created') % created)
        if updated:
            msg_parts.append(_('%d recipes updated') % updated)

        if msg_parts:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Recipes Saved'),
                    'message': ', '.join(msg_parts),
                    'type': 'success',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }

        raise UserError(_('No changes to save. Add ingredients to create recipes.'))

    def action_copy_from_variant(self):
        """Copy ingredients from one variant to others.

        Opens a sub-wizard to select source and target variants.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Copy Ingredients'),
            'res_model': 'recipe.variant.copy',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_editor_id': self.id,
                'default_product_tmpl_id': self.product_tmpl_id.id,
            },
        }


class RecipeVariantEditorLine(models.TransientModel):
    """A single variant line in the Recipe Variant Editor."""
    _name = 'recipe.variant.editor.line'
    _description = 'Variant Recipe Editor Line'
    _order = 'variant_name'

    wizard_id = fields.Many2one('recipe.variant.editor', required=True, ondelete='cascade')
    variant_id = fields.Many2one('product.product', string='Variant', readonly=True)
    variant_name = fields.Char(string='Variant', readonly=True)
    attribute_values = fields.Char(string='Attributes', readonly=True)

    recipe_id = fields.Many2one('restaurant.recipe', string='Recipe', readonly=True)
    has_recipe = fields.Boolean(string='Has Recipe', readonly=True)

    # Editable ingredients for this variant
    ingredient_line_ids = fields.One2many(
        'recipe.variant.editor.ingredient', 'line_id',
        string='Ingredients'
    )

    total_cost = fields.Float(string='Cost', compute='_compute_cost')
    ingredient_count = fields.Integer(string='Ingredients', compute='_compute_cost')

    @api.depends('ingredient_line_ids', 'ingredient_line_ids.cost')
    def _compute_cost(self):
        for line in self:
            line.ingredient_count = len(line.ingredient_line_ids)
            line.total_cost = sum(line.ingredient_line_ids.mapped('cost'))

    def action_open_recipe(self):
        """Open the linked recipe in a form view."""
        self.ensure_one()
        if not self.recipe_id:
            raise UserError(_('No recipe exists for this variant yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Recipe'),
            'res_model': 'restaurant.recipe',
            'view_mode': 'form',
            'res_id': self.recipe_id.id,
            'target': 'current',
        }


class RecipeVariantEditorIngredient(models.TransientModel):
    """Ingredient line within the editor."""
    _name = 'recipe.variant.editor.ingredient'
    _description = 'Variant Recipe Editor Ingredient'
    _order = 'sequence, id'

    line_id = fields.Many2one('recipe.variant.editor.line', required=True, ondelete='cascade')
    source_line_id = fields.Many2one('recipe.ingredient.line', string='Source Line')
    sequence = fields.Integer(default=10)

    product_id = fields.Many2one(
        'product.product', string='Ingredient', required=True,
        domain="[('is_ingredient', '=', True)]",
        context="{'default_is_ingredient': True}"
    )
    quantity = fields.Float(string='Qty', required=True, default=1.0)
    uom_id = fields.Many2one('uom.uom', string='Unit', required=True)

    unit_cost = fields.Float(related='product_id.standard_price', string='Unit Cost')
    cost = fields.Float(string='Cost', compute='_compute_cost', store=True)

    @api.depends('quantity', 'unit_cost')
    def _compute_cost(self):
        for line in self:
            line.cost = line.quantity * line.unit_cost

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id


class RecipeVariantCopy(models.TransientModel):
    """Sub-wizard to copy ingredients between variants."""
    _name = 'recipe.variant.copy'
    _description = 'Copy Recipe Between Variants'

    editor_id = fields.Many2one('recipe.variant.editor')
    product_tmpl_id = fields.Many2one('product.template')

    source_variant_id = fields.Many2one(
        'product.product',
        string='Copy From',
        required=True,
        domain="[('product_tmpl_id', '=', product_tmpl_id)]"
    )

    target_variant_ids = fields.Many2many(
        'product.product',
        'recipe_copy_target_rel',
        'wizard_id', 'product_id',
        string='Copy To',
        domain="[('product_tmpl_id', '=', product_tmpl_id), ('id', '!=', source_variant_id)]"
    )

    def action_copy(self):
        """Copy ingredients from source to target variants."""
        self.ensure_one()

        Recipe = self.env['restaurant.recipe']
        source_recipe = Recipe.search([
            ('product_id', '=', self.source_variant_id.id)
        ], limit=1)

        if not source_recipe:
            raise UserError(_('Source variant has no recipe. Create one first.'))

        created = 0
        for target in self.target_variant_ids:
            existing = Recipe.search([('product_id', '=', target.id)], limit=1)
            if existing:
                # Update existing: clear and copy
                existing.ingredient_line_ids.unlink()
                for line in source_recipe.ingredient_line_ids:
                    self.env['recipe.ingredient.line'].create({
                        'recipe_id': existing.id,
                        'product_id': line.product_id.id,
                        'quantity': line.quantity,
                        'uom_id': line.uom_id.id,
                    })
            else:
                # Create new recipe with copied ingredients
                Recipe.create({
                    'name': target.display_name,
                    'product_id': target.id,
                    'recipe_type': source_recipe.recipe_type,
                    'portion_size': source_recipe.portion_size,
                    'ingredient_line_ids': [
                        (0, 0, {
                            'product_id': line.product_id.id,
                            'quantity': line.quantity,
                            'uom_id': line.uom_id.id,
                        })
                        for line in source_recipe.ingredient_line_ids
                    ],
                })
                created += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Recipes Copied'),
                'message': _('Ingredients copied to %d variants.') % len(self.target_variant_ids),
                'type': 'success',
                'next': {'type': 'ir.actions.act_window_close'},
            }
        }
