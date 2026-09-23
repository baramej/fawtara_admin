{
    'name': 'Fawtara Admin Portal',
    'version': '1.0.0',
    'summary': 'Baramej internal portal for managing Fawtara e-invoicing clients',
    'author': 'Baramej Business and Digital Technology Center LLC',
    'category': 'Accounting',
    'depends': ['base', 'mail'],
    'data': [
        'security/ir.model.access.csv',
        'data/fawtara_config.xml',
        'views/fawtara_billing_views.xml',
        'views/fawtara_dashboard_views.xml',
        'views/fawtara_dashboard_client_action.xml',
        'views/fawtara_client_views.xml',
        'views/fawtara_invoice_views.xml',
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
