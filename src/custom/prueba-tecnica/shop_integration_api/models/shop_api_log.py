from odoo import fields, models


class ShopApiLog(models.Model):
    _name = "shop.api.log"
    _description = "Registro de llamadas de la API de tienda"
    _order = "create_date desc, id desc"

    endpoint = fields.Char(string="Endpoint", required=True, readonly=True, index=True)
    http_method = fields.Char(string="Método HTTP", required=True, readonly=True)
    user_id = fields.Many2one(
        "res.users",
        string="Usuario",
        readonly=True,
        ondelete="set null",
        index=True,
    )
    status_code = fields.Integer(string="Código de respuesta", required=True, readonly=True)
    duration_ms = fields.Float(
        string="Duración (ms)",
        digits=(12, 2),
        required=True,
        readonly=True,
    )
    error_code = fields.Char(string="Código de error", readonly=True)
    request_date = fields.Datetime(
        string="Fecha de solicitud",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )
