# Integración con API para Tienda en Línea (`shop_integration_api`)

Módulo para **Odoo 18.0** que expone los endpoints REST para que la tienda en línea del cliente consulte el catálogo de productos con su stock disponible, cree pedidos de venta y reciba notificaciones (webhooks) al validarse la entrega.

## Tramos completados

- **Tramo A (Completo):**
  - `GET /api/v1/products` con soporte de autenticación por sesión (`auth='user'`) y por API key (`Bearer`).
  - Filtros opcionales combinables: categoría (`category_id`), solo con stock (`in_stock=true`), y modificados desde fecha (`modified_since=YYYY-MM-DD` o `YYYY-MM-DDTHH:MM:SS`).
  - Validación de parámetros y fechas mal escritas devolviendo error claro HTTP `400` en JSON (nunca `500`).
  - Filtra exclusivamente productos activos y vendibles (`active=True`, `sale_ok=True`).
- **Tramo B (Completo):**
  - Autenticación mediante API keys nativas de Odoo (`res.users.apikeys`) en la cabecera `Authorization: Bearer <api_key>`.
  - `POST /api/v1/orders` que recibe `rif`, `external_reference` y `lines` (`default_code`, `quantity`).
  - Formato estructurado de errores (`{"error": {"code": "...", "field": "...", "message": "..."}}`) y códigos HTTP exactos (`401`, `400`, `409`, `422`).
  - Modelo `shop.api.log` que registra cada llamada (incluidas las fallidas `401`/`422`/`409`) con endpoint, método, usuario, código de respuesta y duración en milisegundos, sin guardar nunca la clave API.
  - Pruebas automatizadas con `HttpCase`.
- **Tramo C (Completo):**
  - Paginación en `GET /api/v1/products` (`page`, `limit`) con metadatos (`total`, `page`, `limit`, `next_page`).
  - Cabecera `Idempotency-Key` en `POST /api/v1/orders` respaldada por el modelo `shop.api.idempotency`: misma clave + mismo contenido devuelve el mismo pedido sin duplicarlo; misma clave + distinto contenido devuelve `409 Conflict`.
  - Cálculo de stock disponible mediante consulta SQL agregada sobre `stock_quant` y `stock_location` ($O(1)$ consultas sin importar la cantidad de productos, verificado con prueba).
  - Webhook saliente (`shop.webhook.event`) al validar la entrega (`stock.picking.button_validate`) con reintentos automáticos por `ir.cron` y backoff exponencial sin bloquear ni mostrar error al usuario de almacén si la tienda está caída.
  - Especificación OpenAPI 3.0 en [`openapi.yaml`](openapi.yaml).

---

## Formato de errores y códigos HTTP para la tienda

Todas las respuestas de error devuelven `Content-Type: application/json; charset=utf-8` con la siguiente estructura:

```json
{
  "error": {
    "code": "PRODUCT_NOT_FOUND",
    "field": "lines[1].default_code",
    "message": "No existe un producto con el código ABC-123"
  }
}
```

| Código HTTP | `error.code` | `error.field` | Cuándo ocurre |
| :--- | :--- | :--- | :--- |
| `400` | `INVALID_DATE` | `modified_since` | La fecha enviada en el filtro `modified_since` no cumple con ISO 8601 (`YYYY-MM-DD` o `YYYY-MM-DDTHH:MM:SS`). |
| `400` | `INVALID_CATEGORY` | `category_id` | El parámetro `category_id` no es un entero positivo. |
| `400` | `INVALID_BOOLEAN` | `in_stock` | El parámetro `in_stock` no es un valor booleano válido (`true`/`false`/`1`/`0`). |
| `400` | `INVALID_PAGINATION` | `page` / `limit` | Parámetros `page` (`< 1`) o `limit` (`< 1` o `> 200`) fuera de rango. |
| `400` | `INVALID_JSON` | `body` | El cuerpo enviado al `POST /api/v1/orders` no es un JSON válido. |
| `401` | `UNAUTHORIZED` | `Authorization` | Falta la cabecera `Authorization: Bearer <api_key>` o la clave API es inválida/expirada. |
| `409` | `IDEMPOTENCY_CONFLICT` | `Idempotency-Key` | Se reutilizó una misma `Idempotency-Key` con un payload distinto al original. |
| `422` | `MISSING_RIF` | `rif` | No se indicó el RIF del cliente en el cuerpo del pedido. |
| `422` | `CUSTOMER_NOT_FOUND` | `rif` | No existe ningún cliente (`res.partner`) con ese RIF (`vat`). |
| `422` | `EMPTY_LINES` | `lines` | La lista `lines` está vacía o no fue enviada. |
| `422` | `PRODUCT_NOT_FOUND` | `lines[i].default_code` | No existe un producto activo y vendible con ese `default_code` en la línea `i`. |
| `422` | `INVALID_QUANTITY` | `lines[i].quantity` | La cantidad en la línea `i` es cero, negativa o no numérica. |

---

## Ejemplos de integración

### 1. Consultar catálogo de productos (`GET /api/v1/products`)

```bash
curl -X GET "http://localhost:8069/api/v1/products?category_id=5&in_stock=true&modified_since=2026-10-01&page=1&limit=20" \
  -H "Authorization: Bearer <TU_API_KEY>"
```

### 2. Crear pedido de venta (`POST /api/v1/orders`)

```bash
curl -X POST "http://localhost:8069/api/v1/orders" \
  -H "Authorization: Bearer <TU_API_KEY>" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: pedido-tienda-2026-00091" \
  -d '{
    "rif": "J-31234567-8",
    "external_reference": "WEB-2026-00091",
    "lines": [
      {"default_code": "LAP-001", "quantity": 2},
      {"default_code": "MOU-002", "quantity": 1}
    ]
  }'
```

---

## Supuestos y decisiones de diseño

1. **Estado del pedido creado (`sale` — Confirmado):** Se decidió confirmar automáticamente el pedido (`order.action_confirm()`) al crearse en `POST /api/v1/orders`. Como la compra ya ocurrió en la tienda en línea, confirmarlo de inmediato reserva mercancía y genera automáticamente la orden de entrega (`stock.picking`), permitiendo además que el almacén valide el despacho y dispare el webhook del Tramo C.
2. **Búsqueda de RIF flexible:** Se busca coincidencia por `vat` tanto exacta (`=ilike`) como normalizada sin guiones ni espacios (por ejemplo `J-31234567-8` o `J312345678`) para evitar rechazos por formato de guiones entre la tienda y Odoo.
3. **Stock disponible (`qty_available`):** Se calcula sumando `stock.quant.quantity` en ubicaciones internas (`usage = 'internal'`) de las compañías activas mediante una única consulta SQL agrupada (`GROUP BY product_id`), garantizando que el número de consultas nunca crezca con la cantidad de productos.
4. **Configuración de URL del webhook:** La URL destino del webhook se lee del parámetro del sistema `shop_integration_api.webhook_url` (con valor por defecto `http://localhost:9999/webhook/delivery`).

## Limitaciones conocidas

- Los precios del pedido utilizan la tarifa (`pricelist_id`) asignada al cliente en Odoo o el precio de lista del producto.
- El webhook saliente reintenta hasta `max_retries = 5` veces con backoff exponencial desde la acción planificada cada 5 minutos; una vez agotados los intentos pasa a estado `failed` (pudiendo reintentarse manualmente desde el botón *Reintentar ahora* en *Ventas › Configuración › Integración Tienda › Webhooks salientes*).

## Cómo probarlo

```bash
./odoo test -d prueba_limpia -m shop_integration_api
```
