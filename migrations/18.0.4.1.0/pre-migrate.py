# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Pre-migration: Clean up orphaned menu references before module upgrade"""
    if not version:
        return

    _logger.info("pos_recipe_costing: Running pre-migration cleanup from version %s", version)

    # Clean up orphaned act_window action references
    cr.execute("""
        UPDATE ir_ui_menu
        SET action = NULL
        WHERE action IS NOT NULL
        AND action LIKE 'ir.actions.act_window,%%'
        AND CAST(SPLIT_PART(action, ',', 2) AS INTEGER) NOT IN (
            SELECT id FROM ir_act_window
        )
    """)
    if cr.rowcount > 0:
        _logger.info("Cleaned up %d orphaned act_window menu references", cr.rowcount)

    # Clean up orphaned server action references
    cr.execute("""
        UPDATE ir_ui_menu
        SET action = NULL
        WHERE action IS NOT NULL
        AND action LIKE 'ir.actions.server,%%'
        AND CAST(SPLIT_PART(action, ',', 2) AS INTEGER) NOT IN (
            SELECT id FROM ir_act_server
        )
    """)
    if cr.rowcount > 0:
        _logger.info("Cleaned up %d orphaned server action references", cr.rowcount)

    # Also delete any orphaned ir_model_data entries for this module
    cr.execute("""
        DELETE FROM ir_model_data
        WHERE module = 'pos_recipe_costing'
        AND model = 'ir.actions.act_window'
        AND res_id NOT IN (SELECT id FROM ir_act_window)
    """)
    if cr.rowcount > 0:
        _logger.info("Cleaned up %d orphaned ir_model_data entries", cr.rowcount)
