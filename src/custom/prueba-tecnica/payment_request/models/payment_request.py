# -*- coding: utf-8 -*-
# Resolución Ejercicio 4

from psycopg2 import OperationalError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError

LOCKED_BUSINESS_FIELDS = {
    "partner_id",
    "requester_id",
    "amount",
    "currency_id",
    "date",
    "concept",
    "company_id",
}


class PaymentRequest(models.Model):
    _name = "payment.request"
    _description = "Solicitud de pago a proveedor"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "date desc, id desc"
    _check_company_auto = True

    name = fields.Char(
        string="Número",
        required=True,
        copy=False,
        readonly=True,
        default="/",
        tracking=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Proveedor",
        required=True,
        tracking=True,
    )
    requester_id = fields.Many2one(
        "res.users",
        string="Solicitante",
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        "res.company",
        string="Compañía",
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        "res.currency",
        string="Moneda",
        required=True,
        default=lambda self: self.env.company.currency_id,
        tracking=True,
    )
    amount = fields.Monetary(
        string="Monto",
        currency_field="currency_id",
        required=True,
        tracking=True,
    )
    date = fields.Date(
        string="Fecha",
        required=True,
        default=fields.Date.context_today,
        tracking=True,
    )
    concept = fields.Text(
        string="Concepto",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Borrador"),
            ("submitted", "Enviada"),
            ("approved", "Aprobada"),
            ("paid", "Pagada"),
            ("rejected", "Rechazada"),
        ],
        string="Estado",
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )
    approval_level_id = fields.Many2one(
        "payment.approval.level",
        string="Nivel de aprobación",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approver_id = fields.Many2one(
        "res.users",
        string="Aprobador asignado",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approved_by_id = fields.Many2one(
        "res.users",
        string="Aprobado por",
        readonly=True,
        copy=False,
        tracking=True,
    )
    approved_date = fields.Datetime(
        string="Fecha de aprobación",
        readonly=True,
        copy=False,
        tracking=True,
    )
    rejection_reason = fields.Text(
        string="Motivo de rechazo",
        readonly=True,
        copy=False,
        tracking=True,
    )
    payment_id = fields.Many2one(
        "account.payment",
        string="Pago contable",
        readonly=True,
        copy=False,
        tracking=True,
    )
    payment_currency_id = fields.Many2one(
        "res.currency",
        related="payment_id.currency_id",
        string="Moneda del pago",
        readonly=True,
    )
    payment_amount = fields.Monetary(
        related="payment_id.amount",
        currency_field="payment_currency_id",
        string="Monto pagado",
        readonly=True,
    )

    _sql_constraints = [
        ("amount_positive", "CHECK(amount > 0)", "El monto de la solicitud debe ser mayor que cero."),
    ]

    @api.constrains("amount")
    def _check_amount_positive(self):
        for rec in self:
            if rec.amount <= 0:
                raise ValidationError(_("El monto de la solicitud debe ser mayor que cero."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if "amount" in vals and vals["amount"] <= 0:
                raise ValidationError(_("El monto de la solicitud debe ser mayor que cero."))
            if vals.get("name", "/") == "/":
                vals["name"] = self.env["ir.sequence"].next_by_code("payment.request") or "/"
        return super().create(vals_list)

    def write(self, vals):
        if LOCKED_BUSINESS_FIELDS.intersection(vals.keys()):
            if any(rec.state != "draft" for rec in self):
                raise UserError(
                    _("No se puede modificar una solicitud de pago una vez que ha sido enviada.")
                )
        return super().write(vals)

    def unlink(self):
        if any(rec.state != "draft" for rec in self):
            raise UserError(_("Solo se pueden eliminar solicitudes de pago en estado borrador."))
        return super().unlink()

    def _lock_rows_for_update(self):
        """Adquiere un bloqueo pesimista (FOR UPDATE NOWAIT) en PostgreSQL sobre las solicitudes."""
        if not self.ids:
            return
        self.env.flush_all()
        try:
            self.env.cr.execute(
                "SELECT id, state FROM payment_request WHERE id IN %s FOR UPDATE NOWAIT",
                (tuple(self.ids),),
            )
        except OperationalError as exc:
            raise UserError(
                _("La solicitud está siendo procesada por otro usuario en este mismo instante.")
            ) from exc
        self.env.invalidate_all()

    def _find_matching_approval_level(self):
        """Determina el nivel de aprobación aplicable según el monto en la moneda de la compañía."""
        self.ensure_one()
        company_currency = self.company_id.currency_id
        amount_in_company_curr = self.currency_id._convert(
            self.amount,
            company_currency,
            self.company_id,
            self.date or fields.Date.context_today(self),
        )
        levels = (
            self.env["payment.approval.level"]
            .sudo()
            .search(
                [
                    ("company_id", "=", self.company_id.id),
                    ("min_amount", "<=", amount_in_company_curr),
                    ("active", "=", True),
                ],
                order="min_amount desc, id desc",
                limit=1,
            )
        )
        return levels[:1]

    def action_submit(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Solo se pueden enviar solicitudes en estado borrador."))
            if rec.amount <= 0:
                raise ValidationError(_("El monto de la solicitud debe ser mayor que cero."))

            level = rec._find_matching_approval_level()
            if not level or not level.approver_id:
                raise UserError(
                    _(
                        "No existe un nivel de aprobación configurado con aprobador para el monto de la solicitud (%s %s)."
                    )
                    % (rec.amount, rec.currency_id.name)
                )
            update_vals = {
                "state": "submitted",
                "approval_level_id": level.id,
                "approver_id": level.approver_id.id,
            }
            super(PaymentRequest, rec).write(update_vals)
            rec.activity_schedule(
                "mail.mail_activity_data_todo",
                user_id=level.approver_id.id,
                summary=_("Aprobar solicitud de pago %s") % rec.name,
                note=_(
                    "Solicitud de pago para %s por %s %s (%s)."
                )
                % (rec.partner_id.name, rec.amount, rec.currency_id.name, rec.concept),
            )
        return True

    def action_approve(self):
        if not self.env.user.has_group("payment_request.group_payment_request_approver"):
            raise AccessError(_("Solo un usuario del grupo Aprobador puede aprobar solicitudes de pago."))

        self._lock_rows_for_update()

        now = fields.Datetime.now()
        for rec in self:
            if rec.state != "submitted":
                raise UserError(_("La solicitud %s ya fue procesada o no está en estado enviada.") % rec.name)
            if rec.requester_id == self.env.user and not self.env.is_superuser():
                raise AccessError(_("El solicitante no puede aprobar su propia solicitud de pago."))
            if rec.approver_id and rec.approver_id != self.env.user:
                raise AccessError(
                    _("Solo el aprobador asignado (%s) puede aprobar esta solicitud.")
                    % rec.approver_id.name
                )
            super(PaymentRequest, rec).write({
                "state": "approved",
                "approved_by_id": self.env.user.id,
                "approved_date": now,
            })
            todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
            activities = rec.activity_ids.filtered(
                lambda a: (not todo_type or a.activity_type_id == todo_type)
                and (not rec.approver_id or a.user_id == rec.approver_id)
            )
            activities.sudo().action_done()
        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group("payment_request.group_payment_request_approver"):
            raise AccessError(_("Solo un usuario del grupo Aprobador puede rechazar solicitudes de pago."))
        if self.state != "submitted":
            raise UserError(_("Solo se pueden rechazar solicitudes en estado enviada."))
        return {
            "name": _("Rechazar solicitud de pago"),
            "type": "ir.actions.act_window",
            "res_model": "payment.request.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_request_id": self.id},
        }

    def _apply_rejection(self, reason):
        self.ensure_one()
        if not self.env.user.has_group("payment_request.group_payment_request_approver"):
            raise AccessError(_("Solo un usuario del grupo Aprobador puede rechazar solicitudes de pago."))
        reason = (reason or "").strip()
        if not reason:
            raise ValidationError(_("Debe indicar el motivo del rechazo."))

        self._lock_rows_for_update()
        if self.state != "submitted":
            raise UserError(_("Solo se pueden rechazar solicitudes en estado enviada."))
        if self.approver_id and self.approver_id != self.env.user:
            raise AccessError(
                _("Solo el aprobador asignado (%s) puede rechazar esta solicitud.")
                % self.approver_id.name
            )

        super(PaymentRequest, self).write({
            "state": "rejected",
            "rejection_reason": reason,
        })
        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        activities = self.activity_ids.filtered(
            lambda a: (not todo_type or a.activity_type_id == todo_type)
            and (not self.approver_id or a.user_id == self.approver_id)
        )
        activities.sudo().action_done()
        self.message_post(
            body=_("Solicitud rechazada por %s. Motivo: %s") % (self.env.user.name, reason),
            subtype_xmlid="mail.mt_comment",
        )
        return True

    def action_open_pay_wizard(self):
        self.ensure_one()
        if not self.env.user.has_group("payment_request.group_payment_request_treasury"):
            raise AccessError(_("Solo el equipo de Tesorería puede registrar el pago."))
        if self.state != "approved":
            raise UserError(_("Solo se pueden pagar solicitudes en estado aprobada."))
        if self.payment_id:
            raise UserError(_("Esta solicitud ya tiene un pago registrado."))
        return {
            "name": _("Registrar pago de solicitud"),
            "type": "ir.actions.act_window",
            "res_model": "payment.request.pay.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_request_id": self.id,
                "default_payment_date": fields.Date.context_today(self),
            },
        }

    def _register_supplier_payment(self, journal, payment_date=None):
        """Crea el account.payment de proveedor dentro de un bloqueo de fila y savepoint atómico."""
        self.ensure_one()
        if not self.env.user.has_group("payment_request.group_payment_request_treasury"):
            raise AccessError(_("Solo el equipo de Tesorería puede registrar el pago de la solicitud."))

        self._lock_rows_for_update()

        if self.state == "paid" or self.payment_id:
            raise UserError(_("La solicitud %s ya fue pagada y no puede pagarse dos veces.") % self.name)
        if self.state != "approved":
            raise UserError(_("Solo se pueden pagar solicitudes en estado aprobada."))

        payment_date = payment_date or fields.Date.context_today(self)
        target_currency = journal.currency_id or self.company_id.currency_id

        if self.currency_id != target_currency:
            payment_amount = self.currency_id._convert(
                self.amount,
                target_currency,
                self.company_id,
                payment_date,
            )
        else:
            payment_amount = self.amount

        with self.env.cr.savepoint():
            payment_vals = {
                "payment_type": "outbound",
                "partner_type": "supplier",
                "partner_id": self.partner_id.id,
                "amount": payment_amount,
                "currency_id": target_currency.id,
                "date": payment_date,
                "journal_id": journal.id,
                "company_id": self.company_id.id,
            }
            Payment = self.env["account.payment"]
            if "memo" in Payment._fields:
                payment_vals["memo"] = f"{self.name} - {self.concept}"
            elif "ref" in Payment._fields:
                payment_vals["ref"] = f"{self.name} - {self.concept}"

            payment = Payment.create(payment_vals)
            if hasattr(payment, "action_post"):
                payment.action_post()

            super(PaymentRequest, self).write({
                "state": "paid",
                "payment_id": payment.id,
            })

        self.message_post(
            body=_("Pago registrado en %s por %s %s (Pago: %s).")
            % (journal.name, payment_amount, target_currency.name, payment.name),
            subtype_xmlid="mail.mt_note",
        )
        return payment

    def action_view_payment(self):
        self.ensure_one()
        if not self.payment_id:
            return False
        return {
            "name": _("Pago de proveedor"),
            "type": "ir.actions.act_window",
            "res_model": "account.payment",
            "res_id": self.payment_id.id,
            "view_mode": "form",
        }
