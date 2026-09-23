import json
import logging
from datetime import date, datetime, timedelta
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class FawtaraDashboardOwl(models.Model):
    _name = 'fawtara.dashboard.owl'
    _description = 'Fawtara OWL Dashboard Data'
    _check_company_auto = False

    name = fields.Char(default='Fawtara Dashboard')
    date_from = fields.Date(string='Date From')
    date_to = fields.Date(string='Date To')

    # ── Numeric KPIs ─────────────────────────────────────────────
    total_clients = fields.Integer(compute='_compute_kpis')
    active_clients = fields.Integer(compute='_compute_kpis')
    invoices_today = fields.Integer(compute='_compute_kpis')
    invoices_this_month = fields.Integer(compute='_compute_kpis')
    cleared_this_month = fields.Integer(compute='_compute_kpis')
    failed_this_month = fields.Integer(compute='_compute_kpis')
    clearance_rate = fields.Float(
        compute='_compute_kpis', digits=(5, 1))
    vat_this_month = fields.Float(
        compute='_compute_kpis', digits=(16, 3))
    total_overage_omr = fields.Float(
        compute='_compute_kpis', digits=(16, 3))
    queued_invoices = fields.Integer(compute='_compute_kpis')

    # ── JSON chart fields ─────────────────────────────────────────
    invoices_by_day = fields.Text(compute='_compute_charts')
    invoices_by_type = fields.Text(compute='_compute_charts')
    invoices_by_client = fields.Text(compute='_compute_charts')
    clearance_trend = fields.Text(compute='_compute_charts')
    vat_by_month = fields.Text(compute='_compute_charts')
    top_clients_table = fields.Text(compute='_compute_charts')
    failed_invoices_list = fields.Text(compute='_compute_charts')
    overage_clients_list = fields.Text(compute='_compute_charts')

    def _date_domain(self, field='created_at'):
        domain = []
        if self.date_from:
            domain.append(
                (field, '>=',
                 datetime.combine(self.date_from, datetime.min.time())))
        if self.date_to:
            domain.append(
                (field, '<=',
                 datetime.combine(self.date_to, datetime.max.time())))
        return domain

    def _month_range(self, months=6):
        result = []
        if self.date_from and self.date_to:
            cur = self.date_from.replace(day=1)
            while cur <= self.date_to:
                start = datetime.combine(cur, datetime.min.time())
                end = datetime.combine(
                    (cur + relativedelta(months=1)) - timedelta(days=1),
                    datetime.max.time())
                result.append((start, end, cur.strftime('%b %Y')))
                cur += relativedelta(months=1)
        else:
            today = datetime.today()
            for i in range(months - 1, -1, -1):
                m = today - relativedelta(months=i)
                start = m.replace(
                    day=1, hour=0, minute=0, second=0, microsecond=0)
                end = (start + relativedelta(months=1)) - timedelta(seconds=1)
                result.append((start, end, m.strftime('%b %Y')))
        return result

    def _compute_kpis(self):
        today = date.today()
        month_start = datetime.combine(today.replace(day=1), datetime.min.time())
        today_start = datetime.combine(today, datetime.min.time())

        inv = self.env['fawtara.invoice'].sudo()
        client = self.env['fawtara.client'].sudo()
        sub = self.env['fawtara.client.subscription'].sudo()

        for rec in self:
            domain = rec._date_domain('created_at')

            rec.total_clients = client.search_count([])
            rec.active_clients = client.search_count(
                [('status', '=', 'ACTIVE')])

            rec.invoices_today = inv.search_count(
                [('created_at', '>=', today_start)])
            rec.queued_invoices = inv.search_count(
                [('status', 'in', ['QUEUED', 'PROCESSING'])])

            if domain:
                base = domain
            else:
                base = [('created_at', '>=', month_start)]

            rec.invoices_this_month = inv.search_count(base)

            cleared = inv.search(
                base + [('status', '=', 'CLEARED')])
            rec.cleared_this_month = len(cleared)

            rec.failed_this_month = inv.search_count(
                base + [('status_group', '=', 'failed')])

            total = rec.invoices_this_month
            rec.clearance_rate = round(
                rec.cleared_this_month / total * 100, 1) if total else 0.0

            rec.vat_this_month = round(
                sum(cleared.mapped('total_tax')), 3)

            active_subs = sub.search([('state', '=', 'active')])
            rec.total_overage_omr = round(
                sum(active_subs.mapped('overage_amount_omr')), 3)

    def _compute_charts(self):
        inv = self.env['fawtara.invoice'].sudo()
        client = self.env['fawtara.client'].sudo()

        for rec in self:
            domain = rec._date_domain('created_at')
            if not domain:
                month_start = datetime.combine(
                    date.today().replace(day=1), datetime.min.time())
                domain = [('created_at', '>=', month_start)]

            # ── Invoices by day (last 30 days) ────────────────────
            today = date.today()
            day_data = []
            for i in range(29, -1, -1):
                d = today - timedelta(days=i)
                d_start = datetime.combine(d, datetime.min.time())
                d_end = datetime.combine(d, datetime.max.time())
                count = inv.search_count([
                    ('created_at', '>=', d_start),
                    ('created_at', '<=', d_end),
                ])
                day_data.append({
                    'day': d.strftime('%d %b'),
                    'count': count,
                })
            rec.invoices_by_day = json.dumps(day_data)

            # ── By type ───────────────────────────────────────────
            type_map = {
                '380': 'Tax Invoice (380)',
                '381': 'Credit Note (381)',
                '389': 'Self-Billing (389)',
                '261': 'SB Credit Note (261)',
            }
            type_data = []
            for code, label in type_map.items():
                count = inv.search_count(
                    domain + [('invoice_type_code', '=', code)])
                type_data.append({'label': label, 'count': count})
            rec.invoices_by_type = json.dumps(type_data)

            # ── By client ─────────────────────────────────────────
            clients = client.search(
                [('status', '=', 'ACTIVE')])
            client_data = []
            for c in clients:
                count = inv.search_count(
                    domain + [('fawtara_client_id', '=', c.id)])
                if count:
                    client_data.append({
                        'name': c.name,
                        'count': count,
                        'client_id': c.client_id,
                    })
            rec.invoices_by_client = json.dumps(
                sorted(client_data, key=lambda x: -x['count'])[:10])

            # ── Clearance trend (6 months) ─────────────────────────
            trend = []
            for start, end, label in rec._month_range(6):
                cleared = inv.search_count([
                    ('created_at', '>=', start),
                    ('created_at', '<=', end),
                    ('status', '=', 'CLEARED'),
                ])
                failed = inv.search_count([
                    ('created_at', '>=', start),
                    ('created_at', '<=', end),
                    ('status_group', '=', 'failed'),
                ])
                trend.append({
                    'month': label,
                    'cleared': cleared,
                    'failed': failed,
                })
            rec.clearance_trend = json.dumps(trend)

            # ── VAT by month ──────────────────────────────────────
            vat_data = []
            for start, end, label in rec._month_range(6):
                cleared_inv = inv.search([
                    ('created_at', '>=', start),
                    ('created_at', '<=', end),
                    ('status', '=', 'CLEARED'),
                ])
                vat = round(sum(cleared_inv.mapped('total_tax')), 3)
                vat_data.append({'month': label, 'vat': vat})
            rec.vat_by_month = json.dumps(vat_data)

            # ── Top clients table ─────────────────────────────────
            sub = self.env['fawtara.client.subscription'].sudo()
            table = []
            for c in clients:
                used = inv.search_count(
                    domain + [('fawtara_client_id', '=', c.id)])
                cleared_count = inv.search_count(
                    domain + [
                        ('fawtara_client_id', '=', c.id),
                        ('status', '=', 'CLEARED'),
                    ])
                failed_count = inv.search_count(
                    domain + [
                        ('fawtara_client_id', '=', c.id),
                        ('status_group', '=', 'failed'),
                    ])
                active_sub = sub.search([
                    ('client_id', '=', c.id),
                    ('state', '=', 'active'),
                ], limit=1)
                quota = active_sub.quota_invoices if active_sub else 0
                overage = active_sub.overage_amount_omr if active_sub else 0
                usage_pct = round(
                    used / quota * 100, 1) if quota else 0

                table.append({
                    'client_id': c.client_id or '',
                    'name':      c.name,
                    'vatin':     c.vatin,
                    'plan':      active_sub.plan_id.name
                                 if active_sub else 'No Plan',
                    'quota':     quota,
                    'used':      used,
                    'cleared':   cleared_count,
                    'failed':    failed_count,
                    'usage_pct': usage_pct,
                    'overage_omr': round(overage, 3),
                })
            rec.top_clients_table = json.dumps(
                sorted(table, key=lambda x: -x['used']))

            # ── Failed invoices ───────────────────────────────────
            failed_recs = inv.search(
                [('status_group', '=', 'failed')],
                order='created_at desc', limit=20)
            failed_list = []
            for f in failed_recs:
                failed_list.append({
                    'uuid':   f.invoice_uuid or '',
                    'number': f.invoice_number or '',
                    'client': f.client_name or f.client_id or '',
                    'type':   f.invoice_type_code or '',
                    'date':   str(f.issue_date or ''),
                    'status': f.status or '',
                    'error':  (f.error_detail or '')[:120],
                })
            rec.failed_invoices_list = json.dumps(failed_list)

            # ── Overage clients ───────────────────────────────────────
            active_subs = sub.search([('state', '=', 'active')])
            overage_list = []
            for s in active_subs:
                if s.overage_invoices > 0:
                    overage_list.append({
                        'name': s.client_id.name,
                        'plan': s.plan_id.name,
                        'quota': s.quota_invoices,
                        'used': s.invoices_used,
                        'overage': s.overage_invoices,
                        'amount': round(s.overage_amount_omr, 3),
                    })
            rec.overage_clients_list = json.dumps(overage_list)