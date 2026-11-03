# -*- coding: utf-8 -*-
"""Recipe & Costing works with several companies (18.0.4.9.0).

- The module's accounts move from shared settings (ir.config_parameter) to each company.
  An account goes to every company that can use it (account.company_ids).
- Recipe kits (BOMs) of shared products lose their company, so every company's POS consumes
  the ingredients. Before, a kit only worked in the company of the user who saved the recipe.
- Stocktakes get the warehouse they counted (the company's first one, as before).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

PARAMS = {
    'pos_recipe_costing.stocktake_gain_account_id': 'recipe_stocktake_gain_account_id',
    'pos_recipe_costing.stocktake_loss_account_id': 'recipe_stocktake_loss_account_id',
    'pos_recipe_costing.waste_account_id': 'recipe_waste_account_id',
    'pos_recipe_costing.ingredient_expense_account_id': 'recipe_ingredient_expense_account_id',
    'pos_recipe_costing.ingredient_stock_valuation_id': 'recipe_ingredient_valuation_account_id',
    'pos_recipe_costing.product_income_account_id': 'recipe_product_income_account_id',
}


def migrate(cr, version):
    for key, column in PARAMS.items():
        cr.execute("SELECT value FROM ir_config_parameter WHERE key = %s", (key,))
        row = cr.fetchone()
        if not row or not (row[0] or '').isdigit():
            continue
        account_id = int(row[0])
        cr.execute(f"""UPDATE res_company c SET {column} = %s
                        WHERE {column} IS NULL
                          AND EXISTS (SELECT 1 FROM account_account_res_company_rel r
                                       WHERE r.account_account_id = %s AND r.res_company_id = c.id)""",
                   (account_id, account_id))
        _logger.info("Recipe Costing: %s -> %s companies", key, cr.rowcount)
        cr.execute("DELETE FROM ir_config_parameter WHERE key = %s", (key,))

    cr.execute("""UPDATE mrp_bom b SET company_id = NULL
                    FROM product_template t
                   WHERE b.product_tmpl_id = t.id AND t.company_id IS NULL
                     AND b.code LIKE 'RECIPE-%%' AND b.company_id IS NOT NULL""")
    _logger.info("Recipe Costing: %s recipe kits shared with every company", cr.rowcount)
    cr.execute("""UPDATE mrp_bom_line l SET company_id = NULL
                    FROM mrp_bom b WHERE l.bom_id = b.id AND b.company_id IS NULL AND l.company_id IS NOT NULL""")

    cr.execute("""UPDATE ingredient_stocktake s
                     SET warehouse_id = (SELECT w.id FROM stock_warehouse w
                                          WHERE w.company_id = s.company_id ORDER BY w.sequence, w.id LIMIT 1)
                   WHERE s.warehouse_id IS NULL""")

    # 18.0.4.6.1 / 18.0.4.7.1 marked old lines counted in SQL, so the stored counts
    # (counted / pending / variances) of those stocktakes were never recomputed
    env = api.Environment(cr, SUPERUSER_ID, {})
    stocktakes = env['ingredient.stocktake'].with_context(active_test=False).search([])
    env.add_to_compute(env['ingredient.stocktake.line']._fields['count_status'], stocktakes.line_ids)
    for name in ('line_count', 'counted_count', 'pending_count', 'variance_count'):
        env.add_to_compute(stocktakes._fields[name], stocktakes)
    stocktakes.flush_recordset()
    _logger.info("Recipe Costing: recomputed the counts of %s stocktakes", len(stocktakes))
