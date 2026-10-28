from datetime import timedelta
import importlib.util
from pathlib import Path

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import Form, TransactionCase, tagged


def _load_migration_module(filename):
    mig_path = (
        Path(__file__).resolve().parent.parent
        / "migrations"
        / "18.0.2.0.0"
        / filename
    )
    spec = importlib.util.spec_from_file_location(f"fleet_mig_{filename}", mig_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@tagged("post_install", "-at_install")
class TestFleetInspection(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        brand = cls.env["fleet.vehicle.model.brand"].create({"name": "Marca de prueba"})
        model = cls.env["fleet.vehicle.model"].create({"name": "Modelo de prueba", "brand_id": brand.id})
        cls.vehicle = cls.env["fleet.vehicle"].create({"model_id": model.id, "license_plate": "AB123CD"})
        cls.inspector = cls.env["res.users"].create({
            "name": "Inspector de prueba",
            "login": "inspector_test",
            "groups_id": [(6, 0, [cls.env.ref("fleet_inspection.group_fleet_inspection_user").id])],
        })
        cls.other_inspector = cls.env["res.users"].create({
            "name": "Otro inspector",
            "login": "other_inspector_test",
            "groups_id": [(6, 0, [cls.env.ref("fleet_inspection.group_fleet_inspection_user").id])],
        })
        cls.type_motorcycle = cls.env.ref("fleet_inspection.vehicle_type_motorcycle")
        cls.type_car = cls.env.ref("fleet_inspection.vehicle_type_car")
        cls.type_truck = cls.env.ref("fleet_inspection.vehicle_type_truck")
        cls.type_other = cls.env.ref("fleet_inspection.vehicle_type_other")

    def _new_inspection(self, **vals):
        values = {
            "vehicle_id": self.vehicle.id,
            "vehicle_type_id": self.type_truck.id,
            "inspector_id": self.inspector.id,
        }
        values.update(vals)
        return self.env["fleet.inspection"].create(values)

    def test_create_loads_checklist_and_sequence(self):
        inspection = self._new_inspection()
        self.assertTrue(inspection.name.startswith("INS/"))
        items = self.env["fleet.inspection.item"].search([])
        self.assertEqual(inspection.line_ids.mapped("item_id"), items)

    def test_display_name_includes_plate(self):
        inspection = self._new_inspection()
        self.assertIn("AB123CD", inspection.display_name)

    def test_full_flow_approved(self):
        inspection = self._new_inspection()
        inspection.action_start()
        self.assertEqual(inspection.state, "in_progress")
        with self.assertRaises(UserError):
            inspection.action_approve()
        inspection.line_ids.write({"result": "ok"})
        inspection.action_approve()
        self.assertEqual(inspection.state, "approved")

    def test_critical_failure_blocks_approval(self):
        inspection = self._new_inspection()
        inspection.action_start()
        inspection.line_ids.write({"result": "ok"})
        brakes = inspection.line_ids.filtered(lambda l: l.item_id == self.env.ref("fleet_inspection.item_brakes"))
        brakes.result = "fail"
        self.assertEqual(inspection.failed_count, 1)
        with self.assertRaises(UserError):
            inspection.action_approve()
        inspection.action_reject()
        self.assertEqual(inspection.state, "rejected")

    def test_negative_odometer(self):
        with self.assertRaises(ValidationError):
            self._new_inspection(odometer=-10)

    def test_inspector_sees_only_own(self):
        own = self._new_inspection()
        other = self._new_inspection(inspector_id=self.other_inspector.id)
        visible = self.env["fleet.inspection"].with_user(self.inspector).search([])
        self.assertIn(own, visible)
        self.assertNotIn(other, visible)

    def test_inspector_cannot_delete(self):
        inspection = self._new_inspection()
        with self.assertRaises(AccessError):
            inspection.with_user(self.inspector).unlink()

    def test_form_default_inspector(self):
        form = Form(self.env["fleet.inspection"].with_user(self.inspector))
        form.vehicle_id = self.vehicle
        inspection = form.save()
        self.assertEqual(inspection.inspector_id, self.inspector)
        self.assertEqual(inspection.vehicle_type_id, self.type_car)

    def test_cron_marks_overdue_once(self):
        inspection = self._new_inspection(date=fields.Date.today() - timedelta(days=10))
        inspection.action_start()
        self.env["fleet.inspection"]._cron_mark_overdue()
        self.env["fleet.inspection"]._cron_mark_overdue()
        self.assertTrue(inspection.is_overdue)
        self.assertEqual(len(inspection.activity_ids), 1)

    def test_migration_preserves_all_vehicle_types_including_other_and_is_idempotent(self):
        pre_mod = _load_migration_module("pre-migrate.py")
        post_mod = _load_migration_module("post-migrate.py")

        insp_moto = self._new_inspection(vehicle_type_id=self.type_car.id)
        insp_car = self._new_inspection(vehicle_type_id=self.type_truck.id)
        insp_truck = self._new_inspection(vehicle_type_id=self.type_car.id)
        insp_other = self._new_inspection(vehicle_type_id=self.type_car.id)
        self.env.flush_all()

        # Simular escenario previo a la migración con la columna Selección vehicle_type
        cr = self.env.cr
        cr.execute("ALTER TABLE fleet_inspection ADD COLUMN IF NOT EXISTS vehicle_type VARCHAR")
        cr.execute("ALTER TABLE fleet_inspection ALTER COLUMN vehicle_type_id DROP NOT NULL")
        for rec, legacy_code in (
            (insp_moto, "motorcycle"),
            (insp_car, "car"),
            (insp_truck, "truck"),
            (insp_other, "other"),
        ):
            cr.execute(
                """
                UPDATE fleet_inspection
                   SET vehicle_type = %s,
                       vehicle_type_id = NULL
                 WHERE id = %s
                """,
                (legacy_code, rec.id),
            )

        # Ejecutar pre-migrate y post-migrate
        pre_mod.migrate(cr, "18.0.1.0.0")
        first_stats = post_mod.migrate_vehicle_types_in_batches(cr, batch_size=2)
        self.env.invalidate_all()

        self.assertEqual(insp_moto.vehicle_type_id, self.type_motorcycle)
        self.assertEqual(insp_car.vehicle_type_id, self.type_car)
        self.assertEqual(insp_truck.vehicle_type_id, self.type_truck)
        self.assertEqual(insp_other.vehicle_type_id, self.type_other)

        # Verificar idempotencia: correr por segunda vez no modifica nada ni falla
        second_stats = post_mod.migrate_vehicle_types_in_batches(cr, batch_size=2)
        self.assertEqual(second_stats["updated"], 0)
        self.assertEqual(insp_other.vehicle_type_id, self.type_other)
        self.assertGreaterEqual(first_stats["elapsed_ms"], 0.0)

    def test_migration_batch_10000_inspections(self):
        post_mod = _load_migration_module("post-migrate.py")
        cr = self.env.cr

        cr.execute("ALTER TABLE fleet_inspection ADD COLUMN IF NOT EXISTS vehicle_type_legacy VARCHAR")
        cr.execute("ALTER TABLE fleet_inspection ALTER COLUMN vehicle_type_id DROP NOT NULL")

        # Generar 10.000 inspecciones con distribución entre motorcycle, car, truck y other
        cr.execute(
            """
            INSERT INTO fleet_inspection (
                name, vehicle_id, inspector_id, date, odometer, state,
                failed_count, pending_count, is_overdue, vehicle_type_id, vehicle_type_legacy,
                create_uid, create_date, write_uid, write_date
            )
            SELECT
                'INS/MIG10K/' || LPAD(gs::text, 5, '0'),
                %s,
                %s,
                CURRENT_DATE,
                (gs * 10)::float,
                'draft',
                0,
                0,
                FALSE,
                NULL,
                (ARRAY['motorcycle', 'car', 'truck', 'other'])[1 + (gs %% 4)],
                %s,
                NOW() AT TIME ZONE 'utc',
                %s,
                NOW() AT TIME ZONE 'utc'
            FROM generate_series(1, 10000) AS gs
            """,
            (self.vehicle.id, self.inspector.id, self.env.uid, self.env.uid),
        )

        stats = post_mod.migrate_vehicle_types_in_batches(cr, batch_size=1000)
        self.assertEqual(stats["updated"], 10000)
        self.assertEqual(stats["batches"], 10)

        cr.execute("SELECT COUNT(*) FROM fleet_inspection WHERE vehicle_type_id IS NULL")
        null_count = cr.fetchone()[0]
        self.assertEqual(null_count, 0)

        # Verificar conteo exacto de los 2.500 registros 'other' generados
        cr.execute(
            """
            SELECT COUNT(*)
              FROM fleet_inspection
             WHERE name LIKE 'INS/MIG10K/%%'
               AND vehicle_type_id = %s
            """,
            (self.type_other.id,),
        )
        other_count = cr.fetchone()[0]
        self.assertEqual(other_count, 2500)
