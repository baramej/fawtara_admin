import logging

import psycopg2
import requests

from odoo import models, fields, api, Command
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Every status Spring Boot can emit (Invoice.status / ctx.failureStatus)
FAWTARA_STATUSES = [
    ('QUEUED', 'Queued'),
    ('PROCESSING', 'Processing'),
    ('CLEARED', 'Cleared'),
    ('FAILED', 'Failed'),
    ('FAILED_PERMANENT', 'Failed (permanent)'),
    ('VALIDATION_FAILED', 'Validation Failed'),
    ('SCHEMATRON_FAILED', 'Schematron Failed'),
    ('SCHEMATRON_ERROR', 'Schematron Error'),
    ('XML_BUILD_FAILED', 'XML Build Failed'),
    ('SIGNING_FAILED', 'Signing Failed'),
    ('QR_GENERATION_FAILED', 'QR Generation Failed'),
    ('OTA_FAILED', 'OTA Failed'),
    ('PROCESSING_FAILED', 'Processing Failed'),
    ('REJECTED', 'Rejected'),
]
_KNOWN_STATUSES = {code for code, _label in FAWTARA_STATUSES}
_STATUS_RANK = {'QUEUED': 1, 'PROCESSING': 2}   # anything else = terminal (3)


def _status_group(status):
    if not status or status == 'QUEUED':
        return 'queued'
    if status == 'PROCESSING':
        return 'processing'
    if status == 'CLEARED':
        return 'cleared'
    return 'failed'


