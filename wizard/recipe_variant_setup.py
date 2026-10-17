# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RecipeVariantSetup(models.TransientModel):
    _name = 'recipe.variant.setup'
    _description = 'Bulk Recipe Setup for Product Variants'

    # -------------------------------------------------------------------------
    # BASIC FIELDS
    # -------------------------------------------------------------------------
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

    # -------------------------------------------------------------------------
    # SETUP MODE
    # -------------------------------------------------------------------------
    setup_mode = fields.Selection([
        ('standard', 'Standard Setup'),
        ('quick', 'Quick Setup'),
    ], string='Setup Mode', default='standard', required=True,
        help='Standard: Manual configuration of all ingredients.\n'
             'Quick: Auto-creates one ingredient line per attribute value for faster setup.')

    # -------------------------------------------------------------------------
    # INGREDIENT LINES
    # -------------------------------------------------------------------------
    # Common ingredients - copied to every variant recipe
    ingredient_line_ids = fields.One2many(
        'recipe.variant.setup.ingredient', 'wizard_id',
        string='Base Ingredients'
    )

    # Per-variant extras - only added to the specific variant's recipe
    extra_line_ids = fields.One2many(
        'recipe.variant.setup.extra', 'wizard_id',
        string='Variant-Specific Extras'
    )

    # -------------------------------------------------------------------------
    # VARIANT SELECTION
    # -------------------------------------------------------------------------
    # Store available attribute values for domain filtering (fixes parent context issues)
    available_attribute_value_ids = fields.Many2many(
        'product.template.attribute.value',
        'recipe_setup_avail_attr_val_rel',
        'wizard_id', 'attr_val_id',
        string='Available Attribute Values',
        compute='_compute_available_attribute_values',
        store=True,
    )

    # Many2many is reliable across dialog saves
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

    # -------------------------------------------------------------------------
    # PREVIEW FIELDS
    # -------------------------------------------------------------------------
    preview_line_ids = fields.One2many(
        'recipe.variant.setup.preview', 'wizard_id',
        string='Preview',
        compute='_compute_preview_lines',
    )

    # Summary fields
    summary_total_variants = fields.Integer(
        string='Variants to Create',
        compute='_compute_summary'
    )
    summary_total_base_ingredients = fields.Integer(
        string='Base Ingredients',
        compute='_compute_summary'
    )
    summary_total_extra_rules = fields.Integer(
        string='Extra Ingredient Rules',
        compute='_compute_summary'
    )
    summary_estimated_cost = fields.Float(
        string='Estimated Base Cost',
        compute='_compute_summary'
    )
    summary_html = fields.Html(
        string='Summary',
        compute='_compute_summary_html',
        sanitize=False,
    )

    # -------------------------------------------------------------------------
    # STATE MANAGEMENT
    # -------------------------------------------------------------------------
    state = fields.Selection([
        ('setup', 'Setup'),
        ('preview', 'Preview & Confirm'),
    ], default='setup', string='State')

    # -------------------------------------------------------------------------
    # COMPUTED METHODS
    # -------------------------------------------------------------------------
    @api.depends('selected_variant_ids')
    def _compute_selected_count(self):
        for wiz in self:
            wiz.selected_count = len(wiz.selected_variant_ids)

    @api.depends('product_tmpl_id')
    def _compute_available_attribute_values(self):
        """Compute available attribute values for the selected product template."""
        for wiz in self:
            if wiz.product_tmpl_id:
                wiz.available_attribute_value_ids = wiz.product_tmpl_id.attribute_line_ids.product_template_value_ids
            else:
                wiz.available_attribute_value_ids = False

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

    @api.depends('selected_variant_ids', 'ingredient_line_ids', 'extra_line_ids')
    def _compute_summary(self):
        for wiz in self:
            wiz.summary_total_variants = len(wiz.selected_variant_ids)
            wiz.summary_total_base_ingredients = len(wiz.ingredient_line_ids.filtered(
                lambda l: l.product_id and l.uom_id
            ))
            wiz.summary_total_extra_rules = len(wiz.extra_line_ids.filtered(
                lambda l: l.attribute_value_id and l.product_id and l.uom_id
            ))
            wiz.summary_estimated_cost = sum(
                line.cost for line in wiz.ingredient_line_ids if line.cost
            )

    @api.depends('selected_variant_ids', 'ingredient_line_ids', 'extra_line_ids',
                 'ingredient_line_ids.product_id', 'ingredient_line_ids.quantity',
                 'extra_line_ids.attribute_value_id', 'extra_line_ids.product_id',
                 'extra_line_ids.quantity')
    def _compute_preview_lines(self):
        """Generate preview lines showing what each variant will receive."""
        PreviewLine = self.env['recipe.variant.setup.preview']
        for wiz in self:
            preview_lines = []

            # Build extras index by attribute value ID
            extras_by_attr_val = {}
            for extra in wiz.extra_line_ids:
                if extra.attribute_value_id and extra.product_id and extra.uom_id:
                    extras_by_attr_val.setdefault(extra.attribute_value_id.id, []).append(extra)

            for variant in wiz.selected_variant_ids:
                # Calculate ingredients for this variant
                base_ingredients = []
                for ing in wiz.ingredient_line_ids:
                    if ing.product_id and ing.uom_id:
                        base_ingredients.append(f"{ing.quantity} {ing.uom_id.name} {ing.product_id.name}")

                extra_ingredients = []
                variant_attr_val_ids = set(variant.product_template_attribute_value_ids.ids)
                for attr_val_id in variant_attr_val_ids:
                    if attr_val_id in extras_by_attr_val:
                        for extra in extras_by_attr_val[attr_val_id]:
                            extra_ingredients.append(f"{extra.quantity} {extra.uom_id.name} {extra.product_id.name}")

                preview_lines.append({
                    'wizard_id': wiz.id,
                    'variant_id': variant.id,
                    'variant_name': variant.display_name,
                    'base_ingredients_display': ', '.join(base_ingredients) if base_ingredients else '-',
                    'extra_ingredients_display': ', '.join(extra_ingredients) if extra_ingredients else '-',
                    'total_ingredient_count': len(base_ingredients) + len(extra_ingredients),
                })

            # Create preview records (transient)
            wiz.preview_line_ids = [(5, 0, 0)] + [(0, 0, vals) for vals in preview_lines]

    @api.depends('selected_variant_ids', 'ingredient_line_ids', 'extra_line_ids', 'summary_estimated_cost')
    def _compute_summary_html(self):
        """Generate HTML summary of what will be created."""
        for wiz in self:
            if not wiz.selected_variant_ids:
                wiz.summary_html = '<div class="text-muted">No variants selected</div>'
                continue

            # Build extras index
            extras_by_attr_val = {}
            for extra in wiz.extra_line_ids:
                if extra.attribute_value_id and extra.product_id:
                    extras_by_attr_val.setdefault(extra.attribute_value_id.id, []).append(extra)

            html_parts = []
            html_parts.append('<div class="o_recipe_summary">')
            html_parts.append(f'<h4>Creating {len(wiz.selected_variant_ids)} Recipe(s)</h4>')

            # Base ingredients summary
            base_count = len(wiz.ingredient_line_ids.filtered(lambda l: l.product_id))
            html_parts.append(f'<p><strong>Base ingredients:</strong> {base_count} item(s) '
                            f'(Est. cost: {wiz.summary_estimated_cost:.2f})</p>')

            # Extra rules summary
            extra_count = len(wiz.extra_line_ids.filtered(lambda l: l.attribute_value_id and l.product_id))
            html_parts.append(f'<p><strong>Variant-specific rules:</strong> {extra_count} rule(s)</p>')

            # Detailed variant breakdown
            html_parts.append('<hr/><h5>Variant Details:</h5>')
            html_parts.append('<table class="table table-sm table-bordered">')
            html_parts.append('<thead><tr><th>Variant</th><th>Extra Ingredients</th><th>Total Items</th></tr></thead>')
            html_parts.append('<tbody>')

            for variant in wiz.selected_variant_ids[:10]:  # Limit to first 10 for display
                variant_attr_val_ids = set(variant.product_template_attribute_value_ids.ids)
                extra_names = []
                for attr_val_id in variant_attr_val_ids:
                    if attr_val_id in extras_by_attr_val:
                        for extra in extras_by_attr_val[attr_val_id]:
                            extra_names.append(extra.product_id.name)

                total = base_count + len(extra_names)
                extras_str = ', '.join(extra_names) if extra_names else '<em>None</em>'
                html_parts.append(f'<tr><td>{variant.display_name}</td><td>{extras_str}</td><td>{total}</td></tr>')

            if len(wiz.selected_variant_ids) > 10:
                html_parts.append(f'<tr><td colspan="3"><em>... and {len(wiz.selected_variant_ids) - 10} more</em></td></tr>')

            html_parts.append('</tbody></table>')
            html_parts.append('</div>')

            wiz.summary_html = ''.join(html_parts)

    # -------------------------------------------------------------------------
    # DEFAULT & ONCHANGE
    # -------------------------------------------------------------------------
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
        self.state = 'setup'
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

    @api.onchange('setup_mode')
    def _onchange_setup_mode(self):
        """When switching to quick setup mode, auto-populate extras."""
        if self.setup_mode == 'quick' and self.product_tmpl_id:
            self._do_quick_setup()

    # -------------------------------------------------------------------------
    # ACTIONS
    # -------------------------------------------------------------------------
    def _do_quick_setup(self):
        """Internal method to populate extras for quick setup mode."""
        if not self.product_tmpl_id:
            return

        # Get all attribute values for this product template
        attr_values = self.product_tmpl_id.attribute_line_ids.product_template_value_ids

        # Get already added attribute value IDs to avoid duplicates
        existing_attr_val_ids = set(self.extra_line_ids.mapped('attribute_value_id').ids)

        new_lines = []
        for attr_val in attr_values:
            if attr_val.id in existing_attr_val_ids:
                continue

            # Get default ingredient from product.attribute.value if configured
            base_val = attr_val.product_attribute_value_id
            default_ingredient = base_val.default_ingredient_id if hasattr(base_val, 'default_ingredient_id') and base_val else False

            vals = {
                'attribute_value_id': attr_val.id,
                'quantity': 1.0,
            }
            if default_ingredient:
                vals['product_id'] = default_ingredient.id
                vals['uom_id'] = default_ingredient.uom_id.id

            new_lines.append((0, 0, vals))

        if new_lines:
            self.extra_line_ids = new_lines

    def action_auto_populate_extras(self):
        """Auto-populate extra lines for all attribute values of the product."""
        self.ensure_one()
        if not self.product_tmpl_id:
            raise UserError(_('Please select a product first.'))

        # Get all attribute values for this product template
        attr_values = self.product_tmpl_id.attribute_line_ids.product_template_value_ids

        # Get already added attribute value IDs to avoid duplicates
        existing_attr_val_ids = set(self.extra_line_ids.mapped('attribute_value_id').ids)

        new_lines = []
        for attr_val in attr_values:
            if attr_val.id in existing_attr_val_ids:
                continue

            # Get default ingredient from product.attribute.value if configured
            base_val = attr_val.product_attribute_value_id
            default_ingredient = base_val.default_ingredient_id if hasattr(base_val, 'default_ingredient_id') and base_val else False

            vals = {
                'attribute_value_id': attr_val.id,
                'quantity': 1.0,
            }
            if default_ingredient:
                vals['product_id'] = default_ingredient.id
                vals['uom_id'] = default_ingredient.uom_id.id

            new_lines.append((0, 0, vals))

        if new_lines:
            self.extra_line_ids = new_lines
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('No New Attribute Values'),
                    'message': _('All attribute values already have extra lines defined.'),
                    'type': 'warning',
                    'sticky': False,
                }
            }
        return True

    def action_go_to_preview(self):
        """Move to preview state to show summary before creation."""
        self.ensure_one()
        if not self.selected_variant_ids:
            raise UserError(_('Please select at least one variant to create a recipe for.'))

        self.state = 'preview'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_back_to_setup(self):
        """Return to setup state for modifications."""
        self.ensure_one()
        self.state = 'setup'
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

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

        # Show success notification
        message = _('%d recipe(s) created successfully!') % len(created_ids)
        if skipped:
            message += _('\n%d variant(s) skipped (already have recipes).') % len(skipped)

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

    def action_select_all_variants(self):
        """Select all variants without recipes."""
        self.ensure_one()
        if not self.product_tmpl_id:
            return
        existing_ids = self.existing_recipe_variant_ids.ids
        self.selected_variant_ids = self.product_tmpl_id.product_variant_ids.filtered(
            lambda v: v.id not in existing_ids
        )

    def action_deselect_all_variants(self):
        """Deselect all variants."""
        self.ensure_one()
        self.selected_variant_ids = [(5,)]


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
    _order = 'attribute_id, sequence, id'

    wizard_id = fields.Many2one('recipe.variant.setup', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)

    # Target an attribute VALUE (e.g. "Oat Milk"), not a full variant combination.
    attribute_value_id = fields.Many2one(
        'product.template.attribute.value',
        string='When Attribute Is',
        required=True,
        domain="[('id', 'in', parent.available_attribute_value_ids)]",
        help='Pick one attribute value (e.g. "Oat Milk"). '
             'The ingredient below will be added to every variant that includes it.'
    )
    # Shown readonly so the user understands which axis this rule belongs to
    attribute_id = fields.Many2one(
        'product.attribute',
        related='attribute_value_id.attribute_id',
        string='Attribute',
        readonly=True,
        store=True,
    )

    product_id = fields.Many2one(
        'product.product', string='Add Ingredient', required=True,
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

    @api.onchange('attribute_value_id')
    def _onchange_attribute_value_id(self):
        if not self.attribute_value_id:
            return
        # product.template.attribute.value -> product.attribute.value -> default_ingredient_id
        base_val = self.attribute_value_id.product_attribute_value_id
        if hasattr(base_val, 'default_ingredient_id') and base_val.default_ingredient_id:
            self.product_id = base_val.default_ingredient_id
            self.uom_id = base_val.default_ingredient_id.uom_id

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id


class RecipeVariantSetupPreview(models.TransientModel):
    _name = 'recipe.variant.setup.preview'
    _description = 'Preview Line for Recipe Variant Setup'
    _order = 'variant_name'

    wizard_id = fields.Many2one('recipe.variant.setup', required=True, ondelete='cascade')
    variant_id = fields.Many2one('product.product', string='Variant', readonly=True)
    variant_name = fields.Char(string='Variant Name', readonly=True)
    base_ingredients_display = fields.Char(string='Base Ingredients', readonly=True)
    extra_ingredients_display = fields.Char(string='Extra Ingredients', readonly=True)
    total_ingredient_count = fields.Integer(string='Total Items', readonly=True)
