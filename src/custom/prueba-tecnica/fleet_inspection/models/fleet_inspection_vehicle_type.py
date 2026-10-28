from odoo import api, fields, models


class FleetInspectionVehicleType(models.Model):
    _name = "fleet.inspection.vehicle.type"
    _description = "Tipo de vehículo para inspección"
    _order = "sequence, id"

    name = fields.Char(string="Nombre", required=True, translate=True)
    code = fields.Char(string="Código", required=True, index=True)
    sequence = fields.Integer(string="Secuencia", default=10)
    active = fields.Boolean(string="Activo", default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "El código del tipo de vehículo debe ser único."),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        existing_records = self.browse()
        new_vals_list = []
        for vals in vals_list:
            code = vals.get("code")
            if code:
                existing = self.search([("code", "=", code)], limit=1)
                if existing:
                    existing.write(vals)
                    existing_records |= existing
                    continue
            new_vals_list.append(vals)
        created = super().create(new_vals_list) if new_vals_list else self.browse()
        return existing_records | created
