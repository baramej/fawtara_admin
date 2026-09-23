import requests
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FawtaraClient(models.Model):
    _name = 'fawtara.client'
    _description = 'Fawtara E-Invoicing Client'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'onboarded_at desc'
    _check_company_auto = False

    # ── Identity ──────────────────────────────────────────────────
    name = fields.Char(
        string='Company Name (EN)', required=True, tracking=True)
    name_ar = fields.Char(
        string='Company Name (AR)', tracking=True)
    client_id = fields.Char(
        string='Client ID', readonly=True, copy=False,
        help='Unique ID assigned by Fawtara Spring Boot')
    cr_number = fields.Char(
        string='CR Number', required=True, tracking=True)
    vatin = fields.Char(
        string='VAT/TIN Number', required=True, tracking=True,
        help='OM + 10 digits e.g. OM1112345678')
    participant_id = fields.Char(
        string='Peppol Participant ID', readonly=True)

    # ── Contact ───────────────────────────────────────────────────
    contact_name = fields.Char(string='Contact Person')
    contact_email = fields.Char(
        string='Contact Email', required=True, tracking=True)
    contact_phone = fields.Char(string='Contact Phone')

    # ── Status ────────────────────────────────────────────────────
    status = fields.Selection([
        ('PENDING',     'Pending'),
        ('ACTIVE',      'Active'),
        ('SUSPENDED',   'Suspended'),
        ('OFFBOARDED',  'Offboarded'),
    ], string='Status', default='PENDING', tracking=True)

    smp_registered = fields.Boolean(
        string='SMP Registered', default=False, tracking=True)
    smp_registered_at = fields.Datetime(
        string='SMP Registration Date', readonly=True)

    # ── API Keys (display only — stored in Spring Boot) ───────────
    production_api_key = fields.Char(
        string='Production API Key',
        help='Shown once on creation. Store securely.')
    sandbox_api_key = fields.Char(
        string='Sandbox API Key',
        help='Shown once on creation. Store securely.')

    # ── Notes ─────────────────────────────────────────────────────
    notes = fields.Text(string='Internal Notes')
    onboarded_at = fields.Datetime(
        string='Onboarded At', default=fields.Datetime.now, readonly=True)
    onboarded_by = fields.Many2one(
        'res.users', string='Onboarded By',
        default=lambda self: self.env.user, readonly=True)

    # ── Invoice stats (computed) ───────────────────────────────────
    invoice_count = fields.Integer(
        string='Total Invoices', compute='_compute_invoice_stats')
    cleared_count = fields.Integer(
        string='Cleared', compute='_compute_invoice_stats')
    failed_count = fields.Integer(
        string='Failed', compute='_compute_invoice_stats')

    @api.depends('client_id')
    def _compute_invoice_stats(self):
        for rec in self:
            invoices = self.env['fawtara.invoice'].sudo().search(
                [('client_id', '=', rec.client_id)])
            rec.invoice_count = len(invoices)
            rec.cleared_count = len(
                invoices.filtered(lambda i: i.status == 'CLEARED'))
            rec.failed_count = len(
                invoices.filtered(lambda i: i.status == 'FAILED'))

    # ── Billing ───────────────────────────────────────────────────
    subscription_ids = fields.One2many(
        'fawtara.client.subscription',
        'client_id',
        string='Subscriptions')

    active_subscription_id = fields.Many2one(
        'fawtara.client.subscription',
        string='Active Plan',
        compute='_compute_active_subscription')

    plan_name = fields.Char(
        string='Current Plan',
        compute='_compute_active_subscription')

    quota_invoices = fields.Integer(
        string='Invoice Quota',
        compute='_compute_active_subscription')

    invoices_used = fields.Integer(
        string='Invoices Used This Period',
        compute='_compute_active_subscription')

    usage_percent = fields.Float(
        string='Usage %',
        compute='_compute_active_subscription',
        digits=(5, 1))

    overage_amount_omr = fields.Float(
        string='Overage Due (OMR)',
        compute='_compute_active_subscription',
        digits=(16, 3))

    @api.depends('subscription_ids', 'subscription_ids.state')
    def _compute_active_subscription(self):
        for rec in self:
            sub = self.env['fawtara.client.subscription'].sudo().search([
                ('client_id', '=', rec.id),
                ('state', '=', 'active'),
            ], limit=1, order='start_date desc')

            rec.active_subscription_id = sub
            rec.plan_name = sub.plan_id.name if sub else 'No Plan'
            rec.quota_invoices = sub.quota_invoices if sub else 0
            rec.invoices_used = sub.invoices_used if sub else 0
            rec.usage_percent = sub.usage_percent if sub else 0.0
            rec.overage_amount_omr = sub.overage_amount_omr if sub else 0.0

    def action_view_subscriptions(self):
        return {
            'type': 'ir.actions.act_window',
            'name': f'Subscriptions — {self.name}',
            'res_model': 'fawtara.client.subscription',
            'view_mode': 'list,form',
            'domain': [('client_id', '=', self.id)],
            'context': {'default_client_id': self.id},
        }

    # ── Actions ───────────────────────────────────────────────────

    def action_view_invoices(self):
        return {
            'type': 'ir.actions.act_window',
            'name': f'Invoices — {self.name}',
            'res_model': 'fawtara.invoice',
            'view_mode': 'list,form',
            'domain': [('client_id', '=', self.client_id)],
            'context': {'default_client_id': self.client_id},
        }

    def action_register_smp(self):
        """Call Spring Boot to register client on Peppol SMP."""
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('fawtara.api_url')
        admin_key = config.get_param('fawtara.admin_api_key')

        try:
            url = f"{base_url}/api/v1/clients/{self.client_id}/smp/register"
            resp = requests.post(url, headers={
                'X-API-Key': admin_key,
                'Content-Type': 'application/json',
            }, timeout=30)

            if resp.status_code == 200:
                data = resp.json()
                self.write({
                    'smp_registered': True,
                    'smp_registered_at': fields.Datetime.now(),
                })
                self.message_post(
                    body=f"✅ SMP registration successful. "
                         f"Participant ID: {data.get('participantId')}")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'SMP Registration Successful',
                        'message': f"Client registered on Peppol network.",
                        'type': 'success',
                    }
                }
            else:
                raise UserError(
                    f"SMP registration failed: {resp.status_code} — {resp.text}")

        except requests.exceptions.RequestException as e:
            raise UserError(f"Cannot reach Fawtara API: {str(e)}")

    def action_deregister_smp(self):
        """Deregister client from Peppol SMP."""
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('fawtara.api_url')
        admin_key = config.get_param('fawtara.admin_api_key')

        try:
            url = f"{base_url}/api/v1/clients/{self.client_id}/smp/deregister"
            resp = requests.delete(url, headers={
                'X-API-Key': admin_key,
            }, timeout=30)

            if resp.status_code == 200:
                self.write({'smp_registered': False})
                self.message_post(body="⚠️ SMP deregistration completed.")
            else:
                raise UserError(
                    f"SMP deregistration failed: {resp.status_code} — {resp.text}")

        except requests.exceptions.RequestException as e:
            raise UserError(f"Cannot reach Fawtara API: {str(e)}")

    def action_suspend(self):
        """Suspend client — revokes all API keys."""
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('fawtara.api_url')
        admin_key = config.get_param('fawtara.admin_api_key')

        try:
            url = f"{base_url}/api/v1/clients/{self.client_id}/suspend"
            resp = requests.post(url, headers={
                'X-API-Key': admin_key,
            }, timeout=15)

            if resp.status_code == 200:
                self.write({'status': 'SUSPENDED'})
                self.message_post(body="🚫 Client suspended. All API keys revoked.")
            else:
                raise UserError(f"Suspend failed: {resp.text}")

        except requests.exceptions.RequestException as e:
            raise UserError(f"Cannot reach Fawtara API: {str(e)}")

    def action_rotate_key(self):
        """Rotate production API key."""
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('fawtara.api_url')
        admin_key = config.get_param('fawtara.admin_api_key')

        try:
            url = (f"{base_url}/api/v1/clients/{self.client_id}"
                   f"/apikey/rotate?environment=PRODUCTION")
            resp = requests.post(url, headers={
                'X-API-Key': admin_key,
            }, timeout=15)

            if resp.status_code == 200:
                data = resp.json()
                new_key = data.get('newApiKey')
                self.write({'production_api_key': new_key})
                self.message_post(
                    body="🔑 Production API key rotated. Share new key with client.")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'API Key Rotated',
                        'message': f"New key: {new_key}",
                        'type': 'warning',
                        'sticky': True,
                    }
                }
            else:
                raise UserError(f"Key rotation failed: {resp.text}")

        except requests.exceptions.RequestException as e:
            raise UserError(f"Cannot reach Fawtara API: {str(e)}")