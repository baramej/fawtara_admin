import requests
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FawtaraInvoice(models.Model):
    _name = 'fawtara.invoice'
    _description = 'Fawtara Invoice Record'
    _order = 'created_at desc'
    _check_company_auto = False

    # ── Name (required by Odoo as display name) ───────────────────
    name = fields.Char(
        string='Invoice Number',
        compute='_compute_name',
        store=True)

    # ── Identity ──────────────────────────────────────────────────
    invoice_uuid = fields.Char(
        string='Invoice UUID', readonly=True, index=True)
    invoice_number = fields.Char(
        string='Invoice Number (raw)', readonly=True)
    client_id = fields.Char(
        string='Client ID', readonly=True, index=True)
    client_name = fields.Char(
        string='Client',
        compute='_compute_client_name',
        store=True)

    # ── Type ──────────────────────────────────────────────────────
    invoice_type_code = fields.Selection([
        ('380', '380 — Tax Invoice'),
        ('381', '381 — Credit Note'),
        ('389', '389 — Self-Billing Invoice'),
        ('261', '261 — Self-Billing Credit Note'),
    ], string='Type', readonly=True)

    transaction_type = fields.Selection([
        ('B2B', 'B2B'),
        ('B2C', 'B2C'),
        ('B2G', 'B2G'),
    ], string='Transaction', readonly=True)

    # ── Parties ───────────────────────────────────────────────────
    seller_vatin = fields.Char(string='Seller VATIN', readonly=True)
    seller_name = fields.Char(string='Seller Name', readonly=True)
    buyer_vatin = fields.Char(string='Buyer VATIN', readonly=True)
    buyer_name = fields.Char(string='Buyer Name', readonly=True)

    # ── Amounts ───────────────────────────────────────────────────
    currency_code = fields.Char(
        string='Currency', readonly=True, default='OMR')
    total_excl_tax = fields.Float(
        string='Total (excl. VAT)', readonly=True, digits=(16, 3))
    total_tax = fields.Float(
        string='VAT Amount', readonly=True, digits=(16, 3))
    total_incl_tax = fields.Float(
        string='Total (incl. VAT)', readonly=True, digits=(16, 3))

    # ── Dates ─────────────────────────────────────────────────────
    issue_date = fields.Date(string='Issue Date', readonly=True)
    created_at = fields.Datetime(string='Received At', readonly=True)

    # ── Status ────────────────────────────────────────────────────
    status = fields.Selection([
        ('QUEUED',      'Queued'),
        ('PROCESSING',  'Processing'),
        ('CLEARED',     'Cleared'),
        ('FAILED',      'Failed'),
        ('REJECTED',    'Rejected'),
    ], string='Status', readonly=True)

    error_detail = fields.Text(
        string='Error Detail', readonly=True)
    invoice_uuid_v5 = fields.Char(
        string='UUID v5', readonly=True)
    clearance_id = fields.Char(
        string='Clearance ID', readonly=True)

    # ── Computes ──────────────────────────────────────────────────

    @api.depends('invoice_number', 'invoice_uuid')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.invoice_number or rec.invoice_uuid or 'New'

    @api.depends('client_id')
    def _compute_client_name(self):
        for rec in self:
            client = self.env['fawtara.client'].sudo().search(
                [('client_id', '=', rec.client_id)], limit=1)
            rec.client_name = client.name if client else (rec.client_id or '')

    # ── Actions ───────────────────────────────────────────────────

    def action_refresh_status(self):
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('fawtara.api_url')
        admin_key = config.get_param('fawtara.admin_api_key')

        try:
            url = f"{base_url}/api/v1/invoice/{self.invoice_uuid}"
            resp = requests.get(url, headers={
                'X-API-Key': admin_key,
            }, timeout=15)

            if resp.status_code == 200:
                data = resp.json()
                self.write({
                    'status':       data.get('status', self.status),
                    'error_detail': data.get('errorDetail'),
                    'clearance_id': data.get('clearanceId'),
                })
            else:
                raise UserError(
                    f"Status refresh failed: {resp.status_code} — {resp.text}")

        except requests.exceptions.RequestException as e:
            raise UserError(f"Cannot reach Fawtara API: {str(e)}")