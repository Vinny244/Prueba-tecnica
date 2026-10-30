from datetime import timedelta
import psycopg2
from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestEquipmentLoan(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Equipment = cls.env['maintenance.equipment']
        cls.Loan = cls.env['equipment.loan']
        cls.today = fields.Date.context_today(cls.Equipment)

        cls.group_manager = cls.env.ref('equipment_loan.group_equipment_loan_manager')
        cls.group_user = cls.env.ref('base.group_user')
        cls.group_maint_manager = cls.env.ref('maintenance.group_equipment_manager')

        # Equipments creados con permisos de admin
        cls.equipment_a = cls.Equipment.create({
            'name': 'Laptop Dell Test',
        })
        cls.equipment_b = cls.Equipment.create({
            'name': 'Proyector Epson Test',
        })

        # Usuario regular (solo grupo base.group_user)
        cls.user_regular = cls.env['res.users'].create({
            'name': 'Usuario Regular',
            'login': 'user_regular_test',
            'email': 'regular@test.com',
            'groups_id': [(6, 0, [cls.group_user.id])],
        })

        # Usuario gestor (con grupos de préstamo y mantenimiento)
        cls.user_manager = cls.env['res.users'].create({
            'name': 'Gestor de Préstamos',
            'login': 'user_manager_test',
            'email': 'manager@test.com',
            'groups_id': [(6, 0, [cls.group_user.id, cls.group_manager.id, cls.group_maint_manager.id])],
        })

        cls.Loan = cls.Loan.with_user(cls.user_manager)
        cls.Equipment = cls.Equipment.with_user(cls.user_manager)

    def test_01_single_active_loan_rule(self):
        """Un equipo no puede tener dos préstamos activos a la vez (por botón o código)."""
        loan_1 = self.Loan.create({
            'equipment_id': self.equipment_a.id,
            'date_start': self.today,
            'date_due': self.today + timedelta(days=5),
        })
        self.assertEqual(loan_1.state, 'draft')

        # Entregar primer préstamo como gestor
        loan_1.action_loan()
        self.assertEqual(loan_1.state, 'loaned')

        # Intentar entregar un segundo préstamo del mismo equipo vía acción/botón
        loan_2 = self.Loan.create({
            'equipment_id': self.equipment_a.id,
            'date_start': self.today,
            'date_due': self.today + timedelta(days=3),
        })
        with self.assertRaises(ValidationError, msg="No debe permitir entregar con préstamo activo"):
            loan_2.action_loan()

        # Intentar forzar el estado 'loaned' desde código en loan_2 (bloqueado por índice único de BD)
        with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'):
            with self.cr.savepoint():
                loan_2.write({'state': 'loaned'})

        # Intentar crear un préstamo directamente en estado 'loaned' desde código (bloqueado por índice único de BD)
        with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'):
            with self.cr.savepoint():
                self.Loan.create({
                    'equipment_id': self.equipment_a.id,
                    'date_start': self.today,
                    'date_due': self.today + timedelta(days=2),
                    'state': 'loaned',
                })

        # Al devolver el primer préstamo, el segundo sí puede ser entregado
        loan_1.action_return()
        self.assertEqual(loan_1.state, 'returned')
        self.assertIsNotNone(loan_1.date_return)

        loan_2.action_loan()
        self.assertEqual(loan_2.state, 'loaned')

    def test_02_loan_dates_validation(self):
        """Fecha de devolución prevista anterior a entrega debe ser bloqueada."""
        with self.assertRaises(ValidationError):
            self.Loan.create({
                'equipment_id': self.equipment_a.id,
                'date_start': self.today,
                'date_due': self.today - timedelta(days=1),
            })

    def test_03_overdue_computation_and_search(self):
        """Préstamo está vencido si sigue prestado y la fecha prevista ya pasó."""
        yesterday = self.today - timedelta(days=1)
        tomorrow = self.today + timedelta(days=1)

        # 1. Préstamo vencido (fecha prevista ayer y prestado)
        loan_overdue = self.Loan.create({
            'equipment_id': self.equipment_a.id,
            'date_start': yesterday - timedelta(days=2),
            'date_due': yesterday,
        })
        # En draft no está vencido
        self.assertFalse(loan_overdue.is_overdue)
        loan_overdue.action_loan()
        # En loaned con fecha pasada SÍ está vencido
        self.assertTrue(loan_overdue.is_overdue)

        # 2. Préstamo no vencido (fecha prevista mañana y prestado)
        loan_active = self.Loan.create({
            'equipment_id': self.equipment_b.id,
            'date_start': self.today,
            'date_due': tomorrow,
        })
        loan_active.action_loan()
        self.assertFalse(loan_active.is_overdue)

        # 3. Búsqueda dinámica (filtro 'Vencidos')
        overdue_search = self.Loan.search([('is_overdue', '=', True)])
        self.assertIn(loan_overdue, overdue_search)
        self.assertNotIn(loan_active, overdue_search)

        not_overdue_search = self.Loan.search([('is_overdue', '=', False)])
        self.assertNotIn(loan_overdue, not_overdue_search)
        self.assertIn(loan_active, not_overdue_search)

        # Al devolver el préstamo vencido, deja de estar vencido
        loan_overdue.action_return()
        self.assertEqual(loan_overdue.state, 'returned')
        self.assertFalse(loan_overdue.is_overdue)

    def test_04_equipment_smart_button_and_count(self):
        """El smart button del equipo cuenta y abre los préstamos sin N+1 queries."""
        self.assertEqual(self.equipment_a.loan_count, 0)

        loan = self.Loan.create({
            'equipment_id': self.equipment_a.id,
            'date_start': self.today,
            'date_due': self.today + timedelta(days=2),
        })
        self.equipment_a.invalidate_recordset(['loan_count'])
        self.assertEqual(self.equipment_a.loan_count, 1)

        action = self.equipment_a.action_view_loans()
        self.assertEqual(action['res_model'], 'equipment.loan')
        self.assertEqual(action['domain'], [('equipment_id', '=', self.equipment_a.id)])

    def test_05_security_rules_and_access(self):
        """Tramo C: Reglas de registro y permisos por rol.
        - Un usuario regular puede solicitar/crear su propio préstamo.
        - Un usuario sin el grupo no ve préstamos ajenos ni puede entregar, tampoco llamando al método.
        """
        # Usuario regular puede crear su propia solicitud de préstamo
        loan_created_by_user = self.Loan.with_user(self.user_regular).create({
            'equipment_id': self.equipment_a.id,
            'date_start': self.today,
            'date_due': self.today + timedelta(days=2),
        })
        self.assertEqual(loan_created_by_user.user_id, self.user_regular)

        # Crear un préstamo para el usuario regular y otro para el gestor
        loan_user = loan_created_by_user
        loan_manager = self.Loan.create({
            'equipment_id': self.equipment_b.id,
            'user_id': self.user_manager.id,
            'date_start': self.today,
            'date_due': self.today + timedelta(days=2),
        })

        # Como usuario regular: la regla de registro solo debe mostrar sus propios préstamos
        user_loans = self.Loan.with_user(self.user_regular).search([])
        self.assertIn(loan_user, user_loans)
        self.assertNotIn(loan_manager, user_loans)

        # Como usuario regular: no debe poder llamar al método action_loan
        with self.assertRaises(AccessError, msg="Usuario no gestor no debe poder entregar"):
            loan_user.with_user(self.user_regular).action_loan()

        # El gestor sí puede entregar
        loan_user.with_user(self.user_manager).action_loan()
        self.assertEqual(loan_user.state, 'loaned')

        # Como usuario regular: no debe poder llamar al método action_return
        with self.assertRaises(AccessError, msg="Usuario no gestor no debe poder devolver"):
            loan_user.with_user(self.user_regular).action_return()

        # El gestor sí puede devolver
        loan_user.with_user(self.user_manager).action_return()
        self.assertEqual(loan_user.state, 'returned')

    def test_06_database_concurrency_constraint(self):
        """Tramo C: La base de datos previene préstamos activos duplicados mediante índice parcial único."""
        loan_1 = self.Loan.create({
            'equipment_id': self.equipment_a.id,
            'date_start': self.today,
            'date_due': self.today + timedelta(days=3),
        })
        loan_1.action_loan()

        loan_2 = self.Loan.create({
            'equipment_id': self.equipment_a.id,
            'date_start': self.today,
            'date_due': self.today + timedelta(days=4),
        })

        # Simular intento de bypass del ORM directamente con SQL para probar la protección a nivel de BD
        with self.assertRaises(psycopg2.IntegrityError), mute_logger('odoo.sql_db'):
            with self.cr.savepoint():
                self.cr.execute(
                    "UPDATE equipment_loan SET state = 'loaned' WHERE id = %s",
                    [loan_2.id],
                )

    def test_07_cron_daily_overdue_activities(self):
        """Tramo C: La acción planificada crea actividades al gestor y no las duplica si ya existen."""
        yesterday = self.today - timedelta(days=2)
        loan_overdue = self.Loan.create({
            'equipment_id': self.equipment_a.id,
            'date_start': yesterday - timedelta(days=2),
            'date_due': yesterday,
        })
        loan_overdue.action_loan()

        # Primera ejecución del cron: debe crear la actividad
        self.Loan.cron_check_overdue_loans()

        todo_type = self.env.ref('mail.mail_activity_data_todo')
        activities = self.env['mail.activity'].search([
            ('res_model', '=', 'equipment.loan'),
            ('res_id', '=', loan_overdue.id),
            ('activity_type_id', '=', todo_type.id),
        ])
        self.assertTrue(len(activities) >= 1, "Debe haber creado al menos una actividad")
        initial_count = len(activities)

        # Segunda ejecución consecutiva del cron: NO debe duplicar actividades
        self.Loan.cron_check_overdue_loans()
        activities_second_run = self.env['mail.activity'].search([
            ('res_model', '=', 'equipment.loan'),
            ('res_id', '=', loan_overdue.id),
            ('activity_type_id', '=', todo_type.id),
        ])
        self.assertEqual(len(activities_second_run), initial_count, "Correr el cron 2 veces no debe duplicar actividades")
