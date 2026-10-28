# AI_LOG — shop_integration_api

## Herramientas
- Claude 3.5 Sonnet / Antigravity

## Prompts clave (3 a 5)
1. «Escribe un controlador en Odoo 18 para GET /api/v1/products que filtre por categoría, solo stock y modificados desde fecha.»
   - Me dio la estructura básica de la ruta y los parámetros, pero calculaba el stock llamando a `product.qty_available` en un bucle. Le pedí optimizarlo para que consultara el stock en conjunto y no hiciera una consulta por cada producto.
2. «Crea el POST /api/v1/orders con autenticación Bearer por API key nativa de Odoo y errores 422 con formato {"error": {"code", "field", "message"}}»
   - Armó el JSON y las validaciones de RIF y líneas, pero se equivocó en cómo llamar a `res.users.apikeys` en Odoo 18. Tuve que corregir la llamada a `_check_credentials` con parámetros nombrados y meter un savepoint para que los logs se guarden incluso si el pedido falla.
3. «Añade idempotencia con cabecera Idempotency-Key y que devuelva 409 si mandan el mismo key con otro body.»
   - Me dio el modelo con el hash SHA-256. Le ajusté la lógica para responder con el mismo JSON cacheado si era idéntico.
4. «Cómo disparar un webhook al validar el albarán en button_validate sin trabar al usuario si la tienda no responde.»
   - Al principio quería hacer una llamada HTTP directa en el botón con timeout. Lo quité de inmediato y armé una cola en base de datos con un cron y reintentos, para que el usuario en almacén no se quede colgado.

## Lo que la IA hizo mal
- Me dijo que usara `.sudo()` sobre `res.users.apikeys` y que llamara a `_generate(description, login)`. En Odoo 18 eso tira error de una porque `res.users.apikeys` tiene `_allow_sudo_commands = False` y `_check_credentials` exige parámetros nombrados (`key=...`, `scope=...`).
- Quiso meter el webhook síncrono dentro del botón de validar entrega. Me di cuenta pensando en el almacenero: si la tienda web se cae o tarda 5 segundos, la pantalla de Odoo se congela. Tuve que cambiarlo a un modelo en cola con cron.
- Quiso poner `openapi: 3.0.3` usando la clave `webhooks:`, pero Swagger/OpenAPI solo soporta webhooks nativos a partir de la versión 3.1.0.

## Lo que escribiste tú sin IA
- La decisión de negocio de confirmar el pedido automáticamente (`action_confirm()`) al crearlo y la redacción de los supuestos y limitaciones en el README.
- La definición de los códigos de error de la API (409 y 422) y la revisión manual de seguridad para verificar que ninguna clave API se guarde en los logs de la base de datos.
