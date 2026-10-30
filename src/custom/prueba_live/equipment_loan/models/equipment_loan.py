from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError


class EquipmentLoan(models.Model):
    _name = 'equipment.loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Equipment Loan'
    _order = 'id desc'

    name = fields.Char(
        string='Referencia',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nuevo'),
        tracking=True,
    )
    equipment_id = fields.Many2one(
        comodel_name='maintenance.equipment',
        string='Equipo',
        required=True,
        ondelete='restrict',
        tracking=True,
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Persona que lo recibe',
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    date_start = fields.Date(
        string='Fecha de entrega',
        default=fields.Date.context_today,
        required=True,
        tracking=True,
    )
    date_due = fields.Date(
        string='Fecha prevista de devolución',
        required=True,
        tracking=True,
    )
    date_return = fields.Date(
        string='Fecha real de devolución',
        readonly=True,
        copy=False,
        tracking=True,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('loaned', 'Prestado'),
            ('returned', 'Devuelto'),
        ],
        string='Estado',
        default='draft',
        required=True,
        copy=False,
        tracking=True,
    )
    is_overdue = fields.Boolean(
        string='Vencido',
        compute='_compute_is_overdue',
        search='_search_is_overdue',
    )

    def init(self):
        super().init()
        # Garantía a nivel de Base de Datos para evitar condiciones de carrera en concurrencia
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS equipment_loan_unique_active_equipment
            ON equipment_loan (equipment_id)
            WHERE state = 'loaned';
        """)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals['name'] == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('equipment.loan') or _('Nuevo')
        return super().create(vals_list)

    @api.constrains('date_start', 'date_due')
    def _check_dates(self):
        for record in self:
            if record.date_start and record.date_due and record.date_due < record.date_start:
                raise ValidationError(
                    _("La fecha prevista de devolución no puede ser anterior a la fecha de entrega.")
                )

    @api.constrains('equipment_id', 'state')
    def _check_unique_active_loan(self):
        for record in self:
            if record.state == 'loaned':
                overlapping = self.search([
                    ('equipment_id', '=', record.equipment_id.id),
                    ('state', '=', 'loaned'),
                    ('id', '!=', record.id),
                ])
                if overlapping:
                    raise ValidationError(
                        _("El equipo '%s' ya tiene un préstamo activo en curso (%s). "
                          "Un equipo no puede tener dos préstamos activos a la vez.")
                        % (record.equipment_id.display_name, overlapping[0].name)
                    )

    @api.depends('state', 'date_due')
    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for record in self:
            record.is_overdue = (
                record.state == 'loaned'
                and bool(record.date_due)
                and record.date_due < today
            )

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!='):
            raise NotImplementedError(_("Operador '%s' no soportado para campo vencido.") % operator)
        today = fields.Date.context_today(self)
        match_overdue = (operator == '=' and bool(value)) or (operator == '!=' and not bool(value))
        if match_overdue:
            return [('state', '=', 'loaned'), ('date_due', '<', today)]
        else:
            return ['|', ('state', '!=', 'loaned'), ('date_due', '>=', today)]

    def action_loan(self):
        if not self.env.user.has_group('equipment_loan.group_equipment_loan_manager'):
            raise AccessError(_("Solo los usuarios con el rol 'Gestor de préstamos' pueden realizar la entrega de equipos."))

        for record in self:
            if record.state != 'draft':
                raise ValidationError(_("Solo se pueden entregar préstamos en estado borrador."))

            # Bloqueo pesimista a nivel de fila en Postgres para serializar entregas concurrentes del mismo equipo
            self.env.cr.execute(
                "SELECT id FROM maintenance_equipment WHERE id = %s FOR UPDATE",
                [record.equipment_id.id],
            )

            active_loan = self.search([
                ('equipment_id', '=', record.equipment_id.id),
                ('state', '=', 'loaned'),
                ('id', '!=', record.id),
            ], limit=1)
            if active_loan:
                raise ValidationError(
                    _("No se puede entregar el equipo '%s' porque ya tiene un préstamo activo (%s).")
                    % (record.equipment_id.display_name, active_loan.name)
                )
            record.state = 'loaned'

    def action_return(self):
        if not self.env.user.has_group('equipment_loan.group_equipment_loan_manager'):
            raise AccessError(_("Solo los usuarios con el rol 'Gestor de préstamos' pueden registrar la devolución de equipos."))

        for record in self:
            if record.state != 'loaned':
                raise ValidationError(_("Solo se pueden devolver préstamos en estado prestado."))
            record.write({
                'state': 'returned',
                'date_return': fields.Date.context_today(record),
            })

    @api.model
    def cron_check_overdue_loans(self):
        overdue_loans = self.search([('is_overdue', '=', True)])
        manager_group = self.env.ref('equipment_loan.group_equipment_loan_manager')
        managers = manager_group.users
        if not managers:
            managers = self.env.ref('base.user_admin')

        todo_type = self.env.ref('mail.mail_activity_data_todo')

        for loan in overdue_loans:
            for manager in managers:
                existing_activity = self.env['mail.activity'].search([
                    ('res_model', '=', 'equipment.loan'),
                    ('res_id', '=', loan.id),
                    ('activity_type_id', '=', todo_type.id),
                    ('user_id', '=', manager.id),
                ], limit=1)

                if not existing_activity:
                    loan.activity_schedule(
                        activity_type_id=todo_type.id,
                        user_id=manager.id,
                        summary=_("Préstamo vencido: %s") % loan.name,
                        note=_("El equipo '%s' prestado a %s debió devolverse el %s.") % (
                            loan.equipment_id.display_name,
                            loan.user_id.name,
                            loan.date_due,
                        ),
                    )
