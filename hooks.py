# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def pre_init_hook(env):
    """Clean up before module installation/upgrade"""
    _logger.info("pos_recipe_costing: Running pre_init_hook")
    _cleanup_orphaned_menus(env.cr)


def post_init_hook(env):
    """Setup after module installation/upgrade"""
    _logger.info("pos_recipe_costing: Running post_init_hook")
    _cleanup_orphaned_menus(env.cr)


def _cleanup_orphaned_menus(cr):
    """Remove menu items that reference non-existent actions"""
    try:
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
            _logger.info("Cleaned up %d orphaned menu action references", cr.rowcount)

        # Also clean up server actions
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

    except Exception as e:
        _logger.warning("Failed to cleanup orphaned menus: %s", str(e))
