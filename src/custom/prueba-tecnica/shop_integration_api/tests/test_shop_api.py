from datetime import timedelta
import inspect
import json
from unittest.mock import MagicMock, patch

import requests

from odoo import fields
from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
class TestShopIntegrationApi(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.api_user = new_test_user(
            cls.env,
            login="shop_api_user",
            password="shop_api_password",
            groups="sales_team.group_sale_salesman_all_leads,stock.group_stock_user",
            name="Usuario Tienda API",
        )
        apikeys_model = cls.env["res.users.apikeys"].with_user(cls.api_user)
        sig = inspect.signature(apikeys_model._generate)
        if "expiration_date" in sig.parameters:
            cls.api_key = apikeys_model._generate(
                None, "Tienda Online Test", fields.Datetime.now() + timedelta(days=1)
            )
        else:
            cls.api_key = apikeys_model._generate(None, "Tienda Online Test")

        cls.customer = cls.env["res.partner"].create({
            "name": "Comercializadora Bolívar C.A.",
            "vat": "J-31234567-8",
        })

        cls.cat_electronics = cls.env["product.category"].create({"name": "Electrónica API"})
        cls.cat_accessories = cls.env["product.category"].create({"name": "Accesorios API"})

        cls.warehouse = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.env.company.id)], limit=1
        )
        cls.stock_location = cls.warehouse.lot_stock_id

        cls.prod_in_stock = cls._create_storable_product(
            name="Laptop Pro 15",
            default_code="LAP-001",
            list_price=1200.0,
            categ_id=cls.cat_electronics.id,
        )
        cls.prod_no_stock = cls._create_storable_product(
            name="Mouse Inalámbrico",
            default_code="MOU-002",
            list_price=25.0,
            categ_id=cls.cat_accessories.id,
        )
        cls.prod_inactive = cls._create_storable_product(
            name="Producto Inactivo",
            default_code="INA-003",
            list_price=10.0,
            categ_id=cls.cat_electronics.id,
            active=False,
        )
        cls.prod_not_salable = cls._create_storable_product(
            name="Insumo Interno",
            default_code="INT-004",
            list_price=5.0,
            categ_id=cls.cat_electronics.id,
            sale_ok=False,
        )

        cls.env["stock.quant"]._update_available_quantity(
            cls.prod_in_stock, cls.stock_location, 15.0
        )

    @classmethod
    def _create_storable_product(cls, **vals):
        Product = cls.env["product.product"]
        if "is_storable" in Product._fields:
            vals.setdefault("type", "consu")
            vals.setdefault("is_storable", True)
        elif "detailed_type" in Product._fields:
            vals.setdefault("detailed_type", "product")
        else:
            vals.setdefault("type", "product")
        vals.setdefault("sale_ok", True)
        vals.setdefault("taxes_id", [(5, 0, 0)])
        return Product.create(vals)

    def _auth_headers(self, extra=None):
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        if extra:
            headers.update(extra)
        return headers

    def _post_json(self, url, payload, headers=None):
        return self.url_open(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers if headers is not None else self._auth_headers(),
        )

    # -------------------------------------------------------------------------
    # Tramo A: GET /api/v1/products y filtros
    # -------------------------------------------------------------------------
    def test_get_products_only_active_and_salable(self):
        self.authenticate("shop_api_user", "shop_api_password")
        res = self.url_open("/api/v1/products")
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.text)
        codes = {item["default_code"] for item in body["data"]}
        self.assertIn("LAP-001", codes)
        self.assertIn("MOU-002", codes)
        self.assertNotIn("INA-003", codes)
        self.assertNotIn("INT-004", codes)

    def test_get_products_filters_alone_and_combined(self):
        self.authenticate("shop_api_user", "shop_api_password")

        # 1. Filtro por categoría
        res_cat = self.url_open(f"/api/v1/products?category_id={self.cat_electronics.id}")
        self.assertEqual(res_cat.status_code, 200)
        codes_cat = {p["default_code"] for p in json.loads(res_cat.text)["data"]}
        self.assertIn("LAP-001", codes_cat)
        self.assertNotIn("MOU-002", codes_cat)

        # 2. Filtro solo con stock
        res_stock = self.url_open("/api/v1/products?in_stock=true")
        self.assertEqual(res_stock.status_code, 200)
        items_stock = json.loads(res_stock.text)["data"]
        codes_stock = {p["default_code"] for p in items_stock}
        self.assertIn("LAP-001", codes_stock)
        self.assertNotIn("MOU-002", codes_stock)
        self.assertTrue(all(p["qty_available"] > 0 for p in items_stock))

        # 3. Filtro modificados desde una fecha (tanto en variante como en plantilla)
        past_dt = fields.Datetime.now() - timedelta(days=5)
        self.env.cr.execute(
            "UPDATE product_product SET write_date = %s WHERE id = %s",
            (past_dt, self.prod_no_stock.id),
        )
        self.env.cr.execute(
            "UPDATE product_template SET write_date = %s WHERE id = %s",
            (past_dt, self.prod_no_stock.product_tmpl_id.id),
        )
        since_str = (fields.Datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")
        res_since = self.url_open(f"/api/v1/products?modified_since={since_str}")
        self.assertEqual(res_since.status_code, 200)
        codes_since = {p["default_code"] for p in json.loads(res_since.text)["data"]}
        self.assertIn("LAP-001", codes_since)
        self.assertNotIn("MOU-002", codes_since)

        # 4. Filtros combinados (categoría + con stock + modificados desde)
        res_combined = self.url_open(
            f"/api/v1/products?category_id={self.cat_electronics.id}"
            f"&in_stock=1&modified_since={since_str}"
        )
        self.assertEqual(res_combined.status_code, 200)
        codes_combined = [p["default_code"] for p in json.loads(res_combined.text)["data"]]
        self.assertEqual(codes_combined, ["LAP-001"])

    def test_get_products_invalid_date_returns_clear_error_not_500(self):
        self.authenticate("shop_api_user", "shop_api_password")
        res = self.url_open("/api/v1/products?modified_since=fecha-invalida-2026")
        self.assertEqual(res.status_code, 400)
        body = json.loads(res.text)
        self.assertIn("error", body)
        self.assertEqual(body["error"]["code"], "INVALID_DATE")
        self.assertEqual(body["error"]["field"], "modified_since")

    # -------------------------------------------------------------------------
    # Tramo B: API Keys, POST /api/v1/orders, formato de errores y shop.api.log
    # -------------------------------------------------------------------------
    def test_auth_missing_or_invalid_key_returns_401(self):
        payload = {
            "rif": "J-31234567-8",
            "external_reference": "WEB-1001",
            "lines": [{"default_code": "LAP-001", "quantity": 1}],
        }
        # Sin cabecera Authorization
        res_no_key = self._post_json(
            "/api/v1/orders", payload, headers={"Content-Type": "application/json"}
        )
        self.assertEqual(res_no_key.status_code, 401)
        err_no_key = json.loads(res_no_key.text)["error"]
        self.assertEqual(err_no_key["code"], "UNAUTHORIZED")

        # Con clave inválida
        res_bad_key = self._post_json(
            "/api/v1/orders",
            payload,
            headers={
                "Authorization": "Bearer clave_falsa_invalida_12345",
                "Content-Type": "application/json",
            },
        )
        self.assertEqual(res_bad_key.status_code, 401)
        err_bad_key = json.loads(res_bad_key.text)["error"]
        self.assertEqual(err_bad_key["code"], "UNAUTHORIZED")

    def test_post_order_validation_errors_exact_fields(self):
        # 1. RIF inexistente
        res_rif = self._post_json(
            "/api/v1/orders",
            {
                "rif": "J-99999999-9",
                "external_reference": "WEB-ERR-1",
                "lines": [{"default_code": "LAP-001", "quantity": 1}],
            },
        )
        self.assertEqual(res_rif.status_code, 422)
        err_rif = json.loads(res_rif.text)["error"]
        self.assertEqual(err_rif["code"], "CUSTOMER_NOT_FOUND")
        self.assertEqual(err_rif["field"], "rif")

        # 2. Producto inexistente en la segunda línea (lines[1].default_code)
        res_prod = self._post_json(
            "/api/v1/orders",
            {
                "rif": "J-31234567-8",
                "external_reference": "WEB-ERR-2",
                "lines": [
                    {"default_code": "LAP-001", "quantity": 1},
                    {"default_code": "ABC-123", "quantity": 2},
                ],
            },
        )
        self.assertEqual(res_prod.status_code, 422)
        err_prod = json.loads(res_prod.text)["error"]
        self.assertEqual(err_prod["code"], "PRODUCT_NOT_FOUND")
        self.assertEqual(err_prod["field"], "lines[1].default_code")
        self.assertIn("ABC-123", err_prod["message"])

        # 3. Cantidad cero o negativa (lines[0].quantity)
        for bad_qty in (0, -3):
            res_qty = self._post_json(
                "/api/v1/orders",
                {
                    "rif": "J-31234567-8",
                    "external_reference": "WEB-ERR-3",
                    "lines": [{"default_code": "LAP-001", "quantity": bad_qty}],
                },
            )
            self.assertEqual(res_qty.status_code, 422)
            err_qty = json.loads(res_qty.text)["error"]
            self.assertEqual(err_qty["code"], "INVALID_QUANTITY")
            self.assertEqual(err_qty["field"], "lines[0].quantity")

    def test_post_order_success_and_api_log_records_all_without_key(self):
        Log = self.env["shop.api.log"].sudo()
        initial_count = Log.search_count([])

        # Llamada exitosa
        res_ok = self._post_json(
            "/api/v1/orders",
            {
                "rif": "J-31234567-8",
                "external_reference": "WEB-OK-001",
                "lines": [
                    {"default_code": "LAP-001", "quantity": 2},
                    {"default_code": "MOU-002", "quantity": 3},
                ],
            },
        )
        self.assertEqual(res_ok.status_code, 201)
        data = json.loads(res_ok.text)
        self.assertEqual(data["external_reference"], "WEB-OK-001")
        self.assertEqual(data["state"], "sale")
        self.assertAlmostEqual(data["amount_total"], 2 * 1200.0 + 3 * 25.0)

        # Llamada fallida (422)
        res_fail = self._post_json(
            "/api/v1/orders",
            {
                "rif": "J-31234567-8",
                "external_reference": "WEB-FAIL-001",
                "lines": [{"default_code": "NO-EXISTE", "quantity": 1}],
            },
        )
        self.assertEqual(res_fail.status_code, 422)

        new_logs = Log.search([], order="id desc", limit=2)
        self.assertEqual(Log.search_count([]), initial_count + 2)
        statuses = {log.status_code for log in new_logs}
        self.assertEqual(statuses, {201, 422})

        for log in new_logs:
            self.assertEqual(log.endpoint, "/api/v1/orders")
            self.assertEqual(log.user_id, self.api_user)
            self.assertGreaterEqual(log.duration_ms, 0.0)
            # Verificar que la API key no esté guardada en ningún campo del log
            for fname in log._fields:
                val = str(getattr(log, fname) or "")
                self.assertNotIn(self.api_key, val)

    # -------------------------------------------------------------------------
    # Tramo C: Paginación, Idempotency-Key, consultas O(1) y Webhook con reintentos
    # -------------------------------------------------------------------------
    def test_pagination_metadata(self):
        headers = self._auth_headers()
        res_p1 = self.url_open(
            f"/api/v1/products?category_id={self.cat_electronics.id}&page=1&limit=1",
            headers=headers,
        )
        self.assertEqual(res_p1.status_code, 200)
        body_p1 = json.loads(res_p1.text)
        self.assertEqual(body_p1["page"], 1)
        self.assertEqual(body_p1["limit"], 1)
        self.assertGreaterEqual(body_p1["total"], 1)
        self.assertEqual(len(body_p1["data"]), 1)
        self.assertIn("meta", body_p1)
        self.assertEqual(body_p1["meta"]["total"], body_p1["total"])

    def test_idempotency_key_same_and_different_payload(self):
        Order = self.env["sale.order"].sudo()
        count_before = Order.search_count([])

        payload = {
            "rif": "J-31234567-8",
            "external_reference": "WEB-IDEM-001",
            "lines": [{"default_code": "LAP-001", "quantity": 1}],
        }
        headers = self._auth_headers({"Idempotency-Key": "idem-key-001"})

        # Primera petición: crea el pedido
        res_first = self._post_json("/api/v1/orders", payload, headers=headers)
        self.assertEqual(res_first.status_code, 201)
        first_body = json.loads(res_first.text)
        self.assertEqual(Order.search_count([]), count_before + 1)

        # Reintento con misma clave y mismo contenido: devuelve el mismo pedido sin duplicar
        res_retry = self._post_json("/api/v1/orders", payload, headers=headers)
        self.assertEqual(res_retry.status_code, 201)
        retry_body = json.loads(res_retry.text)
        self.assertEqual(retry_body["id"], first_body["id"])
        self.assertEqual(retry_body["name"], first_body["name"])
        self.assertEqual(Order.search_count([]), count_before + 1)

        # Misma clave con otro contenido: devuelve 409 Conflict
        different_payload = {
            "rif": "J-31234567-8",
            "external_reference": "WEB-IDEM-001",
            "lines": [{"default_code": "LAP-001", "quantity": 5}],
        }
        res_conflict = self._post_json("/api/v1/orders", different_payload, headers=headers)
        self.assertEqual(res_conflict.status_code, 409)
        err_conflict = json.loads(res_conflict.text)["error"]
        self.assertEqual(err_conflict["code"], "IDEMPOTENCY_CONFLICT")
        self.assertEqual(err_conflict["field"], "Idempotency-Key")
        self.assertEqual(Order.search_count([]), count_before + 1)

    def test_get_products_query_count_does_not_grow_with_product_count(self):
        headers = self._auth_headers()
        cat_bulk = self.env["product.category"].create({"name": "Categoría Masiva"})
        for idx in range(3):
            p = self._create_storable_product(
                name=f"Producto Base {idx}",
                default_code=f"BULK-A-{idx}",
                list_price=10.0 + idx,
                categ_id=cat_bulk.id,
            )
            self.env["stock.quant"]._update_available_quantity(p, self.stock_location, 5.0)

        # Calentar cachés en el worker HTTP con una primera llamada
        self.url_open(f"/api/v1/products?category_id={cat_bulk.id}&limit=100", headers=headers)

        # Medir consultas directamente sobre los métodos del controlador con 3 vs 30 productos
        from odoo.addons.shop_integration_api.controllers.main import ShopIntegrationController

        controller = ShopIntegrationController()
        Product = self.env["product.product"]
        domain = [("active", "=", True), ("sale_ok", "=", True), ("categ_id", "child_of", cat_bulk.id)]

        self.env.invalidate_all()
        q_before_small = self.env.cr.sql_log_count
        prods_small = Product.search(domain, limit=100, order="id asc")
        prods_small.read(["id", "default_code", "name", "list_price"])
        controller._get_stock_map_for_products(prods_small.ids, env=self.env)
        queries_small = self.env.cr.sql_log_count - q_before_small

        # Crear 27 productos adicionales con stock (total 30 productos, 10x más)
        for idx in range(3, 30):
            p = self._create_storable_product(
                name=f"Producto Extra {idx}",
                default_code=f"BULK-B-{idx}",
                list_price=20.0 + idx,
                categ_id=cat_bulk.id,
            )
            self.env["stock.quant"]._update_available_quantity(p, self.stock_location, 8.0)

        self.env.invalidate_all()
        q_before_large = self.env.cr.sql_log_count
        prods_large = Product.search(domain, limit=100, order="id asc")
        prods_large.read(["id", "default_code", "name", "list_price"])
        stock_map = controller._get_stock_map_for_products(prods_large.ids, env=self.env)
        queries_large = self.env.cr.sql_log_count - q_before_large

        self.assertEqual(len(prods_large), 30)
        self.assertEqual(len(stock_map), 30)
        # El número de consultas SQL es constante y no crece con la cantidad de productos
        self.assertLessEqual(queries_large, queries_small)

    def test_delivery_validation_webhook_does_not_block_when_shop_is_down_and_retries(self):
        order = self.env["sale.order"].create({
            "partner_id": self.customer.id,
            "client_order_ref": "WEB-HOOK-001",
            "order_line": [
                (0, 0, {"product_id": self.prod_in_stock.id, "product_uom_qty": 1.0})
            ],
        })
        order.action_confirm()
        picking = order.picking_ids.filtered(lambda p: p.picking_type_code == "outgoing")[:1]
        self.assertTrue(picking)

        for move in picking.move_ids:
            if "quantity" in move._fields:
                move.quantity = move.product_uom_qty
            elif "quantity_done" in move._fields:
                move.quantity_done = move.product_uom_qty

        # 1. Al validar la entrega, se encola el evento asíncronamente sin hacer HTTP síncrono
        with patch(
            "odoo.addons.shop_integration_api.models.shop_webhook_event.requests.post",
            side_effect=AssertionError("button_validate no debe hacer HTTP síncrono"),
        ):
            picking.button_validate()

        self.assertEqual(picking.state, "done")
        event = self.env["shop.webhook.event"].search(
            [("picking_id", "=", picking.id)], limit=1
        )
        self.assertTrue(event)
        self.assertEqual(event.state, "pending")
        self.assertEqual(event.retry_count, 0)

        # 2. El cron intenta enviar cuando la tienda está caída: registra el fallo y programa backoff
        with patch(
            "odoo.addons.shop_integration_api.models.shop_webhook_event.requests.post",
            side_effect=requests.ConnectionError("Tienda fuera de línea"),
        ):
            self.env["shop.webhook.event"]._cron_retry_pending_webhooks()

        self.assertEqual(event.state, "pending")
        self.assertEqual(event.retry_count, 1)
        self.assertIn("Tienda fuera de línea", event.last_error or "")

        # 3. Cuando la tienda vuelve a responder, el siguiente ciclo del cron marca el webhook como enviado
        event.write({"next_retry_at": fields.Datetime.now() - timedelta(minutes=1)})
        mock_ok = MagicMock(status_code=200, text="OK")
        with patch(
            "odoo.addons.shop_integration_api.models.shop_webhook_event.requests.post",
            return_value=mock_ok,
        ):
            self.env["shop.webhook.event"]._cron_retry_pending_webhooks()

        self.assertEqual(event.state, "sent")
        self.assertEqual(event.response_code, 200)
