from odoo import fields, models


class ShopApiIdempotency(models.Model):
    _name = "shop.api.idempotency"
    _description = "Clave de idempotencia de la API de tienda"
    _order = "create_date desc, id desc"

    key = fields.Char(string="Idempotency-Key", required=True, index=True, readonly=True)
    endpoint = fields.Char(string="Endpoint", required=True, readonly=True)
    request_hash = fields.Char(string="Hash SHA-256 del contenido", required=True, readonly=True)
    order_id = fields.Many2one(
        "sale.order",
        string="Pedido creado",
        ondelete="cascade",
        readonly=True,
    )
    response_status = fields.Integer(string="Código HTTP", required=True, readonly=True)
    response_body = fields.Text(string="Respuesta JSON", required=True, readonly=True)

    _sql_constraints = [
        (
            "key_endpoint_uniq",
            "unique(key, endpoint)",
            "La clave de idempotencia debe ser única por endpoint.",
        ),
    ]
