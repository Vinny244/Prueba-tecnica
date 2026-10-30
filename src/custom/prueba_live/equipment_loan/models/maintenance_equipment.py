from odoo import api, fields, models, _


class MaintenanceEquipment(models.Model):
    _inherit = 'maintenance.equipment'

    loan_ids = fields.One2many(
        comodel_name='equipment.loan',
        inverse_name='equipment_id',
        string='Préstamos',
    )
    loan_count = fields.Integer(
        string='Cantidad de préstamos',
        compute='_compute_loan_count',
    )

    def _compute_loan_count(self):
        loan_data = self.env['equipment.loan']._read_group(
            domain=[('equipment_id', 'in', self.ids)],
            groupby=['equipment_id'],
            aggregates=['__count'],
        )
        loan_count_map = {equipment.id: count for equipment, count in loan_data}
        for record in self:
            record.loan_count = loan_count_map.get(record.id, 0)

    def action_view_loans(self):
        self.ensure_one()
        return {
            'name': _('Préstamos del Equipo'),
            'type': 'ir.actions.act_window',
            'res_model': 'equipment.loan',
            'view_mode': 'list,form',
            'domain': [('equipment_id', '=', self.id)],
            'context': {'default_equipment_id': self.id},
        }
