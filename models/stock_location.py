# -*- coding: utf-8 -*-
from odoo import api, models


class StockLocation(models.Model):
    _inherit = 'stock.location'

    @api.model
    def _recipe_sync_adjustment_accounts(self, companies=None):
        """Copy each company's stocktake and waste accounts (Settings) onto that company's
        virtual locations, so Odoo posts count differences and waste straight to them.

        Without accounts on these locations Odoo falls back to the category's Stock
        Incoming / Outgoing accounts, which are clearing accounts for purchases and POS.
        - Inventory adjustment: stock leaving the warehouse (shortage) goes to the loss
          account (Incoming), stock coming back (surplus) to the gain account (Outgoing).
        - Scrap: waste goes to the waste account both ways (a return reverses it).
        """
        companies = companies or self.env['res.company'].sudo().search([])
        Location = self.sudo().with_context(active_test=False)
        for company in companies.sudo():
            locations = Location.search([('usage', '=', 'inventory'), ('company_id', '=', company.id)])
            adjustment = locations.filtered(lambda l: not l.scrap_location)
            scrap = locations.filtered('scrap_location')
            gain = company.recipe_stocktake_gain_account_id
            loss = company.recipe_stocktake_loss_account_id
            waste = company.recipe_waste_account_id
            if gain:
                adjustment.write({'valuation_out_account_id': gain.id})
            if loss:
                adjustment.write({'valuation_in_account_id': loss.id})
            if waste:
                scrap.write({'valuation_in_account_id': waste.id, 'valuation_out_account_id': waste.id})
        return True
