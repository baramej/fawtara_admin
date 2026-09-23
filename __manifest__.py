# Result Client
# 3b2d574c-6cc9-4f20-a4b2-8808c7681c55
# Production API Key
# fwt_live_CGGXQP6aJzWO5_Kz6HwQJ54Ls3WgQyaa
# Sandbox API Key
# fwt_test_m2ewTo58B-ISbZEnW3iQhfT6HKB1rX0A

{
    'name': 'Fawtara Admin Portal',
    'version': '19.0.1.1.0',
    'summary': 'Baramej internal portal for managing Fawtara e-invoicing clients',
    'author': 'Baramej Business and Digital Technology Center LLC',
    'category': 'Accounting',
    'depends': ['base', 'mail'],
    'data': [
        'security/fawtara_security.xml',
        'security/ir.model.access.csv',
        'data/fawtara_config.xml',
        'views/fawtara_billing_views.xml',
        'views/fawtara_client_views.xml',
        'views/fawtara_invoice_views.xml',
        'views/fawtara_dashboard_views.xml',
        'views/fawtara_dashboard_client_action.xml',
        'views/menu_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'fawtara_admin/static/src/js/fawtara_dashboard.js',
            'fawtara_admin/static/src/css/fawtara_dashboard.css',
            'fawtara_admin/static/src/xml/fawtara_dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
