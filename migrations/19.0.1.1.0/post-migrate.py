"""Link existing ledger rows to their fawtara.client (by Spring clientId,
falling back to seller VATIN for invoices sent with the admin key)."""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    Client = env['fawtara.client']
    invoices = env['fawtara.invoice'].search([('fawtara_client_id', '=', False)])
    for inv in invoices:
        client = Client._resolve_from_fawtara(inv.client_id, inv.seller_vatin)
        if client:
            inv.fawtara_client_id = client
    # Before this version only the portal form ever created ledger rows
    cr.execute("SELECT to_regclass('fawtara_portal_invoice')")
    if cr.fetchone()[0]:
        cr.execute("""
            UPDATE fawtara_invoice SET source = 'PORTAL'
             WHERE invoice_uuid IN (SELECT invoice_uuid FROM fawtara_portal_invoice
                                     WHERE invoice_uuid IS NOT NULL)
        """)
