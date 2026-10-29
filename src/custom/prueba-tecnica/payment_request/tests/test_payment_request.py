from datetime import date
from unittest.mock import patch

from psycopg2 import OperationalError

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestPaymentRequest(TransactionCase):
    @classmethod
    def _create_account(cls, code, name, account_type, reconcile=False):
        Account = cls.env["account.account"].with_company(cls.company_a)
        vals = {
            "code": code,
            "name": name,
            "account_type": account_type,
            "reconcile": reconcile,
        }
        if "company_ids" in Account._fields:
            vals["company_ids"] = [(6, 0, [cls.company_a.id])]
        elif "company_id" in Account._fields:
            vals["company_id"] = cls.company_a.id
        return Account.create(vals)

    @classmethod
    def _configure_bank_journal_accounts(cls, journal, bank_account, outstanding_account):
        if "default_account_id" in journal._fields and not journal.default_account_id:
            journal.default_account_id = bank_account.id
        if "outbound_payment_method_line_ids" in journal._fields:
            for line in journal.outbound_payment_method_line_ids:
                if "payment_account_id" in line._fields and not line.payment_account_id:
                    line.payment_account_id = outstanding_account.id

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_usd = cls.env.ref("base.USD")
        cls.currency_usd.active = True
        cls.currency_ves = (
            cls.env["res.currency"]
            .with_context(active_test=False)
            .search([("name", "=", "VES")], limit=1)
        )
        if not cls.currency_ves:
            cls.currency_ves = cls.env["res.currency"].create({
                "name": "VES",
                "symbol": "Bs.",
                "rounding": 0.01,
                "active": True,
            })
        else:
            cls.currency_ves.active = True

        cls.company_a = cls.env["res.company"].create({
            "name": "Distribuidora Andina C.A.",
            "currency_id": cls.currency_usd.id,
        })
        cls.company_b = cls.env["res.company"].create({
            "name": "Distribuidora Sucursal B",
            "currency_id": cls.currency_usd.id,
        })

        # Crear cuentas contables mínimas para garantizar que account.payment funcione en BD limpia
        cls.acc_payable = cls._create_account(
            "211001", "Cuentas por pagar proveedores", "liability_payable", reconcile=True
        )
        cls.acc_receivable = cls._create_account(
            "112001", "Cuentas por cobrar clientes", "asset_receivable", reconcile=True
        )
        cls.acc_bank_usd = cls._create_account(
            "111001", "Banco USD", "asset_cash"
        )
        cls.acc_bank_ves = cls._create_account(
            "111002", "Banco VES", "asset_cash"
        )
        cls.acc_outstanding = cls._create_account(
            "111099", "Pagos salientes pendientes", "asset_current", reconcile=True
        )

        cls.requester = new_test_user(
            cls.env,
            login="pr_requester_1",
            groups="payment_request.group_payment_request_requester",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
            name="Empleado Solicitante 1",
        )
        cls.other_requester = new_test_user(
            cls.env,
            login="pr_requester_2",
            groups="payment_request.group_payment_request_requester",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
            name="Empleado Solicitante 2",
        )
        cls.approver_dept = new_test_user(
            cls.env,
            login="pr_approver_dept",
            groups="payment_request.group_payment_request_approver",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
            name="Jefe de Área",
        )
        cls.approver_mgmt = new_test_user(
            cls.env,
            login="pr_approver_mgmt",
            groups="payment_request.group_payment_request_approver",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
            name="Gerente General",
        )
        cls.treasury = new_test_user(
            cls.env,
            login="pr_treasury",
            groups="payment_request.group_payment_request_treasury,account.group_account_manager",
            company_id=cls.company_a.id,
            company_ids=[(6, 0, [cls.company_a.id])],
            name="Analista de Tesorería",
        )
        cls.user_company_b = new_test_user(
            cls.env,
            login="pr_user_company_b",
            groups="payment_request.group_payment_request_approver",
            company_id=cls.company_b.id,
            company_ids=[(6, 0, [cls.company_b.id])],
            name="Aprobador Compañía B",
        )

        cls.supplier = cls.env["res.partner"].with_company(cls.company_a).create({
            "name": "Proveedor Andino C.A.",
            "supplier_rank": 1,
            "property_account_payable_id": cls.acc_payable.id,
            "property_account_receivable_id": cls.acc_receivable.id,
        })

        # Niveles de aprobación en Compañía A:
        # - Pagos normales (>= 0 USD): Jefe de Área
        # - Pagos grandes (>= 1000 USD): Gerente General
        cls.level_normal = cls.env["payment.approval.level"].create({
            "name": "Pagos Normales (Jefe de Área)",
            "company_id": cls.company_a.id,
            "min_amount": 0.0,
            "approver_id": cls.approver_dept.id,
        })
        cls.level_large = cls.env["payment.approval.level"].create({
            "name": "Pagos Grandes (Gerencia)",
            "company_id": cls.company_a.id,
            "min_amount": 1000.0,
            "approver_id": cls.approver_mgmt.id,
        })

        cls.bank_journal_usd = cls.env["account.journal"].with_company(cls.company_a).create({
            "name": "Banco USD",
            "code": "BUSD",
            "type": "bank",
            "company_id": cls.company_a.id,
            "currency_id": cls.currency_usd.id,
            "default_account_id": cls.acc_bank_usd.id,
        })
        cls._configure_bank_journal_accounts(
            cls.bank_journal_usd, cls.acc_bank_usd, cls.acc_outstanding
        )

        cls.bank_journal_ves = cls.env["account.journal"].with_company(cls.company_a).create({
            "name": "Banco Nacional VES",
            "code": "BVES",
            "type": "bank",
            "company_id": cls.company_a.id,
            "currency_id": cls.currency_ves.id,
            "default_account_id": cls.acc_bank_ves.id,
        })
        cls._configure_bank_journal_accounts(
            cls.bank_journal_ves, cls.acc_bank_ves, cls.acc_outstanding
        )

    def _create_request(self, user=None, amount=250.0, **extra):
        user = user or self.requester
        vals = {
            "partner_id": self.supplier.id,
            "amount": amount,
            "currency_id": self.currency_usd.id,
            "concept": "Pago de factura de insumos #0045",
        }
        vals.update(extra)
        return self.env["payment.request"].with_user(user).create(vals)

    # -------------------------------------------------------------------------
    # Tramo A: Secuencia, flujo, permisos, edición bloqueada y monto positivo
    # -------------------------------------------------------------------------
    def test_sequence_and_default_requester(self):
        req = self._create_request(self.requester)
        self.assertTrue(req.name.startswith("SP/"))
        self.assertEqual(req.requester_id, self.requester)
        self.assertEqual(req.state, "draft")

    def test_zero_or_negative_amount_rejected(self):
        for invalid_amount in (0.0, -50.0):
            with self.assertRaises(ValidationError):
                self._create_request(self.requester, amount=invalid_amount)

    def test_requester_sees_only_own_and_cannot_approve(self):
        own_req = self._create_request(self.requester)
        other_req = self._create_request(self.other_requester)

        visible = self.env["payment.request"].with_user(self.requester).search([])
        self.assertIn(own_req, visible)
        self.assertNotIn(other_req, visible)

        own_req.with_user(self.requester).action_submit()
        self.assertEqual(own_req.state, "submitted")

        # El solicitante no puede aprobar ni llamando directamente al método
        with self.assertRaises(AccessError):
            own_req.with_user(self.requester).action_approve()

    def test_submitted_request_cannot_be_edited_or_deleted(self):
        req = self._create_request(self.requester, amount=100.0)
        req.with_user(self.requester).action_submit()

        with self.assertRaises(UserError):
            req.with_user(self.requester).write({"amount": 500.0})

        with self.assertRaises(UserError):
            req.with_user(self.requester).write({"concept": "Cambio no permitido"})

        with self.assertRaises(UserError):
            req.with_user(self.requester).unlink()

    # -------------------------------------------------------------------------
    # Tramo B: Niveles de aprobación, actividad, rechazo en chatter, pago y PDF
    # -------------------------------------------------------------------------
    def test_approval_level_assignment_activity_and_only_assigned_approver(self):
        # Solicitud de 2500 USD -> debe asignarse a Gerencia (>= 1000 USD)
        req_large = self._create_request(self.requester, amount=2500.0)
        req_large.with_user(self.requester).action_submit()

        self.assertEqual(req_large.approver_id, self.approver_mgmt)
        self.assertEqual(req_large.approval_level_id, self.level_large)
        self.assertTrue(
            req_large.activity_ids.filtered(lambda a: a.user_id == self.approver_mgmt)
        )

        # El Jefe de Área (aunque tiene grupo Aprobador) NO es el aprobador asignado
        with self.assertRaises(AccessError):
            req_large.with_user(self.approver_dept).action_approve()

        # La Gerencia (aprobador asignado) sí puede aprobar
        req_large.with_user(self.approver_mgmt).action_approve()
        self.assertEqual(req_large.state, "approved")
        self.assertEqual(req_large.approved_by_id, self.approver_mgmt)
        self.assertTrue(req_large.approved_date)

    def test_reject_wizard_posts_mandatory_reason_in_chatter(self):
        req = self._create_request(self.requester, amount=300.0)
        req.with_user(self.requester).action_submit()
        self.assertEqual(req.approver_id, self.approver_dept)

        with self.assertRaises(ValidationError):
            self.env["payment.request.reject.wizard"].with_user(self.approver_dept).create({
                "request_id": req.id,
                "reason": "   ",
            })

        wiz = (
            self.env["payment.request.reject.wizard"]
            .with_user(self.approver_dept)
            .create({
                "request_id": req.id,
                "reason": "Falta adjuntar el soporte fiscal del proveedor.",
            })
        )
        wiz.action_confirm_reject()
        self.assertEqual(req.state, "rejected")
        self.assertEqual(req.rejection_reason, "Falta adjuntar el soporte fiscal del proveedor.")
        self.assertTrue(
            any(
                "Falta adjuntar el soporte fiscal del proveedor." in (m.body or "")
                for m in req.message_ids
            )
        )

    def test_pay_wizard_creates_payment_prevents_double_pay_and_renders_pdf(self):
        req = self._create_request(self.requester, amount=400.0)
        req.with_user(self.requester).action_submit()
        req.with_user(self.approver_dept).action_approve()

        pay_wiz = (
            self.env["payment.request.pay.wizard"]
            .with_user(self.treasury)
            .create({
                "request_id": req.id,
                "journal_id": self.bank_journal_usd.id,
                "payment_date": date(2026, 10, 27),
            })
        )
        pay_wiz.action_confirm_pay()

        self.assertEqual(req.state, "paid")
        self.assertTrue(req.payment_id)
        self.assertAlmostEqual(req.payment_id.amount, 400.0)

        # Intentar pagar una segunda vez lanza UserError
        with self.assertRaises(UserError):
            req.with_user(self.treasury)._register_supplier_payment(
                journal=self.bank_journal_usd,
                payment_date=date(2026, 10, 27),
            )

        # Verificar que el reporte QWeb muestra quién aprobó y cuándo
        html_Tuple = self.env["ir.actions.report"]._render_qweb_html(
            "payment_request.report_payment_request", req.ids
        )
        rendered_html = html_Tuple[0].decode("utf-8") if isinstance(html_Tuple[0], bytes) else str(html_Tuple[0])
        self.assertIn(self.approver_dept.name, rendered_html)
        self.assertIn(req.name, rendered_html)

    # -------------------------------------------------------------------------
    # Tramo C: Conversión USD -> VES, multi-compañía, concurrencia y atomicidad
    # -------------------------------------------------------------------------
    def test_usd_request_paid_from_ves_journal_at_payment_date_rate(self):
        # Configurar tasa en la fecha de pago: 1 USD = 45.50 VES
        payment_day = date(2026, 10, 27)
        self.env["res.currency.rate"].search([
            ("currency_id", "=", self.currency_ves.id),
            ("company_id", "=", self.company_a.id),
        ]).unlink()
        self.env["res.currency.rate"].create({
            "name": payment_day,
            "currency_id": self.currency_ves.id,
            "company_id": self.company_a.id,
            "rate": 45.50,
        })

        req = self._create_request(self.requester, amount=100.0, currency_id=self.currency_usd.id)
        req.with_user(self.requester).action_submit()
        req.with_user(self.approver_dept).action_approve()

        pay_wiz = (
            self.env["payment.request.pay.wizard"]
            .with_user(self.treasury)
            .create({
                "request_id": req.id,
                "journal_id": self.bank_journal_ves.id,
                "payment_date": payment_day,
            })
        )
        pay_wiz.action_confirm_pay()

        self.assertEqual(req.state, "paid")
        self.assertEqual(req.payment_id.currency_id, self.currency_ves)
        self.assertAlmostEqual(req.payment_id.amount, 4550.0, places=2)

    def test_multi_company_isolation(self):
        req_company_a = self._create_request(self.requester, amount=150.0)
        visible_in_b = (
            self.env["payment.request"]
            .with_user(self.user_company_b)
            .with_company(self.company_b)
            .search([])
        )
        self.assertNotIn(req_company_a, visible_in_b)

        levels_in_b = (
            self.env["payment.approval.level"]
            .with_user(self.user_company_b)
            .with_company(self.company_b)
            .search([])
        )
        self.assertNotIn(self.level_normal, levels_in_b)
        self.assertNotIn(self.level_large, levels_in_b)

    def test_concurrent_approval_and_payment_atomicity_on_failure(self):
        req = self._create_request(self.requester, amount=200.0)
        req.with_user(self.requester).action_submit()

        # Si otro usuario mantiene bloqueada la fila en PostgreSQL (FOR UPDATE NOWAIT), lanza UserError claro
        orig_execute = self.env.cr.execute

        def mock_execute(query, params=None, *args, **kwargs):
            if isinstance(query, str) and "FOR UPDATE NOWAIT" in query:
                raise OperationalError('could not obtain lock on row in relation "payment_request"')
            return orig_execute(query, params, *args, **kwargs)

        with patch.object(self.env.cr, "execute", side_effect=mock_execute):
            with self.assertRaises(UserError):
                req.with_user(self.approver_dept)._lock_rows_for_update()

        # Primera aprobación gana; una segunda aprobación concurrente/consecutiva falla
        req.with_user(self.approver_dept).action_approve()
        with self.assertRaises(UserError):
            req.with_user(self.approver_dept).action_approve()

        # Si la creación del pago contable falla, la solicitud NO queda en estado 'paid'
        with patch.object(
            type(self.env["account.payment"]),
            "create",
            side_effect=UserError("Fallo simulado al contabilizar el asiento"),
        ):
            with self.assertRaises(UserError):
                req.with_user(self.treasury)._register_supplier_payment(
                    journal=self.bank_journal_usd,
                    payment_date=date(2026, 10, 27),
                )

        self.assertEqual(req.state, "approved")
        self.assertFalse(req.payment_id)
