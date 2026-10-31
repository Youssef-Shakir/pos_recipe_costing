# -*- coding: utf-8 -*-
"""Stocktakes validated before 18.0.4.6.0 applied every line (an empty count as 0).

They never saved the 'counted' flag, so the stocktake report would list all their lines as
not counted. Mark their lines counted, matching what was posted."""


def migrate(cr, version):
    cr.execute("""
        UPDATE ingredient_stocktake_line l
           SET is_counted = TRUE, count_status = 'counted'
          FROM ingredient_stocktake s
         WHERE s.id = l.stocktake_id
           AND s.state = 'done'
           AND s.account_move_id IS NOT NULL
           AND NOT COALESCE(l.is_counted, FALSE)
    """)
