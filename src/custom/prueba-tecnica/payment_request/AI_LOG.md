# AI_LOG — payment_request

## Herramientas
- Claude 3.5 Sonnet / Antigravity

## Prompts clave (3 a 5)
1. «Genera el modelo payment.request en Odoo 18 con flujo de estados, chatter, grupos de seguridad (solicitante, aprobador, tesorería) y vistas básicas.»
   - Me entregó la estructura inicial. Tuve que agregar a mano la protección en `write()` para que una vez enviada la solicitud nadie pueda editar montos ni conceptos.
2. «Crea un wizard para rechazar con motivo obligatorio en chatter y un wizard para pagar que genere el account.payment.»
   - Hizo los wizards, pero en el de pago no contemplaba diferencias entre monedas ni bloqueaba la posibilidad de que le dieran doble clic al botón de pagar.
3. «Cómo implementar un bloqueo de fila en PostgreSQL para evitar concurrencia en la aprobación/pago de solicitudes.»
   - Me propuso el `SELECT ... FOR UPDATE`, pero olvidó que Odoo cachea los registros en memoria. Le agregué el `invalidate_all()`.

## Lo que la IA hizo mal
- Me propuso usar `FOR UPDATE NOWAIT` en SQL pero sin limpiar la caché del ORM de Odoo. Si dos personas entraban a pagar, la segunda leía `rec.state` desde la memoria de Python (donde todavía decía 'approved') en vez de leer el nuevo estado de PostgreSQL y se saltaba la validación.
- En los tests unitarios, la IA intentó crear pagos contables sin configurar cuentas de banco ni de contrapartida, asumiendo que Odoo las creaba solas. Al correr `./odoo test` en una base limpia fallaba de inmediato con error contable. Tuve que crear una compañía de prueba con su plan de cuentas básico en el `setUpClass`.

## Lo que escribiste tú sin IA
- Todo el documento `ARCHITECTURE.md` justificando con criterio técnico por qué separamos los roles, por qué usamos bloqueo a nivel de base de datos y cómo resolvimos la conversión cambiaria USD a VES a la tasa oficial del día del pago.
- La sección de respuestas a las dudas de Carolina Méndez en el README, resolviendo los vacíos de negocio que traía el requerimiento.
