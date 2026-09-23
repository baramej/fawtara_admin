import requests
import logging
from odoo import models, fields, api
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OnboardClientWizard(models.TransientModel):
    _name = 'fawtara.onboard.wizard'
    _description = 'Onboard New Fawtara Client'

    # ── Fields ────────────────────────────────────────────────────
    company_name = fields.Char(
        string='Company Name (EN)', required=True)
    company_name_ar = fields.Char(
        string='Company Name (AR)')
    cr_number = fields.Char(
        string='CR Number', required=True)
    vatin = fields.Char(
        string='VAT Number', required=True,
        help='Format: OM + 10 digits e.g. OM1112345678')
    contact_name = fields.Char(
        string='Contact Person', required=True)
    contact_email = fields.Char(
        string='Contact Email', required=True)
    contact_phone = fields.Char(string='Contact Phone')
    notes = fields.Text(string='Notes')
    company_id = fields.Many2one(
        'res.company', string='Odoo Company',
        help='Company the client\'s users will log into. '
             'Leave empty to create one from the details above.')
    register_smp = fields.Boolean(
        string='Register on Peppol SMP immediately',
        default=True)
    send_welcome_email = fields.Boolean(
        string='Send welcome email to client',
        default=True)

    # ── Result (shown after creation) ─────────────────────────────
    result_client_id = fields.Char(readonly=True)
    result_prod_key = fields.Char(
        string='Production API Key', readonly=True)
    result_sandbox_key = fields.Char(
        string='Sandbox API Key', readonly=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], default='draft')

    @api.constrains('vatin')
    def _check_vatin(self):
        for rec in self:
            if rec.vatin and (
                not rec.vatin.startswith('OM')
                or len(rec.vatin) != 12
            ):
                raise UserError(
                    "VATIN must be OM followed by exactly 10 digits "
                    "(e.g. OM1112345678)")

    def action_onboard(self):
        """Create client in Spring Boot and save record in Odoo."""
        self.ensure_one()
        config = self.env['ir.config_parameter'].sudo()
        base_url = config.get_param('fawtara.api_url')
        admin_key = config.get_param('fawtara.admin_api_key')

        if not base_url or not admin_key:
            raise UserError(
                "Fawtara API URL and Admin Key not configured. "
                "Go to Settings → Technical → System Parameters.")

        # Call Spring Boot to create client
        try:
            resp = requests.post(
                f"{base_url}/api/v1/clients",
                headers={
                    'X-API-Key': admin_key,
                    'Content-Type': 'application/json',
                },
                json={
                    'companyName':   self.company_name,
                    'companyNameAr': self.company_name_ar or '',
                    'crNumber':      self.cr_number,
                    'vatin':         self.vatin,
                    'contactName':   self.contact_name,
                    'contactEmail':  self.contact_email,
                    'contactPhone':  self.contact_phone or '',
                },
                timeout=30
            )

            if resp.status_code not in (200, 201):
                raise UserError(
                    f"Spring Boot returned error {resp.status_code}: "
                    f"{resp.text}")

            data = resp.json()

        except requests.exceptions.RequestException as e:
            raise UserError(f"Cannot reach Fawtara API: {str(e)}")

        # Odoo company the client's users work in (drives record rules)
        omr = self.env.ref('base.OMR')
        if not omr.active:
            omr.sudo().active = True
        company = self.company_id or self.env['res.company'].sudo().create({
            'name': self.company_name,
            'vat': self.vatin,
            'company_registry': self.cr_number,
            'email': self.contact_email,
            'phone': self.contact_phone or False,
            'country_id': self.env.ref('base.om').id,
            'currency_id': omr.id,
        })

        # Save in Odoo
        client_rec = self.env['fawtara.client'].create({
            'company_id':         company.id,
            'name':               self.company_name,
            'name_ar':            self.company_name_ar,
            'cr_number':          self.cr_number,
            'vatin':              self.vatin,
            'contact_name':       self.contact_name,
            'contact_email':      self.contact_email,
            'contact_phone':      self.contact_phone,
            'notes':              self.notes,
            'client_id':          data['clientId'],
            'participant_id':     data['participantId'],
            'production_api_key': data['productionApiKey'],
            'sandbox_api_key':    data['sandboxApiKey'],
            'status':             'ACTIVE',
        })

        _logger.info(
            "Client onboarded — clientId: %s, vatin: %s",
            data['clientId'], self.vatin)

        # Register on SMP if requested
        if self.register_smp:
            try:
                client_rec.action_register_smp()
            except Exception as e:
                _logger.warning(
                    "SMP registration failed after onboarding: %s", e)

        # Send welcome email if requested
        if self.send_welcome_email:
            self._send_welcome_email(client_rec, data)

        # Update wizard state to show result
        self.write({
            'state':              'done',
            'result_client_id':   data['clientId'],
            'result_prod_key':    data['productionApiKey'],
            'result_sandbox_key': data['sandboxApiKey'],
        })

        # Stay open to show the keys
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'fawtara.onboard.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _send_welcome_email(self, client_rec, api_data):
        """Send welcome email with API credentials."""
        config = self.env['ir.config_parameter'].sudo()
        api_docs_url = config.get_param(
            'fawtara.docs_url',
            'https://docs.fawtara.baramej.om')
        sandbox_url = config.get_param(
            'fawtara.sandbox_url',
            'https://sandbox.fawtara.baramej.om')
        prod_url = config.get_param(
            'fawtara.api_url',
            'https://fawtara.baramej.om')

        subject = f"Welcome to Fawtara E-Invoicing — Your API Credentials"
        body = f"""
<p>Dear {client_rec.contact_name},</p>
<p>Welcome to <strong>Fawtara</strong>, Baramej's e-invoicing Access Point
for Oman's OTA Peppol network.</p>
<p>Your account has been created and is ready to use.</p>

<h3>Your Credentials</h3>
<table border="1" cellpadding="6" cellspacing="0">
<tr><td><strong>Company</strong></td><td>{client_rec.name}</td></tr>
<tr><td><strong>VAT Number</strong></td><td>{client_rec.vatin}</td></tr>
<tr><td><strong>Peppol ID</strong></td><td>{client_rec.participant_id}</td></tr>
<tr><td><strong>Production API Key</strong></td>
    <td><code>{api_data['productionApiKey']}</code></td></tr>
<tr><td><strong>Sandbox API Key</strong></td>
    <td><code>{api_data['sandboxApiKey']}</code></td></tr>
</table>

<h3>API Endpoints</h3>
<ul>
<li><strong>Production:</strong> {prod_url}/api/v1/invoice</li>
<li><strong>Sandbox:</strong> {sandbox_url}/api/v1/invoice</li>
<li><strong>Documentation:</strong> {api_docs_url}</li>
</ul>

<p><strong>Important:</strong> Please save your API keys securely.
They will not be shown again.</p>
<p>For support, contact: support@baramej.om</p>
<p>Best regards,<br/>Baramej Technology Team</p>
        """

        mail = self.env['mail.mail'].create({
            'subject': subject,
            'body_html': body,
            'email_to': client_rec.contact_email,
            'email_from': 'noreply@baramej.om',
        })
        mail.send()
        _logger.info(
            "Welcome email sent to %s", client_rec.contact_email)

    def action_close(self):
        return {'type': 'ir.actions.act_window_close'}