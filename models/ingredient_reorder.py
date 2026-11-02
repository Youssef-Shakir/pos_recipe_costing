# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.tools import float_round

# Consumption = stock that left the shop (POS sales, waste/scrap, stocktake shortages)
# minus what came back (POS returns, stocktake surpluses). Receipts and manufacturing output are supply, not use.
CONSUMPTION_SQL = """
    SELECT m.product_id,
           SUM(CASE WHEN ls.usage = 'internal' AND ld.usage IN ('customer', 'inventory') THEN m.product_qty
                    WHEN ld.usage = 'internal' AND ls.usage IN ('customer', 'inventory') THEN -m.product_qty
                    ELSE 0 END),
           MIN(m.date)
      FROM stock_move m
      JOIN stock_location ls ON ls.id = m.location_id
      JOIN stock_location ld ON ld.id = m.location_dest_id
     WHERE m.state = 'done' AND m.product_id IN %s AND m.date >= %s
     GROUP BY m.product_id
"""


class ProductProduct(models.Model):
    _inherit = 'product.product'

    reorder_mode = fields.Selection([
        ('auto', 'Auto'),
        ('manual', 'Manual'),
    ], string='Reorder Mode', default='auto', copy=False,
        help="Auto: the reorder point and fill-up level are recalculated every day from consumption.\n"
             "Manual: set by hand and kept; the suggested values are still shown.")
    reorder_cover_days = fields.Float(
        string='Reorder at (days)',
        help="Order when stock covers fewer days than this. 0 = the default in Recipe Settings.")
    reorder_fill_days = fields.Float(
        string='Fill up to (days)',
        help="How many days of use an order should bring stock up to. 0 = the default in Recipe Settings.")
    reorder_avg_daily = fields.Float(
        string='Avg Daily Use', digits='Product Unit of Measure', readonly=True, copy=False,
        help="Average daily consumption over the history window (POS sales + waste + stocktake differences).")
    reorder_auto_point = fields.Float(
        string='Suggested Reorder Point', digits='Product Unit of Measure', readonly=True, copy=False)
    reorder_auto_max = fields.Float(
        string='Suggested Fill-up Level', digits='Product Unit of Measure', readonly=True, copy=False)
    reorder_point = fields.Float(
        string='Reorder Point', digits='Product Unit of Measure', copy=False,
        help="When stock on hand is at or below this, the ingredient goes on the Order Now list. "
             "Editing it switches the ingredient to Manual.")
    reorder_max_qty = fields.Float(
        string='Fill-up Level', digits='Product Unit of Measure', copy=False,
        help="Order Now suggests ordering up to this quantity. Editing it switches the ingredient to Manual.")
    reorder_computed_on = fields.Datetime(string='Recalculated On', readonly=True, copy=False)

    reorder_needed = fields.Boolean(
        string='Order Now', compute='_compute_reorder_status', search='_search_reorder_needed')
    reorder_order_qty = fields.Float(
        string='Order Qty', digits='Product Unit of Measure', compute='_compute_reorder_status')
    reorder_order_qty_po = fields.Float(
        string='Order Qty (Purchase Unit)', digits='Product Unit of Measure', compute='_compute_reorder_status')
    reorder_days_left = fields.Float(
        string='Days Left', digits=(16, 1), compute='_compute_reorder_status',
        help="Stock on hand ÷ average daily use (0 when stock is empty or negative).")
    reorder_vendor_id = fields.Many2one(
        'res.partner', string='Vendor', compute='_compute_reorder_status')

    @api.depends('qty_available', 'reorder_point', 'reorder_max_qty', 'reorder_avg_daily')
    def _compute_reorder_status(self):
        for product in self:
            # Negative stock is a recording error, not stock owed: order as if empty
            on_hand = max(product.qty_available, 0.0)
            needed = product.reorder_point > 0 and on_hand <= product.reorder_point
            qty = max(product.reorder_max_qty - on_hand, 0.0) if needed else 0.0
            product.reorder_needed = needed
            product.reorder_order_qty = float_round(qty, precision_rounding=product.uom_id.rounding,
                                                    rounding_method='UP')
            po_uom = product.uom_po_id or product.uom_id
            product.reorder_order_qty_po = product.uom_id._compute_quantity(
                qty, po_uom, rounding_method='UP') if qty else 0.0
            product.reorder_days_left = on_hand / product.reorder_avg_daily if product.reorder_avg_daily else 0.0
            sellers = product._prepare_sellers().filtered(
                lambda s: not s.company_id or s.company_id == self.env.company)
            product.reorder_vendor_id = sellers[:1].partner_id

    def _search_reorder_needed(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise NotImplementedError(_('Unsupported search on Order Now.'))
        candidates = self.search([('is_ingredient', '=', True), ('reorder_point', '>', 0)])
        ids = candidates.filtered('reorder_needed').ids
        return [('id', 'in' if (operator == '=') == value else 'not in', ids)]

    def write(self, vals):
        if not self.env.context.get('reorder_auto') and 'reorder_mode' not in vals \
                and ({'reorder_point', 'reorder_max_qty'} & set(vals)):
            vals = dict(vals, reorder_mode='manual')
        res = super().write(vals)
        if not self.env.context.get('reorder_auto') and \
                ({'reorder_cover_days', 'reorder_fill_days', 'reorder_mode'} & set(vals)):
            self._recipe_compute_reorder()
        return res

    @api.model
    def _reorder_settings(self):
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'history_days': max(int(float(ICP.get_param('pos_recipe_costing.reorder_history_days', 30) or 30)), 1),
            'cover_days': float(ICP.get_param('pos_recipe_costing.reorder_cover_days', 3) or 0),
            'fill_days': float(ICP.get_param('pos_recipe_costing.reorder_fill_days', 7) or 0),
        }

    def _recipe_compute_reorder(self):
        """Recalculate average use and the suggested levels; Auto ingredients also get them as their levels.
        With an empty recordset, every storable ingredient is recalculated."""
        products = self or self.search([('is_ingredient', '=', True), ('is_storable', '=', True)])
        products = products.filtered(lambda p: p.is_ingredient and p.is_storable)
        if not products:
            return True
        settings = self._reorder_settings()
        now = fields.Datetime.now()
        since = now - timedelta(days=settings['history_days'])
        self.env['stock.move'].flush_model(['state', 'product_id', 'product_qty', 'date',
                                            'location_id', 'location_dest_id'])
        self.env.cr.execute(CONSUMPTION_SQL, (tuple(products.ids), since))
        usage = {pid: (qty or 0.0, first) for pid, qty, first in self.env.cr.fetchall()}
        for product in products:
            qty, first = usage.get(product.id, (0.0, None))
            # A new ingredient is averaged over the days it has existed, not the whole window
            days = settings['history_days']
            if first:
                days = min(days, max((now - first).total_seconds() / 86400.0, 1.0))
            avg = max(qty, 0.0) / days
            rounding = product.uom_id.rounding
            cover = product.reorder_cover_days or settings['cover_days']
            fill = max(product.reorder_fill_days or settings['fill_days'], cover)
            vals = {
                'reorder_avg_daily': avg,
                'reorder_auto_point': float_round(avg * cover, precision_rounding=rounding, rounding_method='UP'),
                'reorder_auto_max': float_round(avg * fill, precision_rounding=rounding, rounding_method='UP'),
                'reorder_computed_on': now,
            }
            if product.reorder_mode != 'manual':
                vals.update(reorder_point=vals['reorder_auto_point'], reorder_max_qty=vals['reorder_auto_max'])
            product.with_context(reorder_auto=True).write(vals)
        return True

    @api.model
    def _cron_recipe_compute_reorder(self):
        self.browse()._recipe_compute_reorder()

    def action_reorder_set_auto(self):
        self.write({'reorder_mode': 'auto'})
        return True

    def action_reorder_recompute(self):
        self._recipe_compute_reorder()
        return True

    @api.model
    def action_reorder_recompute_all(self):
        self.browse()._recipe_compute_reorder()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    @api.model
    def action_print_order_now(self):
        products = self.search([('is_ingredient', '=', True), ('reorder_needed', '=', True)])
        return self.env.ref('pos_recipe_costing.action_report_order_now').report_action(products)

    @api.model
    def get_order_now_list(self):
        """The Order Now list as plain data, for Telegram and the DoniaLink connector.
        Ingredients at or below their reorder point, grouped by vendor, most urgent first."""
        settings = self._reorder_settings()
        products = self.search([('is_ingredient', '=', True), ('reorder_needed', '=', True)])
        items = []
        for p in products.sorted(lambda p: (p.reorder_days_left, p.display_name)):
            seller = p._prepare_sellers().filtered(
                lambda s: s.partner_id == p.reorder_vendor_id)[:1] if p.reorder_vendor_id else False
            items.append({
                'product_id': p.id,
                'name': p.display_name,
                'default_code': p.default_code or '',
                'category': p.categ_id.complete_name or '',
                'uom': p.uom_id.name,
                'on_hand': p.qty_available,
                'negative_stock': p.qty_available < 0,
                'avg_daily_use': p.reorder_avg_daily,
                'days_left': round(p.reorder_days_left, 1) if p.reorder_avg_daily else None,
                'reorder_point': p.reorder_point,
                'fill_up_level': p.reorder_max_qty,
                'order_qty': p.reorder_order_qty,
                'purchase_uom': (p.uom_po_id or p.uom_id).name,
                'order_qty_purchase_uom': p.reorder_order_qty_po,
                'mode': p.reorder_mode,
                'vendor_id': p.reorder_vendor_id.id or False,
                'vendor': p.reorder_vendor_id.name or '',
                'vendor_price': seller.price if seller else None,
                'vendor_lead_days': seller.delay if seller else None,
                'last_recalculated': fields.Datetime.to_string(p.reorder_computed_on) if p.reorder_computed_on else None,
            })
        return {
            'generated_at': fields.Datetime.to_string(fields.Datetime.now()),
            'company': self.env.company.name,
            'currency': self.env.company.currency_id.name,
            'settings': settings,
            'count': len(items),
            'items': items,
        }


class ReportOrderNow(models.AbstractModel):
    _name = 'report.pos_recipe_costing.report_order_now'
    _description = 'Order Now Report'

    @api.model
    def _get_report_values(self, docids, data=None):
        result = self.env['product.product'].get_order_now_list()
        items = result['items']
        if docids:
            items = [item for item in items if item['product_id'] in docids]
        groups = {}
        for item in items:
            groups.setdefault(item['vendor'] or _('No vendor'), []).append(item)
        # Vendors in name order, ingredients without a vendor last
        vendors = sorted(groups, key=lambda v: (v == _('No vendor'), v))
        return {
            'doc_ids': docids,
            'doc_model': 'product.product',
            'docs': self.env['product.product'].browse(docids),
            'data': result,
            'groups': [(vendor, groups[vendor]) for vendor in vendors],
            'count': len(items),
            'negative_count': len([i for i in items if i['negative_stock']]),
        }
