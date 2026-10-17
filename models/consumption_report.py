# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from datetime import datetime, timedelta


class ConsumptionReportWizard(models.TransientModel):
    _name = 'consumption.report.wizard'
    _description = 'Consumption Report Wizard'

    date_from = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1)
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.today
    )
    product_ids = fields.Many2many(
        'product.product',
        'consumption_wizard_product_rel',
        'wizard_id',
        'product_id',
        string='Ingredients',
        domain="[('is_ingredient', '=', True)]",
        help="Filter by specific ingredients. Leave empty for all."
    )
    category_ids = fields.Many2many(
        'product.category',
        'consumption_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Ingredient Categories',
        help="Filter by ingredient categories. Leave empty for all."
    )
    recipe_ids = fields.Many2many(
        'restaurant.recipe',
        'consumption_wizard_recipe_rel',
        'wizard_id',
        'recipe_id',
        string='Recipes',
        help="Filter by specific recipes. Leave empty for all."
    )

    # Summary fields for display
    total_consumption_value = fields.Float(
        string='Total Consumption Value',
        compute='_compute_summary',
        store=False
    )
    total_ingredients_consumed = fields.Integer(
        string='Total Ingredients Consumed',
        compute='_compute_summary',
        store=False
    )
    total_orders = fields.Integer(
        string='Total POS Orders',
        compute='_compute_summary',
        store=False
    )

    @api.depends('date_from', 'date_to', 'product_ids', 'category_ids', 'recipe_ids')
    def _compute_summary(self):
        for wizard in self:
            data = wizard._get_consumption_data()
            wizard.total_consumption_value = sum(d['total_cost'] for d in data)
            wizard.total_ingredients_consumed = len(data)
            # Count unique POS orders
            order_ids = set()
            for d in data:
                order_ids.update(d.get('order_ids', []))
            wizard.total_orders = len(order_ids)

    def _get_consumption_data(self):
        """
        Compute consumption data from stock moves linked to POS orders.
        Returns list of dicts with ingredient consumption details.
        """
        self.ensure_one()

        # Build domain for stock moves
        # Stock moves from POS orders are typically outgoing moves from
        # stock location to customer location
        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', datetime.combine(self.date_to, datetime.max.time())),
            ('state', '=', 'done'),
            ('product_id.is_ingredient', '=', True),
        ]

        # Filter by specific ingredients
        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))

        # Filter by categories
        if self.category_ids:
            domain.append(('product_id.categ_id', 'child_of', self.category_ids.ids))

        # Get stock moves - focus on moves from kit explosions (phantom BOM)
        # These are typically inventory adjustment or internal moves from BOM consumption
        StockMove = self.env['stock.move']
        moves = StockMove.search(domain)

        # Filter moves that are from POS-related picking or BOM consumption
        # Phantom BOMs create moves when POS order is validated
        pos_related_moves = moves.filtered(lambda m: (
            m.picking_id.pos_session_id or
            m.picking_id.pos_order_id or
            (m.origin and ('POS' in (m.origin or '') or 'S0' in (m.origin or ''))) or
            m.bom_line_id  # Direct BOM consumption
        ))

        # If no POS-specific moves, fall back to all outgoing ingredient moves
        if not pos_related_moves:
            # Get outgoing moves (stock consumption)
            pos_related_moves = moves.filtered(lambda m: m.location_id.usage == 'internal')

        # Group by product
        product_data = {}
        for move in pos_related_moves:
            product = move.product_id
            if product.id not in product_data:
                product_data[product.id] = {
                    'product_id': product.id,
                    'product_name': product.display_name,
                    'categ_id': product.categ_id.id,
                    'categ_name': product.categ_id.complete_name,
                    'uom_id': product.uom_id.id,
                    'uom_name': product.uom_id.name,
                    'qty_consumed': 0.0,
                    'total_cost': 0.0,
                    'move_ids': [],
                    'order_ids': [],
                    'recipe_names': set(),
                }

            # Convert quantity to product UoM if needed
            qty = move.product_uom._compute_quantity(
                move.product_uom_qty,
                product.uom_id
            )
            product_data[product.id]['qty_consumed'] += qty
            product_data[product.id]['total_cost'] += abs(move.product_uom_qty * product.standard_price)
            product_data[product.id]['move_ids'].append(move.id)

            # Track source orders
            if move.picking_id.pos_order_id:
                product_data[product.id]['order_ids'].append(move.picking_id.pos_order_id.id)

            # Track recipes this ingredient is used in
            if move.bom_line_id and move.bom_line_id.bom_id:
                recipe = self.env['restaurant.recipe'].search([
                    ('bom_id', '=', move.bom_line_id.bom_id.id)
                ], limit=1)
                if recipe:
                    product_data[product.id]['recipe_names'].add(recipe.name)

        # Convert sets to lists for JSON serialization
        result = []
        for data in product_data.values():
            data['recipe_names'] = list(data['recipe_names'])
            data['recipes_used_in'] = ', '.join(data['recipe_names']) if data['recipe_names'] else ''
            result.append(data)

        # Filter by recipes if specified
        if self.recipe_ids:
            recipe_names = set(self.recipe_ids.mapped('name'))
            result = [
                d for d in result
                if any(rn in recipe_names for rn in d['recipe_names'])
            ]

        # Sort by total cost descending
        result.sort(key=lambda x: x['total_cost'], reverse=True)

        return result

    def action_generate_lines(self):
        """Generate consumption lines and display them"""
        self.ensure_one()

        # Clear existing lines for this date range
        ConsumptionLine = self.env['ingredient.consumption.line']
        existing = ConsumptionLine.search([
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ])
        existing.unlink()

        data = self._get_consumption_data()

        # Create consumption lines
        lines = ConsumptionLine
        for item in data:
            # Find recipes this ingredient is used in
            recipes = self.env['restaurant.recipe'].search([
                ('ingredient_line_ids.product_id', '=', item['product_id'])
            ])

            line_vals = {
                'date': self.date_to,
                'product_id': item['product_id'],
                'quantity': item['qty_consumed'],
                'uom_id': item['uom_id'],
                'cost': item['total_cost'],
                'date_from': self.date_from,
                'date_to': self.date_to,
                'recipe_ids': [(6, 0, recipes.ids)] if recipes else False,
            }
            lines |= ConsumptionLine.create(line_vals)

        # Return action to view consumption lines
        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredient Consumption: %s to %s') % (self.date_from, self.date_to),
            'res_model': 'ingredient.consumption.line',
            'view_mode': 'list,pivot,graph',
            'domain': [('id', 'in', lines.ids)],
            'context': {
                'search_default_group_by_category': 1,
            },
            'target': 'current',
        }

    def action_view_consumption(self):
        """View consumption lines without regenerating"""
        self.ensure_one()

        domain = [
            ('date', '>=', self.date_from),
            ('date', '<=', self.date_to),
        ]

        if self.product_ids:
            domain.append(('product_id', 'in', self.product_ids.ids))

        if self.category_ids:
            domain.append(('product_id.categ_id', 'child_of', self.category_ids.ids))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Ingredient Consumption: %s to %s') % (self.date_from, self.date_to),
            'res_model': 'ingredient.consumption.line',
            'view_mode': 'list,pivot,graph',
            'domain': domain,
            'context': {
                'search_default_group_by_category': 1,
            },
            'target': 'current',
        }

    def action_print_report(self):
        """Print PDF consumption report"""
        self.ensure_one()
        return self.env.ref(
            'pos_recipe_costing.action_report_consumption'
        ).report_action(self)

    def get_report_data(self):
        """Get data formatted for the PDF report"""
        self.ensure_one()
        data = self._get_consumption_data()

        # Group by category
        categories = {}
        for item in data:
            categ_name = item['categ_name'] or _('Uncategorized')
            if categ_name not in categories:
                categories[categ_name] = {
                    'name': categ_name,
                    'items': [],
                    'total_cost': 0.0,
                }
            categories[categ_name]['items'].append(item)
            categories[categ_name]['total_cost'] += item['total_cost']

        # Sort categories by total cost
        sorted_categories = sorted(
            categories.values(),
            key=lambda x: x['total_cost'],
            reverse=True
        )

        # Top 10 most consumed by cost
        top_10 = data[:10] if len(data) >= 10 else data

        # Top 10 by quantity (normalize to common unit is complex, so by cost)
        top_10_qty = sorted(data, key=lambda x: x['qty_consumed'], reverse=True)[:10]

        return {
            'date_from': self.date_from,
            'date_to': self.date_to,
            'total_value': sum(d['total_cost'] for d in data),
            'total_ingredients': len(data),
            'categories': sorted_categories,
            'top_10_by_cost': top_10,
            'top_10_by_qty': top_10_qty,
            'currency': self.env.company.currency_id,
        }
