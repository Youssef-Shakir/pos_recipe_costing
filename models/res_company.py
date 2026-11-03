# -*- coding: utf-8 -*-
from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    # Accounts belong to one company's chart, so the module's accounts are set per company
    recipe_stocktake_gain_account_id = fields.Many2one(
        'account.account', string='Inventory Gain Account',
        help="Surpluses found by a stocktake (counted > system)")
    recipe_stocktake_loss_account_id = fields.Many2one(
        'account.account', string='Inventory Loss Account',
        help="Shortages found by a stocktake (counted < system)")
    recipe_waste_account_id = fields.Many2one(
        'account.account', string='Waste Expense Account',
        help="Recorded waste (expired, spoiled, damaged)")
    recipe_ingredient_expense_account_id = fields.Many2one(
        'account.account', string='Ingredient Expense Account (COGS)')
    recipe_ingredient_valuation_account_id = fields.Many2one(
        'account.account', string='Ingredient Stock Valuation Account')
    recipe_product_income_account_id = fields.Many2one(
        'account.account', string='Menu Item Income Account')
