# -*- coding: utf-8 -*-
from odoo import api, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _recipe_sync_adjustment_accounts(self):
        """Copy the stocktake and waste accounts from the module settings onto the
        virtual locations, so Odoo posts count differences and waste straight to them.

        Without accounts on these locations Odoo falls back to the category's Stock
        Incoming / Outgoing accounts, which are clearing accounts for purchases and POS.
        - Inventory adjustment: stock leaving the warehouse (shortage) goes to the loss
          account (Incoming), stock coming back (surplus) to the gain account (Outgoing).
        - Scrap: waste goes to the waste account both ways (a return reverses it).
        """
        ICP = self.env['ir.config_parameter'].sudo()
        Account = self.env['account.account'].sudo()

        def account(key):
            value = ICP.get_param(key)
            return Account.browse(int(value)).exists() if value else Account

        gain = account('pos_recipe_costing.stocktake_gain_account_id')
        loss = account('pos_recipe_costing.stocktake_loss_account_id')
        waste = account('pos_recipe_costing.waste_account_id')

        locations = self.sudo().with_context(active_test=False).search([('usage', '=', 'inventory')])
        adjustment = locations.filtered(lambda l: not l.scrap_location)
        scrap = locations.filtered('scrap_location')
        if gain:
            adjustment.write({'valuation_out_account_id': gain.id})
        if loss:
            adjustment.write({'valuation_in_account_id': loss.id})
        if waste:
            scrap.write({'valuation_in_account_id': waste.id, 'valuation_out_account_id': waste.id})
        return True
