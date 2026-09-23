from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api


class FawtaraDashboard(models.Model):
    _name = 'fawtara.dashboard'
    _description = 'Fawtara Admin Dashboard'
    _check_company_auto = False

    name = fields.Char(default='Dashboard')

    # ── KPIs ──────────────────────────────────────────────────────
    total_clients = fields.Integer(
        string='Total Clients',
        compute='_compute_kpis')
    active_clients = fields.Integer(
        string='Active Clients',
        compute='_compute_kpis')
    invoices_today = fields.Integer(
        string='Invoices Today',
        compute='_compute_kpis')
    invoices_this_month = fields.Integer(
        string='Invoices This Month',
        compute='_compute_kpis')
    cleared_this_month = fields.Integer(
        string='Cleared This Month',
        compute='_compute_kpis')
    failed_this_month = fields.Integer(
        string='Failed This Month',
        compute='_compute_kpis')
    clearance_rate = fields.Float(
        string='Clearance Rate %',
        compute='_compute_kpis', digits=(5, 1))
    vat_this_month = fields.Float(
        string='VAT Submitted (OMR)',
        compute='_compute_kpis', digits=(16, 3))
    total_overage_omr = fields.Float(
        string='Total Overage Due (OMR)',
        compute='_compute_kpis', digits=(16, 3))

    def _compute_kpis(self):
        for rec in self:
            today = date.today()
            month_start = today.replace(day=1)
            month_start_dt = fields.Datetime.to_datetime(
                str(month_start))
            today_start_dt = fields.Datetime.to_datetime(
                str(today))

            inv = self.env['fawtara.invoice'].sudo()
            client = self.env['fawtara.client'].sudo()
            sub = self.env['fawtara.client.subscription'].sudo()

            rec.total_clients = client.search_count([])
            rec.active_clients = client.search_count(
                [('status', '=', 'ACTIVE')])

            rec.invoices_today = inv.search_count([
                ('created_at', '>=', today_start_dt)])
            rec.invoices_this_month = inv.search_count([
                ('created_at', '>=', month_start_dt)])

            cleared = inv.search([
                ('created_at', '>=', month_start_dt),
                ('status', '=', 'CLEARED')])
            rec.cleared_this_month = len(cleared)

            rec.failed_this_month = inv.search_count([
                ('created_at', '>=', month_start_dt),
                ('status', 'in', ['FAILED', 'REJECTED',
                                   'VALIDATION_FAILED'])])

            total = rec.invoices_this_month
            rec.clearance_rate = (
                rec.cleared_this_month / total * 100
                if total > 0 else 0.0)

            rec.vat_this_month = sum(
                cleared.mapped('total_tax'))

            # Total overage across all active subscriptions
            active_subs = sub.search([('state', '=', 'active')])
            rec.total_overage_omr = sum(
                active_subs.mapped('overage_amount_omr'))