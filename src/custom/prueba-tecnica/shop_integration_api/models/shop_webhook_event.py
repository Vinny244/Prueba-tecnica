from datetime import timedelta
import json
import logging
import requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ShopWebhookEvent(models.Model):
    _name = "shop.webhook.event"
    _description = "Notificación webhook saliente hacia la tienda"
    _order = "create_date desc, id desc"

    name = fields.Char(string="Evento", required=True, default="order.delivered", readonly=True)
    picking_id = fields.Many2one(
        "stock.picking",
        string="Entrega",
        required=True,
        ondelete="cascade",
        index=True,
        readonly=True,
    )
    order_id = fields.Many2one(
        "sale.order",
        string="Pedido de venta",
        ondelete="set null",
        index=True,
        readonly=True,
    )
    target_url = fields.Char(string="URL destino", required=True, readonly=True)
    payload = fields.Text(string="Payload JSON", required=True, readonly=True)
    state = fields.Selection(
        [
            ("pending", "Pendiente"),
            ("sent", "Enviado"),
            ("failed", "Fallido"),
        ],
        string="Estado",
        default="pending",
        required=True,
        index=True,
    )
    retry_count = fields.Integer(string="Intentos realizados", default=0, readonly=True)
    max_retries = fields.Integer(string="Máximo de intentos", default=5, readonly=True)
    next_retry_at = fields.Datetime(string="Próximo intento", index=True, readonly=True)
    response_code = fields.Integer(string="Código HTTP respuesta", readonly=True)
    last_error = fields.Text(string="Último error", readonly=True)
    sent_at = fields.Datetime(string="Fecha de envío exitoso", readonly=True)

    def _send_single_webhook(self):
        """Intenta enviar el webhook sin propagar excepciones al flujo llamador."""
        self.ensure_one()
        if self.state == "sent":
            return True

        try:
            body_dict = json.loads(self.payload or "{}")
        except ValueError:
            body_dict = {}

        try:
            response = requests.post(
                self.target_url,
                json=body_dict,
                headers={"Content-Type": "application/json", "X-Odoo-Event": self.name},
                timeout=3,
            )
            if 200 <= response.status_code < 300:
                self.write({
                    "state": "sent",
                    "response_code": response.status_code,
                    "sent_at": fields.Datetime.now(),
                    "last_error": False,
                    "next_retry_at": False,
                })
                return True
            error_msg = f"HTTP {response.status_code}: {(response.text or '')[:300]}"
            response_code = response.status_code
        except Exception as exc:
            error_msg = str(exc)
            response_code = 0

        new_retries = self.retry_count + 1
        backoff_minutes = min(60, 2 ** new_retries)
        is_exhausted = new_retries >= self.max_retries
        self.write({
            "retry_count": new_retries,
            "response_code": response_code,
            "last_error": error_msg,
            "state": "failed" if is_exhausted else "pending",
            "next_retry_at": (
                False
                if is_exhausted
                else fields.Datetime.now() + timedelta(minutes=backoff_minutes)
            ),
        })
        _logger.warning(
            "Webhook %s para entrega %s falló (intento %s/%s): %s",
            self.id,
            self.picking_id.name,
            new_retries,
            self.max_retries,
            error_msg,
        )
        return False

    def action_retry_now(self):
        """Permite reintentar manualmente o desde pruebas."""
        for event in self.filtered(lambda e: e.state != "sent"):
            event._send_single_webhook()
        return True

    @api.model
    def _cron_retry_pending_webhooks(self):
        """Reintenta los webhooks pendientes cuya fecha de próximo intento ya venció."""
        now = fields.Datetime.now()
        pending = self.search([
            ("state", "=", "pending"),
            "|",
            ("next_retry_at", "=", False),
            ("next_retry_at", "<=", now),
        ], limit=100)
        for event in pending:
            event._send_single_webhook()
        return True
