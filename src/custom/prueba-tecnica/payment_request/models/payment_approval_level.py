# -*- coding: utf-8 -*-
# Resolución Ejercicio 4

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PaymentApprovalLevel(models.Model):
    _name = "payment.approval.level"
    _description = "Nivel de aprobación de solicitudes de pago"
    _order = "min_amount desc, id desc"
    _check_company_auto = True

    name = fields.Char(string="Nivel", required=True)
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        related="company_id.currency_id",
        string="Moneda base",
        store=True,
        readonly=True,
    )
    min_amount = fields.Monetary(
        string="Monto mínimo",
        currency_field="currency_id",
        required=True,
        default=0.0,
        help="Monto mínimo (expresado en la moneda de la compañía) a partir del cual aplica este aprobador.",
    )
    approver_id = fields.Many2one(
        "res.users",
        string="Aprobador",
        required=True,
        check_company=True,
    )
    active = fields.Boolean(string="Activo", default=True)

    @api.constrains("min_amount")
    def _check_min_amount(self):
        for level in self:
            if level.min_amount < 0:
                raise ValidationError(_("El monto mínimo del nivel de aprobación no puede ser negativo."))
