import logging
from datetime import date
from dateutil.relativedelta import relativedelta
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FawtaraBillingPlan(models.Model):
    _name = 'fawtara.billing.plan'
    _description = 'Fawtara Billing Plan Template'
    _order = 'quota_invoices asc'
    _check_company_auto = False

    name = fields.Char(string='Plan Name', required=True)
    quota_invoices = fields.Integer(
        string='Invoice Quota', required=True,
        help='Maximum invoices included in plan price')
    price_omr = fields.Float(
        string='Plan Price (OMR)', required=True, digits=(16, 3))
    overage_rate_bzs = fields.Float(
        string='Overage Rate (Baisa per invoice)',
        default=50.0, digits=(16, 3),
        help='Charged per invoice above quota. 1 OMR = 1000 Baisa')
    billing_cycle = fields.Selection([
        ('monthly',  'Monthly'),
        ('annual',   'Annual'),
    ], string='Billing Cycle', default='monthly', required=True)
    active = fields.Boolean(default=True)
    description = fields.Text(string='Plan Description')

    @api.depends('quota_invoices', 'price_omr')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"{rec.name} — {rec.quota_invoices:,} invoices "
                f"@ {rec.price_omr:.3f} OMR")


class FawtaraClientSubscription(models.Model):
    _name = 'fawtara.client.subscription'
    _description = 'Client Billing Subscription'
    _order = 'start_date desc'
    _inherit = ['mail.thread']
    _check_company_auto = False

    name = fields.Char(
        string='Subscription',
        compute='_compute_name', store=True)

    client_id = fields.Many2one(
        'fawtara.client',
        string='Client', required=True,
        ondelete='cascade', tracking=True)

    plan_id = fields.Many2one(
        'fawtara.billing.plan',
        string='Plan', required=True, tracking=True)

    # ── Plan snapshot (stored at time of subscription) ────────────
    quota_invoices = fields.Integer(
        string='Invoice Quota',
        related='plan_id.quota_invoices', store=True)
    price_omr = fields.Float(
        string='Plan Price (OMR)',
        related='plan_id.price_omr', store=True, digits=(16, 3))
    overage_rate_bzs = fields.Float(
        string='Overage Rate (Bzs)',
        related='plan_id.overage_rate_bzs', store=True, digits=(16, 3))

    # ── Dates ─────────────────────────────────────────────────────
    start_date = fields.Date(
        string='Start Date', required=True,
        default=fields.Date.today, tracking=True)
    end_date = fields.Date(
        string='End Date', tracking=True)
    renewal_date = fields.Date(
        string='Next Renewal',
        compute='_compute_renewal_date', store=True)

    # ── Status ────────────────────────────────────────────────────
    state = fields.Selection([
        ('active',    'Active'),
        ('expired',   'Expired'),
        ('cancelled', 'Cancelled'),
    ], string='State', default='active', tracking=True)

    # ── Current period usage ──────────────────────────────────────
    period_start = fields.Date(
        string='Current Period Start',
        compute='_compute_period', store=False)
    period_end = fields.Date(
        string='Current Period End',
        compute='_compute_period', store=False)
    invoices_used = fields.Integer(
        string='Invoices Used',
        compute='_compute_usage')
    invoices_remaining = fields.Integer(
        string='Invoices Remaining',
        compute='_compute_usage')
    overage_invoices = fields.Integer(
        string='Overage Invoices',
        compute='_compute_usage')
    overage_amount_omr = fields.Float(
        string='Overage Amount (OMR)',
        compute='_compute_usage', digits=(16, 3))
    usage_percent = fields.Float(
        string='Usage %',
        compute='_compute_usage', digits=(5, 1))

    notes = fields.Text(string='Notes')

    @api.depends('client_id', 'plan_id', 'start_date')
    def _compute_name(self):
        for rec in self:
            client = rec.client_id.name or ''
            plan = rec.plan_id.name or ''
            dt = str(rec.start_date or '')
            rec.name = f"{client} — {plan} ({dt})"

    @api.depends('start_date', 'plan_id.billing_cycle')
    def _compute_renewal_date(self):
        for rec in self:
            if not rec.start_date:
                rec.renewal_date = False
                continue
            if rec.plan_id.billing_cycle == 'annual':
                rec.renewal_date = (
                    rec.start_date + relativedelta(years=1))
            else:
                rec.renewal_date = (
                    rec.start_date + relativedelta(months=1))

    def _compute_period(self):
        today = date.today()
        for rec in self:
            if not rec.start_date:
                rec.period_start = today.replace(day=1)
                rec.period_end = (
                    today.replace(day=1)
                    + relativedelta(months=1)
                    - relativedelta(days=1))
                continue
            if rec.plan_id.billing_cycle == 'annual':
                # Annual — period = subscription year
                rec.period_start = rec.start_date
                rec.period_end = (
                    rec.start_date + relativedelta(years=1)
                    - relativedelta(days=1))
            else:
                # Monthly — current calendar month
                rec.period_start = today.replace(day=1)
                rec.period_end = (
                    today.replace(day=1)
                    + relativedelta(months=1)
                    - relativedelta(days=1))

    @api.depends('client_id', 'plan_id', 'start_date')
    def _compute_usage(self):
        today = date.today()
        for rec in self:
            # Current period bounds
            if rec.plan_id.billing_cycle == 'annual':
                p_start = rec.start_date or today.replace(day=1)
                p_end = p_start + relativedelta(years=1)
            else:
                p_start = today.replace(day=1)
                p_end = p_start + relativedelta(months=1)

            # Count cleared invoices for this client in period
            used = self.env['fawtara.invoice'].sudo().search_count([
                ('fawtara_client_id', '=', rec.client_id.id),
                ('status', '=', 'CLEARED'),
                ('created_at', '>=',
                 fields.Datetime.to_datetime(str(p_start))),
                ('created_at', '<',
                 fields.Datetime.to_datetime(str(p_end))),
            ])

            quota = rec.quota_invoices or 0
            overage = max(0, used - quota)
            remaining = max(0, quota - used)
            # Convert baisa to OMR (1000 baisa = 1 OMR)
            overage_omr = (overage * rec.overage_rate_bzs) / 1000
            pct = (used / quota * 100) if quota > 0 else 0.0

            rec.invoices_used = used
            rec.invoices_remaining = remaining
            rec.overage_invoices = overage
            rec.overage_amount_omr = overage_omr
            rec.usage_percent = min(pct, 999.9)

    def action_cancel(self):
        self.write({'state': 'cancelled'})
        self.message_post(body="Subscription cancelled.")

    def action_reactivate(self):
        self.write({'state': 'active'})
        self.message_post(body="Subscription reactivated.")

    def action_check_usage_alerts(self):
        """Send alerts when client hits 80% or 100% of quota."""
        for rec in self.search([('state', '=', 'active')]):
            pct = rec.usage_percent
            client = rec.client_id
            if pct >= 100:
                rec.message_post(
                    body=f"🚨 <b>Quota Exceeded</b> — "
                         f"{client.name} has used "
                         f"{rec.invoices_used:,} / {rec.quota_invoices:,} "
                         f"invoices. Overage: {rec.overage_invoices:,} "
                         f"invoices = {rec.overage_amount_omr:.3f} OMR")
            elif pct >= 80:
                rec.message_post(
                    body=f"⚠️ <b>80% Quota Warning</b> — "
                         f"{client.name} has used "
                         f"{rec.invoices_used:,} / {rec.quota_invoices:,} "
                         f"invoices ({pct:.1f}%)")