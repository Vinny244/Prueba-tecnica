# -*- coding: utf-8 -*-
# Resolución Ejercicio 4

from odoo import fields, models


class PaymentRequestPayWizard(models.TransientModel):
    _name = "payment.request.pay.wizard"
    _description = "Asistente para registrar pago de solicitud"

    request_id = fields.Many2one(
        "payment.request",
        string="Solicitud de pago",
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        related="request_id.company_id",
        readonly=True,
    )
    journal_id = fields.Many2one(
        "account.journal",
        string="Diario de pago",
        required=True,
        domain="[('type', 'in', ('bank', 'cash')), ('company_id', '=', company_id)]",
    )
    payment_date = fields.Date(
        string="Fecha de pago",
        required=True,
        default=fields.Date.context_today,
    )

    def action_confirm_pay(self):
        self.ensure_one()
        self.request_id._register_supplier_payment(
            journal=self.journal_id,
            payment_date=self.payment_date,
        )
        return {"type": "ir.actions.act_window_close"}
