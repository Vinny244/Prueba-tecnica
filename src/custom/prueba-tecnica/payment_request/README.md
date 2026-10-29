# Solicitudes de pago con aprobación (`payment_request`)

Módulo para **Odoo 18.0** que digitaliza y controla el ciclo de vida de las solicitudes de pago a proveedores (`borrador → enviada → aprobada → pagada` o `rechazada`), con niveles de aprobación configurables por monto, registro contable en Tesorería (`account.payment`), conversión multimoneda (`USD → VES`), aislamiento multi-compañía y reporte PDF para la carpeta del proveedor.

## Tramos completados

- **Tramo A (Completo):**
  - Modelo `payment.request` con `mail.thread` y `mail.activity.mixin`, secuencia `SP/%(year)s/0001`, proveedor, solicitante (usuario actual por defecto), monto, moneda, fecha, concepto y estado.
  - Grupos *Solicitante*, *Aprobador* y *Tesorería* con reglas de registro (`ir.rule`: el solicitante solo ve sus propias solicitudes).
  - Bloqueo de edición y borrado una vez enviada la solicitud, restricción de monto positivo (`> 0`) y validación en backend para que el solicitante no pueda aprobar ni desde el botón ni invocando el método.
- **Tramo B (Completo):**
  - Niveles de aprobación configurables (`payment.approval.level`: monto mínimo y aprobador).
  - Al enviar la solicitud se asigna automáticamente el aprobador según el monto y se le programa una actividad (`mail.activity`). Solo el aprobador asignado puede aprobar.
  - Asistente de rechazo (`payment.request.reject.wizard`) con motivo obligatorio publicado en el chatter.
  - Asistente de pago (`payment.request.pay.wizard`) que genera y publica el `account.payment` de proveedor vinculado a la solicitud e impide pagar dos veces.
  - Reporte PDF (QWeb) que incluye quién aprobó (`approved_by_id`) y en qué fecha/hora (`approved_date`).
- **Tramo C (Completo):**
  - Pago desde un diario en bolívares (`VES`) de una solicitud registrada en dólares (`USD`) aplicando la tasa de cambio vigente en la fecha del pago.
  - Soporte multi-compañía en `payment.request` y `payment.approval.level` con reglas `ir.rule` globales por `company_ids`.
  - Control de concurrencia mediante bloqueo de fila en base de datos (`SELECT ... FOR UPDATE NOWAIT`) y atomicidad transaccional documentados en [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

## Supuestos y preguntas al cliente (Carolina Méndez — Distribuidora Andina C.A.)

### 1. Qué le preguntaríamos a Carolina antes de cerrar el alcance funcional
1. **Umbral y estructura de aprobación («pagos normales vs. pagos grandes»):**
   - *¿Cuál es el monto exacto en USD a partir del cual un pago pasa de requerir la aprobación del jefe de área a requerir la aprobación de gerencia?*
   - *¿La aprobación depende únicamente del monto (con un único aprobador por tramo), o cada departamento tiene un jefe de área distinto según el empleado que solicita?*
2. **Flujo tras un rechazo:**
   - *Cuando una solicitud se rechaza y el empleado ve el motivo, ¿debe quedar cerrada definitivamente como constancia histórica (obligando a crear una nueva solicitud) o prefieren que el solicitante pueda devolverla a borrador para corregirla?*
3. **Relación con facturas de proveedor (`account.move`):**
   - *¿Estas solicitudes de pago corresponden a anticipos/pagos rápidos sin factura previa cargada en Odoo, o desean vincular opcionalmente una factura de proveedor existente para conciliar el pago automáticamente?*
4. **Tasa de cambio en pagos USD → VES:**
   - *Cuando pagan en bolívares una obligación en dólares, ¿siempre se liquida a la tasa oficial BCV cargada en Odoo en la fecha del pago, o tesorería necesita en algún caso indicar una tasa acordada manualmente en el momento del desembolso?*

### 2. Qué asumimos para avanzar sin su respuesta
1. **Niveles de aprobación configurables por tabla (`payment.approval.level`):** En lugar de fijar un monto en código, creamos el catálogo configurable `payment.approval.level` ordenado por `min_amount desc`. Al enviar la solicitud, el sistema convierte el monto a la moneda base de la compañía y selecciona el nivel activo con el mayor `min_amount` que sea menor o igual al monto solicitado, asignando su `approver_id`.
2. **Segregación de funciones (SoD):** Asumimos que un solicitante nunca puede aprobar su propia solicitud (incluso si también pertenece al grupo Aprobador) y que, cuando existe un aprobador asignado por nivel, únicamente ese aprobador asignado puede aprobar o rechazar la solicitud.
3. **Inmutabilidad de solicitudes enviadas y rechazadas:** Asumimos que una vez enviada (`submitted`, `approved`, `paid`, `rejected`), los datos del pago (`partner_id`, `amount`, `currency_id`, `date`, `concept`) quedan bloqueados para garantizar trazabilidad de auditoría.
4. **Conversión multimoneda con tasa de la fecha de pago:** Cuando la moneda del diario seleccionado por Tesorería (ej. `VES`) difiere de la moneda de la solicitud (ej. `USD`), se utiliza `currency_id._convert(amount, journal_currency, company, payment_date)` tomando la tasa configurada en Odoo para la fecha exacta del pago.

---

## Limitaciones conocidas

- La asignación de aprobador se basa en el escalafón de montos por compañía (`payment.approval.level`). Si en una compañía aún no se han configurado niveles de aprobación, cualquier miembro del grupo *Aprobador* (distinto al solicitante) puede aprobar la solicitud.

## Cómo probarlo

```bash
./odoo test -d prueba_limpia -m payment_request
```
