{
    "name": "Integración con API para tienda en línea",
    "summary": "Endpoints REST para consulta de productos con stock y creación de pedidos de venta",
    "version": "18.0.1.0.0",
    "category": "Sales/Sales",
    "author": "Binaural",
    "license": "LGPL-3",
    "depends": ["sale_management", "stock"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/shop_api_log_views.xml",
    ],
    "installable": True,
    "application": False,
}
