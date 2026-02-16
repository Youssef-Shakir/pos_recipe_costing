# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # Ingredient defaults
    recipe_ingredient_category_id = fields.Many2one(
        'product.category',
        string='Ingredient Category',
        config_parameter='pos_recipe_costing.ingredient_category_id',
        help="Default product category for ingredients"
    )
    recipe_ingredient_account_expense_id = fields.Many2one(
        'account.account',
        string='Expense Account (COGS)',
        config_parameter='pos_recipe_costing.ingredient_expense_account_id',
        domain="[('account_type', 'in', ['expense', 'expense_direct_cost'])]",
        help="Default expense account (COGS) for ingredients"
    )
    recipe_ingredient_account_stock_valuation_id = fields.Many2one(
        'account.account',
        string='Stock Valuation Account',
        config_parameter='pos_recipe_costing.ingredient_stock_valuation_id',
        domain="[('account_type', '=', 'asset_current')]",
        help="Default stock valuation account for ingredients"
    )

    # Final product defaults
    recipe_product_category_id = fields.Many2one(
        'product.category',
        string='Menu Item Category',
        config_parameter='pos_recipe_costing.product_category_id',
        help="Default product category for menu items (final products)"
    )
    recipe_product_account_income_id = fields.Many2one(
        'account.account',
        string='Income Account',
        config_parameter='pos_recipe_costing.product_income_account_id',
        domain="[('account_type', '=', 'income')]",
        help="Default income account for menu items"
    )
    recipe_pos_category_id = fields.Many2one(
        'pos.category',
        string='Default POS Category',
        config_parameter='pos_recipe_costing.pos_category_id',
        help="Default POS category for menu items"
    )

    # Thresholds
    recipe_high_food_cost_threshold = fields.Float(
        string='High Food Cost Threshold',
        config_parameter='pos_recipe_costing.high_food_cost_threshold',
        default=35.0,
        help="Recipes above this food cost % will be flagged"
    )
