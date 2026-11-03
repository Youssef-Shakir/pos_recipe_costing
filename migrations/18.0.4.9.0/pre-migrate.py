# -*- coding: utf-8 -*-
"""Values that become per company (company_dependent, stored as jsonb {company_id: value}):
the reorder points and the recipe's last tracked cost. Keep them for the main company instead
of letting Odoo fail on (or drop) the old columns."""

COLUMNS = [
    ('product_product', name) for name in (
        'reorder_mode', 'reorder_cover_days', 'reorder_fill_days', 'reorder_avg_daily', 'reorder_auto_point',
        'reorder_auto_max', 'reorder_point', 'reorder_max_qty', 'reorder_computed_on')
] + [('restaurant_recipe', '_previous_cost_per_portion')]


def migrate(cr, version):
    cr.execute("SELECT id FROM res_company ORDER BY sequence, id LIMIT 1")
    row = cr.fetchone()
    if not row:
        return
    company_key = str(row[0])
    for table, name in COLUMNS:
        cr.execute("""SELECT data_type FROM information_schema.columns
                       WHERE table_name = %s AND column_name = %s""", (table, name))
        column = cr.fetchone()
        if not column or column[0] == 'jsonb':
            continue
        value = f"to_char({name}, 'YYYY-MM-DD HH24:MI:SS')" if column[0].startswith('timestamp') else name
        cr.execute(f"""ALTER TABLE {table} ALTER COLUMN "{name}" TYPE jsonb
                       USING CASE WHEN "{name}" IS NULL THEN NULL
                                  ELSE jsonb_build_object(%s, "{value}") END""" if value == name else
                   f"""ALTER TABLE {table} ALTER COLUMN "{name}" TYPE jsonb
                       USING CASE WHEN "{name}" IS NULL THEN NULL
                                  ELSE jsonb_build_object(%s, {value}) END""", (company_key,))
