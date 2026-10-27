# -*- coding: utf-8 -*-
# Resolución Ejercicio 1

from datetime import datetime
import hashlib
import json
import logging
import re
import time

import psycopg2

from odoo import fields, http
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class ShopIntegrationController(http.Controller):
    """Controlador REST para la integración con la tienda en línea."""

    # -------------------------------------------------------------------------
    # MÉTODOS AUXILIARES: RESPUESTAS JSON Y REGISTRO DE AUDITORÍA
    # -------------------------------------------------------------------------

    def _json_response(self, data, status=200):
        return Response(
            json.dumps(data, ensure_ascii=False, default=str),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def _error_response(self, code, field, message, status=422):
        payload = {
            "error": {
                "code": code,
                "field": field,
                "message": message,
            }
        }
        return self._json_response(payload, status=status)

    def _log_api_call(self, endpoint, http_method, user_id, status_code, start_time, error_code=False):
        """Registra la llamada en shop.api.log sin almacenar nunca la clave API."""
        duration_ms = round((time.perf_counter() - start_time) * 1000.0, 2)
        request.env["shop.api.log"].sudo().create({
            "endpoint": endpoint,
            "http_method": http_method,
            "user_id": user_id or False,
            "status_code": status_code,
            "duration_ms": duration_ms,
            "error_code": error_code or False,
        })

    def _authenticate_api_request(self, allow_session=False):
        """Valida la cabecera Authorization: Bearer con res.users.apikeys.

        Si allow_session=True y no viene cabecera Authorization, permite usar
        la sesión activa de usuario ('user'). Devuelve (uid, error_tuple).
        """
        auth_header = request.httprequest.headers.get("Authorization", "").strip()
        if auth_header:
            match = re.match(r"^Bearer\s+(\S+)$", auth_header, re.IGNORECASE)
            if not match:
                return None, (
                    "UNAUTHORIZED",
                    "Authorization",
                    "Formato de cabecera Authorization inválido. Use 'Bearer <api_key>'.",
                    401,
                )
            token = match.group(1).strip()
            if not token:
                return None, (
                    "UNAUTHORIZED",
                    "Authorization",
                    "La clave API está vacía.",
                    401,
                )
            try:
                uid = request.env["res.users.apikeys"]._check_credentials(
                    scope="rpc", key=token
                )
            except Exception:
                uid = None
            if not uid:
                return None, (
                    "UNAUTHORIZED",
                    "Authorization",
                    "La clave API proporcionada es inválida o ha expirado.",
                    401,
                )
            request.update_env(user=uid)
            return uid, None

        if allow_session and request.session.uid:
            request.update_env(user=request.session.uid)
            return request.session.uid, None

        return None, (
            "UNAUTHORIZED",
            "Authorization",
            "Se requiere autenticación mediante cabecera 'Authorization: Bearer <api_key>'.",
            401,
        )

    def _parse_modified_since(self, raw_value):
        """Convierte una cadena ISO 8601 (fecha o fecha-hora) a datetime de Odoo."""
        raw_value = (raw_value or "").strip()
        if not raw_value:
            return None
        normalized = raw_value.replace("Z", "")
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(normalized, fmt)
            except ValueError:
                continue
        return False

    def _build_products_domain_and_filters(self, params):
        """Construye el dominio de búsqueda de productos y valida los parámetros."""
        domain = [("active", "=", True), ("sale_ok", "=", True)]

        category_param = (
            params.get("category_id")
            or params.get("category")
            or params.get("categ_id")
        )
        if category_param not in (None, ""):
            try:
                categ_id = int(category_param)
                if categ_id <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                return None, None, (
                    "INVALID_CATEGORY",
                    "category_id",
                    f"El identificador de categoría '{category_param}' no es válido.",
                    400,
                )
            domain.append(("categ_id", "child_of", categ_id))

        modified_param = (
            params.get("modified_since")
            or params.get("updated_since")
            or params.get("since")
        )
        if modified_param not in (None, ""):
            parsed_dt = self._parse_modified_since(modified_param)
            if not parsed_dt:
                return None, None, (
                    "INVALID_DATE",
                    "modified_since",
                    (
                        f"La fecha '{modified_param}' no tiene un formato válido. "
                        "Use YYYY-MM-DD o YYYY-MM-DDTHH:MM:SS."
                    ),
                    400,
                )
            dt_str = fields.Datetime.to_string(parsed_dt)
            domain.extend([
                "|",
                ("write_date", ">=", dt_str),
                ("product_tmpl_id.write_date", ">=", dt_str),
            ])

        in_stock_param = (
            params.get("in_stock")
            if "in_stock" in params
            else params.get("with_stock", params.get("only_stock"))
        )
        only_in_stock = False
        if in_stock_param not in (None, ""):
            val_lower = str(in_stock_param).strip().lower()
            if val_lower in ("1", "true", "yes", "si", "sí"):
                only_in_stock = True
            elif val_lower in ("0", "false", "no"):
                only_in_stock = False
            else:
                return None, None, (
                    "INVALID_BOOLEAN",
                    "in_stock",
                    f"El valor '{in_stock_param}' para filtro de stock no es válido.",
                    400,
                )

        return domain, only_in_stock, None

    def _parse_pagination(self, params):
        """Valida y extrae los parámetros de paginación (page, limit)."""
        raw_page = params.get("page", 1)
        raw_limit = params.get("limit", params.get("page_size", 20))
        try:
            page = int(raw_page)
            if page < 1:
                raise ValueError
        except (ValueError, TypeError):
            return None, None, (
                "INVALID_PAGINATION",
                "page",
                "El número de página debe ser un entero mayor o igual a 1.",
                400,
            )
        try:
            limit = int(raw_limit)
            if limit < 1 or limit > 200:
                raise ValueError
        except (ValueError, TypeError):
            return None, None, (
                "INVALID_PAGINATION",
                "limit",
                "El tamaño de página (limit) debe estar entre 1 y 200.",
                400,
            )
        return page, limit, None

    def _get_in_stock_product_ids(self):
        """Obtiene en una única consulta agregada los IDs de productos con stock > 0."""
        request.env.cr.execute(
            """
            SELECT sq.product_id
              FROM stock_quant sq
              JOIN stock_location sl ON sl.id = sq.location_id
             WHERE sl.usage = 'internal'
               AND sq.company_id IN %s
             GROUP BY sq.product_id
            HAVING COALESCE(SUM(sq.quantity), 0) > 0
            """,
            (tuple(request.env.companies.ids),),
        )
        return [row[0] for row in request.env.cr.fetchall()]

    # -------------------------------------------------------------------------
    # Optimización SQL de cálculo de stock
    # -------------------------------------------------------------------------
    def _get_stock_map_for_products(self, product_ids, env=None):
        """Calcula el stock disponible para una lista de productos en una sola consulta SQL."""
        if not product_ids:
            return {}
        current_env = env or request.env
        current_env.cr.execute(
            """
            SELECT sq.product_id, COALESCE(SUM(sq.quantity), 0.0)
              FROM stock_quant sq
              JOIN stock_location sl ON sl.id = sq.location_id
             WHERE sl.usage = 'internal'
               AND sq.company_id IN %s
               AND sq.product_id IN %s
             GROUP BY sq.product_id
            """,
            (tuple(current_env.companies.ids), tuple(product_ids)),
        )
        return {row[0]: float(row[1]) for row in current_env.cr.fetchall()}

    # -------------------------------------------------------------------------
    # Endpoint GET /api/v1/products
    # -------------------------------------------------------------------------
    @http.route("/api/v1/products", type="http", auth="public", methods=["GET"], csrf=False)
    def get_products(self, **params):
        start_time = time.perf_counter()
        endpoint = "/api/v1/products"

        uid, auth_err = self._authenticate_api_request(allow_session=True)
        if auth_err:
            code, field, msg, status = auth_err
            self._log_api_call(endpoint, "GET", False, status, start_time, error_code=code)
            return self._error_response(code, field, msg, status=status)

        domain, only_in_stock, filter_err = self._build_products_domain_and_filters(params)
        if filter_err:
            code, field, msg, status = filter_err
            self._log_api_call(endpoint, "GET", uid, status, start_time, error_code=code)
            return self._error_response(code, field, msg, status=status)

        page, limit, page_err = self._parse_pagination(params)
        if page_err:
            code, field, msg, status = page_err
            self._log_api_call(endpoint, "GET", uid, status, start_time, error_code=code)
            return self._error_response(code, field, msg, status=status)

        if only_in_stock:
            in_stock_ids = self._get_in_stock_product_ids()
            domain.append(("id", "in", in_stock_ids))

        Product = request.env["product.product"]
        total = Product.search_count(domain)
        offset = (page - 1) * limit
        products = Product.search(domain, offset=offset, limit=limit, order="id asc")

        # Lectura directa sin disparar N+1 consultas por producto
        rows = products.read(["id", "default_code", "name", "list_price"])
        stock_by_product = self._get_stock_map_for_products(products.ids)

        items = [
            {
                "id": row["id"],
                "code": row["default_code"] or "",
                "default_code": row["default_code"] or "",
                "name": row["name"],
                "price": row["list_price"],
                "list_price": row["list_price"],
                "qty_available": stock_by_product.get(row["id"], 0.0),
            }
            for row in rows
        ]

        next_page = page + 1 if (offset + len(items)) < total else None
        response_payload = {
            "data": items,
            "products": items,
            "total": total,
            "page": page,
            "limit": limit,
            "next_page": next_page,
            "meta": {
                "total": total,
                "page": page,
                "limit": limit,
                "next_page": next_page,
            },
        }
        self._log_api_call(endpoint, "GET", uid, 200, start_time)
        return self._json_response(response_payload, status=200)

    def _find_partner_by_rif(self, rif):
        """Busca un cliente por RIF (exacto o normalizado en SQL sin cargar toda la tabla)."""
        Partner = request.env["res.partner"]
        partner = Partner.search([("vat", "=ilike", rif.strip())], limit=1)
        if partner:
            return partner
        normalized = re.sub(r"[^A-Za-z0-9]", "", rif).upper()
        if not normalized:
            return Partner.browse()
        request.env.cr.execute(
            """
            SELECT id
              FROM res_partner
             WHERE active IS TRUE
               AND vat IS NOT NULL
               AND REGEXP_REPLACE(UPPER(vat), '[^A-Z0-9]', '', 'g') = %s
             ORDER BY id ASC
             LIMIT 1
            """,
            (normalized,),
        )
        row = request.env.cr.fetchone()
        return Partner.browse(row[0]) if row else Partner.browse()

    def _compute_payload_hash(self, payload):
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    # -------------------------------------------------------------------------
    # Endpoint POST /api/v1/orders
    # -------------------------------------------------------------------------
    @http.route("/api/v1/orders", type="http", auth="public", methods=["POST"], csrf=False)
    def create_order(self, **_kwargs):
        start_time = time.perf_counter()
        endpoint = "/api/v1/orders"

        uid, auth_err = self._authenticate_api_request(allow_session=False)
        if auth_err:
            code, field, msg, status = auth_err
            self._log_api_call(endpoint, "POST", False, status, start_time, error_code=code)
            return self._error_response(code, field, msg, status=status)

        raw_body = request.httprequest.get_data(as_text=True) or ""
        try:
            payload = json.loads(raw_body) if raw_body.strip() else {}
            if not isinstance(payload, dict):
                raise ValueError
        except ValueError:
            self._log_api_call(endpoint, "POST", uid, 400, start_time, error_code="INVALID_JSON")
            return self._error_response(
                "INVALID_JSON", "body", "El cuerpo de la petición debe ser un objeto JSON válido.", status=400
            )

        idempotency_key = (request.httprequest.headers.get("Idempotency-Key") or "").strip()
        payload_hash = self._compute_payload_hash(payload) if idempotency_key else None
        Idempotency = request.env["shop.api.idempotency"].sudo()

        if idempotency_key:
            existing = Idempotency.search(
                [("key", "=", idempotency_key), ("endpoint", "=", endpoint)],
                limit=1,
            )
            if existing:
                if existing.request_hash != payload_hash:
                    self._log_api_call(
                        endpoint, "POST", uid, 409, start_time, error_code="IDEMPOTENCY_CONFLICT"
                    )
                    return self._error_response(
                        "IDEMPOTENCY_CONFLICT",
                        "Idempotency-Key",
                        "La clave de idempotencia ya fue utilizada con un contenido diferente.",
                        status=409,
                    )
                cached_body = json.loads(existing.response_body)
                self._log_api_call(endpoint, "POST", uid, existing.response_status, start_time)
                return self._json_response(cached_body, status=existing.response_status)

        rif_field = "rif" if "rif" in payload or "vat" not in payload else "vat"
        rif = (payload.get("rif") or payload.get("vat") or "").strip()
        if not rif:
            self._log_api_call(endpoint, "POST", uid, 422, start_time, error_code="MISSING_RIF")
            return self._error_response(
                "MISSING_RIF", rif_field, "El RIF del cliente es obligatorio.", status=422
            )

        partner = self._find_partner_by_rif(rif)
        if not partner:
            self._log_api_call(endpoint, "POST", uid, 422, start_time, error_code="CUSTOMER_NOT_FOUND")
            return self._error_response(
                "CUSTOMER_NOT_FOUND",
                rif_field,
                f"No existe un cliente con el RIF {rif}",
                status=422,
            )

        external_ref = (
            payload.get("external_reference")
            or payload.get("client_order_ref")
            or payload.get("reference")
            or ""
        )
        if isinstance(external_ref, str):
            external_ref = external_ref.strip()
        else:
            external_ref = str(external_ref)

        lines_data = payload.get("lines")
        if not isinstance(lines_data, list) or not lines_data:
            self._log_api_call(endpoint, "POST", uid, 422, start_time, error_code="EMPTY_LINES")
            return self._error_response(
                "EMPTY_LINES",
                "lines",
                "El pedido debe incluir al menos una línea.",
                status=422,
            )

        order_lines_vals = []
        Product = request.env["product.product"]

        for idx, line in enumerate(lines_data):
            if not isinstance(line, dict):
                self._log_api_call(endpoint, "POST", uid, 422, start_time, error_code="INVALID_LINE")
                return self._error_response(
                    "INVALID_LINE",
                    f"lines[{idx}]",
                    "Cada línea debe ser un objeto JSON.",
                    status=422,
                )

            code_key = "default_code" if "default_code" in line or "code" not in line else "code"
            prod_code = (line.get("default_code") or line.get("code") or "").strip()
            if not prod_code:
                self._log_api_call(endpoint, "POST", uid, 422, start_time, error_code="PRODUCT_NOT_FOUND")
                return self._error_response(
                    "PRODUCT_NOT_FOUND",
                    f"lines[{idx}].{code_key}",
                    "El código del producto es obligatorio.",
                    status=422,
                )

            product = Product.search(
                [("default_code", "=", prod_code), ("active", "=", True), ("sale_ok", "=", True)],
                limit=1,
            )
            if not product:
                self._log_api_call(endpoint, "POST", uid, 422, start_time, error_code="PRODUCT_NOT_FOUND")
                return self._error_response(
                    "PRODUCT_NOT_FOUND",
                    f"lines[{idx}].{code_key}",
                    f"No existe un producto con el código {prod_code}",
                    status=422,
                )

            qty_key = "quantity" if "quantity" in line or "qty" not in line else "qty"
            raw_qty = line.get(qty_key)
            if isinstance(raw_qty, bool) or raw_qty is None:
                qty_valid = False
                qty_val = 0.0
            else:
                try:
                    qty_val = float(raw_qty)
                    qty_valid = qty_val > 0
                except (ValueError, TypeError):
                    qty_valid = False
                    qty_val = 0.0

            if not qty_valid:
                self._log_api_call(endpoint, "POST", uid, 422, start_time, error_code="INVALID_QUANTITY")
                return self._error_response(
                    "INVALID_QUANTITY",
                    f"lines[{idx}].{qty_key}",
                    "La cantidad debe ser mayor que cero.",
                    status=422,
                )

            order_lines_vals.append(
                (0, 0, {"product_id": product.id, "product_uom_qty": qty_val})
            )

        try:
            with request.env.cr.savepoint():
                order = request.env["sale.order"].create({
                    "partner_id": partner.id,
                    "client_order_ref": external_ref or False,
                    "order_line": order_lines_vals,
                })
                order.action_confirm()

                response_data = {
                    "id": order.id,
                    "name": order.name,
                    "state": order.state,
                    "external_reference": order.client_order_ref or "",
                    "partner_rif": partner.vat,
                    "amount_untaxed": order.amount_untaxed,
                    "amount_total": order.amount_total,
                    "lines": [
                        {
                            "id": l.id,
                            "default_code": l.product_id.default_code or "",
                            "quantity": l.product_uom_qty,
                            "price_unit": l.price_unit,
                            "price_subtotal": l.price_subtotal,
                        }
                        for l in order.order_line
                    ],
                }
                if idempotency_key:
                    Idempotency.create({
                        "key": idempotency_key,
                        "endpoint": endpoint,
                        "request_hash": payload_hash,
                        "order_id": order.id,
                        "response_status": 201,
                        "response_body": json.dumps(response_data, ensure_ascii=False, default=str),
                    })
        except psycopg2.IntegrityError:
            if idempotency_key:
                existing = Idempotency.search(
                    [("key", "=", idempotency_key), ("endpoint", "=", endpoint)],
                    limit=1,
                )
                if existing:
                    if existing.request_hash != payload_hash:
                        self._log_api_call(
                            endpoint, "POST", uid, 409, start_time, error_code="IDEMPOTENCY_CONFLICT"
                        )
                        return self._error_response(
                            "IDEMPOTENCY_CONFLICT",
                            "Idempotency-Key",
                            "La clave de idempotencia ya fue utilizada con un contenido diferente.",
                            status=409,
                        )
                    cached_body = json.loads(existing.response_body)
                    self._log_api_call(endpoint, "POST", uid, existing.response_status, start_time)
                    return self._json_response(cached_body, status=existing.response_status)
            raise
        except Exception as exc:
            _logger.exception("Error procesando creación de pedido vía API: %s", exc)
            self._log_api_call(endpoint, "POST", uid, 500, start_time, error_code="INTERNAL_ERROR")
            return self._error_response(
                "INTERNAL_ERROR",
                "order",
                "No fue posible procesar el pedido en este momento.",
                status=500,
            )

        self._log_api_call(endpoint, "POST", uid, 201, start_time)
        return self._json_response(response_data, status=201)