class FawtaraInvoice(models.Model):
    """Canonical ledger of every invoice Fawtara has received for a client,
    whatever the channel (direct API, Odoo portal form, Odoo Excel upload).

    Records are created/updated by Spring Boot's webhook
    (see fawtara_portal/controllers/webhook_controller.py → upsert_from_fawtara)
    and by the "Sync from Fawtara" action (GET /api/v1/invoice).
    """
    _name = 'fawtara.invoice'
    _description = 'Fawtara Invoice Record'
    _order = 'created_at desc, id desc'
    _check_company_auto = False

    _invoice_uuid_uniq = models.Constraint(
        'UNIQUE(invoice_uuid)', 'Invoice UUID must be unique.')

    # ── Name (required by Odoo as display name) ───────────────────
    name = fields.Char(
        string='Invoice Number',
        compute='_compute_name',
        store=True)

    # ── Identity ──────────────────────────────────────────────────
    invoice_uuid = fields.Char(
        string='Invoice UUID', readonly=True, index=True)
    invoice_number = fields.Char(
        string='Invoice Number (raw)', readonly=True, index=True)
    client_id = fields.Char(
        string='Client ID', readonly=True, index=True,
        help='Spring Boot clientId of the API key used to submit.')
    fawtara_client_id = fields.Many2one(
        'fawtara.client', string='Fawtara Client',
        index=True, readonly=True, ondelete='restrict')
    company_id = fields.Many2one(
        'res.company', string='Company',
        related='fawtara_client_id.company_id', store=True, index=True)
    client_name = fields.Char(
        string='Client',
        related='fawtara_client_id.name', store=True)

    source = fields.Selection([
        ('API', 'API'),
        ('PORTAL', 'Portal Form'),
        ('EXCEL', 'Excel Upload'),
    ], string='Channel', default='API', readonly=True, index=True)
    environment = fields.Selection([
        ('PRODUCTION', 'Production'),
        ('SANDBOX', 'Sandbox'),
    ], string='Environment', default='PRODUCTION', readonly=True, index=True)

    # ── Type ──────────────────────────────────────────────────────
    invoice_type_code = fields.Selection([
        ('380', '380 — Tax Invoice'),
        ('381', '381 — Credit Note'),
        ('384', '384 — Corrected Invoice'),
        ('389', '389 — Self-Billing Invoice'),
        ('261', '261 — Self-Billing Credit Note'),
    ], string='Type', readonly=True)

    transaction_type = fields.Selection([
        ('B2B', 'B2B'),
        ('B2C', 'B2C'),
        ('B2G', 'B2G'),
    ], string='Transaction', readonly=True)

    # ── Parties ───────────────────────────────────────────────────
    seller_vatin = fields.Char(string='Seller VATIN', readonly=True, index=True)
    seller_name = fields.Char(string='Seller Name', readonly=True)
    seller_address_line1 = fields.Char(string='Seller Address 1', readonly=True)
    seller_address_line2 = fields.Char(string='Seller Address 2', readonly=True)
    seller_address_line3 = fields.Char(string='Seller Address 3', readonly=True)
    seller_city = fields.Char(string='Seller City', readonly=True)
    seller_post_code = fields.Char(string='Seller Post Code', readonly=True)
    seller_country_code = fields.Char(string='Seller Country', readonly=True)
    seller_contact_name = fields.Char(string='Seller Contact', readonly=True)
    seller_contact_phone = fields.Char(string='Seller Phone', readonly=True)
    seller_contact_email = fields.Char(string='Seller Email', readonly=True)

    buyer_vatin = fields.Char(string='Buyer VATIN', readonly=True)
    buyer_name = fields.Char(string='Buyer Name', readonly=True)
    buyer_address_line1 = fields.Char(string='Buyer Address 1', readonly=True)
    buyer_address_line2 = fields.Char(string='Buyer Address 2', readonly=True)
    buyer_address_line3 = fields.Char(string='Buyer Address 3', readonly=True)
    buyer_city = fields.Char(string='Buyer City', readonly=True)
    buyer_post_code = fields.Char(string='Buyer Post Code', readonly=True)
    buyer_country_code = fields.Char(string='Buyer Country', readonly=True)

    # ── References ────────────────────────────────────────────────
    invoice_note = fields.Text(string='Note', readonly=True)
    contract_reference = fields.Char(string='Contract Reference', readonly=True)
    purchase_order_reference = fields.Char(string='PO Reference', readonly=True)
    preceding_invoice_number = fields.Char(string='Original Invoice', readonly=True)
    preceding_invoice_uuid = fields.Char(string='Original Invoice UUID', readonly=True)
    preceding_invoice_date = fields.Date(string='Original Invoice Date', readonly=True)
    credit_note_reason = fields.Char(string='Credit Note Reason', readonly=True)

    # ── Amounts ───────────────────────────────────────────────────
    currency_code = fields.Char(
        string='Currency', readonly=True, default='OMR')
    total_excl_tax = fields.Float(
        string='Total (excl. VAT)', readonly=True, digits=(16, 3))
    total_tax = fields.Float(
        string='VAT Amount', readonly=True, digits=(16, 3))
    total_incl_tax = fields.Float(
        string='Total (incl. VAT)', readonly=True, digits=(16, 3))
    amount_due = fields.Float(
        string='Amount Due', readonly=True, digits=(16, 3))

    line_ids = fields.One2many(
        'fawtara.invoice.line', 'invoice_id', string='Lines', readonly=True)

    # ── Dates ─────────────────────────────────────────────────────
    issue_date = fields.Date(string='Issue Date', readonly=True)
    issue_time = fields.Char(string='Issue Time', readonly=True)
    created_at = fields.Datetime(string='Received At', readonly=True)
    last_sync_at = fields.Datetime(string='Last Update from Fawtara', readonly=True)

    # ── Status ────────────────────────────────────────────────────
    status = fields.Selection(
        FAWTARA_STATUSES, string='Status', readonly=True, index=True)
    status_group = fields.Selection([
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('cleared', 'Cleared'),
        ('failed', 'Failed'),
    ], string='Status Group', compute='_compute_status_group',
        store=True, index=True)

    error_detail = fields.Text(
        string='Error Detail', readonly=True)
    invoice_uuid_v5 = fields.Char(
        string='UUID v5', readonly=True)
    tdd_uuid = fields.Char(
        string='TDD UUID', readonly=True)
    clearance_id = fields.Char(
        string='Clearance ID', readonly=True)

    # ── Computes ──────────────────────────────────────────────────

    @api.depends('invoice_number', 'invoice_uuid')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.invoice_number or rec.invoice_uuid or 'New'

    @api.depends('status')
    def _compute_status_group(self):
        for rec in self:
            rec.status_group = _status_group(rec.status)

    # ── Upsert from Spring Boot ───────────────────────────────────

    @api.model
    def _vals_from_fawtara(self, data):
        """Translate a Spring Boot invoice dict (webhook snapshot or
        InvoiceSummaryResponse) into field values. Keys absent from
        `data` are left out so partial payloads never blank fields."""
        def num(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        def dt(v):
            # Spring LocalDateTime → '2026-09-23T09:45:12.123'
            if not v:
                return None
            return str(v).replace('T', ' ')[:19]

        mapping = {
            'invoice_uuid': data.get('invoiceUuid'),
            'invoice_uuid_v5': data.get('invoiceUuidV5'),
            'tdd_uuid': data.get('tddUuid'),
            'invoice_number': data.get('invoiceNumber'),
            'client_id': data.get('clientId'),
            'environment': data.get('environment'),
            'source': data.get('source'),
            'invoice_type_code': data.get('invoiceTypeCode'),
            'transaction_type': data.get('transactionType'),
            'issue_date': data.get('issueDate'),
            'issue_time': data.get('issueTime'),
            'currency_code': data.get('currencyCode'),
            'invoice_note': data.get('invoiceNote'),
            'contract_reference': data.get('contractReference'),
            'purchase_order_reference': data.get('purchaseOrderReference'),
            'seller_name': data.get('sellerName'),
            'seller_vatin': data.get('sellerVatin') or data.get('companyVatin'),
            'seller_address_line1': data.get('sellerAddressLine1'),
            'seller_address_line2': data.get('sellerAddressLine2'),
            'seller_address_line3': data.get('sellerAddressLine3'),
            'seller_city': data.get('sellerCity'),
            'seller_post_code': data.get('sellerPostCode'),
            'seller_country_code': data.get('sellerCountryCode'),
            'seller_contact_name': data.get('sellerContactName'),
            'seller_contact_phone': data.get('sellerContactPhone'),
            'seller_contact_email': data.get('sellerContactEmail'),
            'buyer_name': data.get('buyerName'),
            'buyer_vatin': data.get('buyerVatin'),
            'buyer_address_line1': data.get('buyerAddressLine1'),
            'buyer_address_line2': data.get('buyerAddressLine2'),
            'buyer_address_line3': data.get('buyerAddressLine3'),
            'buyer_city': data.get('buyerCity'),
            'buyer_post_code': data.get('buyerPostCode'),
            'buyer_country_code': data.get('buyerCountryCode'),
            'preceding_invoice_number': data.get('precedingInvoiceNumber'),
            'preceding_invoice_uuid': data.get('precedingInvoiceUuid'),
            'preceding_invoice_date': data.get('precedingInvoiceDate'),
            'credit_note_reason': data.get('creditNoteReasonCode'),
            'total_excl_tax': num(data.get('totalAmountWithoutTax')),
            'total_tax': num(data.get('totalTaxAmount')),
            'total_incl_tax': num(data.get('totalAmountWithTax')),
            'amount_due': num(data.get('amountDueForPayment')),
            'error_detail': data.get('errorDetail'),
            'clearance_id': data.get('clearanceId'),
            'created_at': dt(data.get('createdAt')),
        }
        vals = {k: v for k, v in mapping.items() if v not in (None, '')}
        # Clear a stale error once the invoice clears
        if data.get('status') == 'CLEARED':
            vals.setdefault('error_detail', False)

        # Selection guards — never let an unknown code break the write
        sel = self._fields
        for fname in ('environment', 'source', 'invoice_type_code',
                      'transaction_type'):
            if fname in vals:
                allowed = set(sel[fname].get_values(self.env))
                if vals[fname] not in allowed:
                    vals.pop(fname)
        status = data.get('status')
        if status:
            vals['status'] = status if status in _KNOWN_STATUSES else 'FAILED'
        return vals

    @api.model
    def _line_commands(self, lines):
        cmds = [Command.clear()]
        for i, l in enumerate(lines or [], start=1):
            cmds.append(Command.create({
                'sequence': i,
                'line_ref': l.get('lineId'),
                'item_name': l.get('itemName') or '',
                'quantity': l.get('quantity') or 0.0,
                'unit_code': l.get('unitCode'),
                'unit_price': l.get('unitPrice') or 0.0,
                'line_total': l.get('lineNetAmount') or 0.0,
                'vat_category_code': l.get('vatCategoryCode'),
                'vat_rate': l.get('vatRate') or 0.0,
                'vat_amount': l.get('vatAmount') or 0.0,
                'service_type_code': l.get('serviceTypeCode'),
                'isic_code': l.get('isicCode'),
            }))
        return cmds

    @api.model
    def upsert_from_fawtara(self, data):
        """Create or update one invoice from Spring Boot data.

        Safe to call repeatedly and out of order:
          * matches on invoice_uuid (unique)
          * a late QUEUED/PROCESSING push never overwrites a terminal status
          * a concurrent create of the same UUID (webhook racing the
            portal's own create) falls back to an update
        Returns the record id.
        """
        uuid = data.get('invoiceUuid')
        if not uuid:
            raise UserError('invoiceUuid missing')

        Inv = self.sudo().with_context(tracking_disable=True)
        vals = self._vals_from_fawtara(data)
        vals['last_sync_at'] = fields.Datetime.now()

        client = self.env['fawtara.client']._resolve_from_fawtara(
            data.get('clientId'),
            data.get('sellerVatin') or data.get('companyVatin'))
        if client:
            vals['fawtara_client_id'] = client.id

        if data.get('lines'):
            vals['line_ids'] = self._line_commands(data['lines'])

        rec = Inv.search([('invoice_uuid', '=', uuid)], limit=1)
        if not rec:
            try:
                with self.env.cr.savepoint():
                    rec = Inv.create(vals)
                _logger.info('Fawtara invoice created from %s — uuid: %s, client: %s',
                             vals.get('source', 'API'), uuid,
                             client.name if client else 'UNMATCHED')
                return rec.id
            except psycopg2.IntegrityError:
                rec = Inv.search([('invoice_uuid', '=', uuid)], limit=1)
                if not rec:
                    raise

        # Out-of-order protection
        incoming = vals.get('status')
        if incoming and _STATUS_RANK.get(incoming, 3) < _STATUS_RANK.get(rec.status, 3):
            vals.pop('status')
        # Don't let a summary (no source key) reset a known channel
        if 'source' not in data:
            vals.pop('source', None)
        rec.write(vals)
        return rec.id

    # ── Pull sync (recovers missed webhooks / historical invoices) ──

    @api.model
    def _fawtara_endpoints(self):
        """[(environment, base_url, admin_key)] configured in system parameters."""
        icp = self.env['ir.config_parameter'].sudo()
        out = []
        prod_url, prod_key = icp.get_param('fawtara.api_url'), icp.get_param('fawtara.admin_api_key')
        if prod_url and prod_key:
            out.append(('PRODUCTION', prod_url.rstrip('/'), prod_key))
        sb_url, sb_key = icp.get_param('fawtara.sandbox_url'), icp.get_param('fawtara.sandbox_admin_api_key')
        if sb_url and sb_key:
            out.append(('SANDBOX', sb_url.rstrip('/'), sb_key))
        return out

    @api.model
    def action_sync_from_fawtara(self, full=False):
        """Pull invoices from Spring Boot (GET /api/v1/invoice) and upsert them.

        Incremental: uses updatedSince = last Spring updatedAt seen per
        environment (stored in ir.config_parameter) unless `full`.
        """
        icp = self.env['ir.config_parameter'].sudo()
        total, errors = 0, []
        for env_name, base_url, key in self._fawtara_endpoints():
            param = f'fawtara.last_sync_updated_at.{env_name.lower()}'
            since = None if full else icp.get_param(param)
            params = {'updatedSince': since} if since else {}
            try:
                resp = requests.get(f'{base_url}/api/v1/invoice',
                                    headers={'X-API-Key': key},
                                    params=params, timeout=120)
                resp.raise_for_status()
                rows = resp.json()
            except Exception as e:  # noqa: BLE001 — report, don't crash cron
                errors.append(f'{env_name}: {e}')
                _logger.warning('Fawtara sync failed for %s: %s', env_name, e)
                continue

            newest = since
            for row in rows:
                row.setdefault('environment', env_name)
                try:
                    with self.env.cr.savepoint():
                        self.upsert_from_fawtara(row)
                    total += 1
                except Exception as e:  # noqa: BLE001
                    errors.append(f"{row.get('invoiceUuid')}: {e}")
                upd = row.get('updatedAt')
                if upd and (not newest or upd > newest):
                    newest = upd
            if newest:
                icp.set_param(param, newest)

        _logger.info('Fawtara sync — %s invoices upserted, %s errors', total, len(errors))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Fawtara Sync',
                'message': f'{total} invoice(s) synced.'
                           + (f" {len(errors)} error(s): {'; '.join(errors[:3])}" if errors else ''),
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    @api.model
    def _cron_sync_from_fawtara(self):
        self.action_sync_from_fawtara()

    # ── Actions ───────────────────────────────────────────────────

    def _api_for_record(self):
        """(base_url, api_key) matching this invoice's environment."""
        self.ensure_one()
        icp = self.env['ir.config_parameter'].sudo()
        if self.environment == 'SANDBOX':
            return (icp.get_param('fawtara.sandbox_url'),
                    icp.get_param('fawtara.sandbox_admin_api_key')
                    or self.fawtara_client_id.sudo().sandbox_api_key)
        return (icp.get_param('fawtara.api_url'),
                icp.get_param('fawtara.admin_api_key'))

    def action_refresh_status(self):
        self.ensure_one()
        base_url, key = self._api_for_record()
        try:
            resp = requests.get(
                f"{base_url}/api/v1/invoice/{self.invoice_uuid}/summary",
                headers={'X-API-Key': key}, timeout=15)
        except requests.exceptions.RequestException as e:
            raise UserError(f"Cannot reach Fawtara API: {e}")
        if resp.status_code != 200:
            raise UserError(
                f"Status refresh failed: {resp.status_code} — {resp.text}")
        self.upsert_from_fawtara(resp.json())


class FawtaraInvoiceLine(models.Model):
    _name = 'fawtara.invoice.line'
    _description = 'Fawtara Invoice Line (from Spring Boot)'
    _order = 'invoice_id, sequence, id'

    invoice_id = fields.Many2one(
        'fawtara.invoice', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        related='invoice_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    line_ref = fields.Char(string='Line ID')
    item_name = fields.Char(string='Item / Service')
    quantity = fields.Float(digits=(16, 3))
    unit_code = fields.Char(string='Unit')
    unit_price = fields.Float(digits=(16, 3))
    line_total = fields.Float(string='Net Amount', digits=(16, 3))
    vat_category_code = fields.Char(string='VAT Cat.')
    vat_rate = fields.Float(string='VAT %')
    vat_amount = fields.Float(string='VAT', digits=(16, 3))
    service_type_code = fields.Char(string='Service Type')
    isic_code = fields.Char(string='ISIC')
