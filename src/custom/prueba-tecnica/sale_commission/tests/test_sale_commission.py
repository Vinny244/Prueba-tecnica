from odoo.addons.sale_commission.scripts.audit_t200_affected_orders import (
    find_affected_order_lines,
)
from odoo.exceptions import AccessError
from odoo.tests import tagged
from odoo.tests.common import TransactionCase, new_test_user


@tagged("post_install", "-at_install")
class TestSaleCommission(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.salesman = new_test_user(
            cls.env,
            login="commission_salesman",
            groups="sales_team.group_sale_salesman",
            name="Vendedor de prueba",
        )
        cls.salesman.commission_percent = 5.0
        cls.other_salesman = new_test_user(
            cls.env,
            login="commission_other_salesman",
            groups="sales_team.group_sale_salesman",
            name="Otro vendedor",
        )
        cls.other_salesman.commission_percent = 3.0
        cls.manager = new_test_user(
            cls.env,
            login="commission_manager",
            groups="sales_team.group_sale_manager",
            name="Gerente de ventas",
        )
        cls.manager.commission_percent = 0.0
        cls.partner = cls.env["res.partner"].create({"name": "Cliente de prueba"})
        cls.category = cls.env["product.category"].create({"name": "Repuestos"})
        cls.product = cls.env["product.product"].create({
            "name": "Producto de prueba",
            "categ_id": cls.category.id,
            "list_price": 100.0,
            "taxes_id": [(5, 0, 0)],
        })

    def _create_order(self, user, qty=2):
        return self.env["sale.order"].with_user(user).create({
            "partner_id": self.partner.id,
            "user_id": user.id,
            "order_line": [(0, 0, {"product_id": self.product.id, "product_uom_qty": qty})],
        })

    def test_commission_on_confirm_as_salesman(self):
        """Un usuario vendedor confirma su propio pedido sin AccessError y recibe su comisión."""
        order = self._create_order(self.salesman)
        self.assertEqual(order.order_line.commission_amount, 0.0)
        order.with_user(self.salesman).action_confirm()
        self.assertEqual(order.order_line.commission_percent, 5.0)
        self.assertAlmostEqual(order.order_line.commission_amount, 10.0)

    def test_manager_confirming_salesman_order_uses_salesman_commission(self):
        """Cuando el gerente confirma el pedido de un vendedor, se usa el % del vendedor asignado."""
        order = self._create_order(self.salesman)
        order.with_user(self.manager).action_confirm()
        self.assertEqual(order.order_line.commission_percent, 5.0)
        self.assertAlmostEqual(order.order_line.commission_amount, 10.0)

    def test_salesman_cannot_modify_commission_rules(self):
        """El vendedor solo tiene lectura sobre las reglas de categoría; no puede crearlas ni editarlas."""
        with self.assertRaises(AccessError):
            self.env["sale.commission.rule"].with_user(self.salesman).create({
                "categ_id": self.category.id,
                "percent": 15.0,
            })

    def test_salesman_report_only_own(self):
        self._create_order(self.salesman).with_user(self.salesman).action_confirm()
        self._create_order(self.other_salesman).with_user(self.other_salesman).action_confirm()
        self.env.flush_all()
        lines = self.env["sale.commission.report"].with_user(self.salesman).search([])
        self.assertTrue(lines)
        self.assertEqual(lines.mapped("user_id"), self.salesman)

    def test_commission_by_category(self):
        self.category.with_user(self.manager).commission_percent = 8.0
        order = self._create_order(self.salesman)
        order.with_user(self.salesman).action_confirm()
        self.assertEqual(order.order_line.commission_percent, 8.0)
        self.assertAlmostEqual(order.order_line.commission_amount, 16.0)

    def test_subcategory_uses_most_specific_rule_and_recompute(self):
        self.category.with_user(self.manager).commission_percent = 8.0
        child = self.env["product.category"].create({"name": "Frenos", "parent_id": self.category.id})
        child.with_user(self.manager).commission_percent = 10.0
        self.product.categ_id = child
        order = self._create_order(self.salesman)
        order.with_user(self.salesman).action_confirm()
        self.assertEqual(order.order_line.commission_percent, 10.0)

        # Si se elimina la regla de la subcategoría y se recalcula, hereda el 8% de la categoría padre
        child.commission_rule_ids.unlink()
        order.with_user(self.salesman).action_recompute_commissions()
        self.assertEqual(order.order_line.commission_percent, 8.0)

    def test_audit_script_identifies_corrupted_orders_without_modifying(self):
        order = self._create_order(self.salesman)
        order.with_user(self.salesman).action_confirm()
        # Simular registro afectado por el incidente (quedó con 0% del gerente en lugar de 5% del vendedor)
        order.order_line.commission_percent = 0.0
        affected = find_affected_order_lines(self.env, date_from=False)
        line_ids = [r["line_id"] for r in affected]
        self.assertIn(order.order_line.id, line_ids)
        # Verificar que el script es de solo lectura y no modificó el registro
        self.assertEqual(order.order_line.commission_percent, 0.0)
