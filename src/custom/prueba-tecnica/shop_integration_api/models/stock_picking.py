# -*- coding: utf-8 -*-
# Resolución Ejercicio 1

import json

from odoo import fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def button_validate(self):
        res = super().button_validate()
        self._notify_shop_delivery_validated()
        return res

    def _notify_shop_delivery_validated(self):
        """Genera y envía el webhook cuando se valida la entrega de un pedido de venta."""
        webhook_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("shop_integration_api.webhook_url", default="http://localhost:9999/webhook/delivery")
        )
        if not webhook_url:
            return

        WebhookEvent = self.env["shop.webhook.event"].sudo()
        for picking in self:
            if picking.picking_type_code != "outgoing" or picking.state != "done":
                continue
            order = picking.sale_id
            if not order:
                continue

            delivered_lines = []
            for move in picking.move_ids.filtered(lambda m: m.state == "done"):
                qty_done = getattr(move, "quantity", 0.0) or getattr(move, "quantity_done", 0.0) or move.product_uom_qty
                delivered_lines.append({
                    "default_code": move.product_id.default_code or "",
                    "product_id": move.product_id.id,
                    "quantity_delivered": qty_done,
                })

            payload = {
                "event": "order.delivered",
                "order_id": order.id,
                "order_name": order.name,
                "external_reference": order.client_order_ref or "",
                "picking_id": picking.id,
                "picking_name": picking.name,
                "delivered_at": fields.Datetime.to_string(picking.date_done or fields.Datetime.now()),
                "lines": delivered_lines,
            }
            WebhookEvent.create({
                "name": "order.delivered",
                "picking_id": picking.id,
                "order_id": order.id,
                "target_url": webhook_url,
                "payload": json.dumps(payload, ensure_ascii=False),
                "state": "pending",
                "next_retry_at": fields.Datetime.now(),
            })
        # Disparar el cron de forma asíncrona sin bloquear la transacción del almacenero
        cron = self.env.ref(
            "shop_integration_api.ir_cron_process_shop_webhooks",
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()
