from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class PaymentRequestRejectWizard(models.TransientModel):
    _name = "payment.request.reject.wizard"
    _description = "Asistente para rechazar solicitud de pago"

    request_id = fields.Many2one(
        "payment.request",
        string="Solicitud de pago",
        required=True,
        readonly=True,
    )
    reason = fields.Text(string="Motivo del rechazo", required=True)

    @api.constrains("reason")
    def _check_reason_not_empty(self):
        for wiz in self:
            if not (wiz.reason or "").strip():
                raise ValidationError(_("El motivo del rechazo es obligatorio."))

    def action_confirm_reject(self):
        self.ensure_one()
        if not (self.reason or "").strip():
            raise ValidationError(_("El motivo del rechazo es obligatorio."))
        self.request_id._apply_rejection(self.reason)
        return {"type": "ir.actions.act_window_close"}
