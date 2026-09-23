"""Before the UNIQUE(invoice_uuid) constraint is added: drop duplicate
ledger rows (keep the newest one per UUID)."""


def migrate(cr, version):
    cr.execute("""
        DELETE FROM fawtara_invoice a
         USING fawtara_invoice b
         WHERE a.invoice_uuid IS NOT NULL
           AND a.invoice_uuid = b.invoice_uuid
           AND a.id < b.id
    """)
