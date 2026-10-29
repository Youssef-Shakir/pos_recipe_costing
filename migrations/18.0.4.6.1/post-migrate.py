# -*- coding: utf-8 -*-
"""Open stocktakes: lines with a count entered are counted.

Older versions saved the count without the 'counted' flag. Validation now applies only
counted lines, so mark them; lines left empty stay pending and no longer post as zero."""


def migrate(cr, version):
    cr.execute("""
        UPDATE ingredient_stocktake_line l
           SET is_counted = TRUE, count_status = 'counted'
          FROM ingredient_stocktake s
         WHERE s.id = l.stocktake_id
           AND s.state IN ('draft', 'in_progress')
           AND l.counted_qty IS NOT NULL
           AND NOT COALESCE(l.is_counted, FALSE)
           AND COALESCE(l.count_status, 'pending') <> 'skipped'
    """)
