# Decisiones de Arquitectura — `payment_request` (Tramo C)

Este documento describe las decisiones técnicas adoptadas en el módulo `payment_request` para resolver concurrencia en aprobaciones y pagos, conversión multimoneda `USD → VES`, aislamiento multi-compañía y atomicidad transaccional.

---

## 1. Control de concurrencia con bloqueo en base de datos (`FOR UPDATE NOWAIT`)

### El problema del chequeo solo en Python
En un entorno con múltiples workers de Odoo, validar únicamente en Python (`if self.state != 'submitted': raise UserError(...)`) es vulnerable a condiciones de carrera (*Time-Of-Check to Time-Of-Use — TOCTOU*):
- Dos transacciones concurrentes $T_1$ y $T_2$ leen la misma fila en estado `submitted` antes de que cualquiera de las dos haga `commit`.
- Ambas pasan la validación en Python y ejecutan su lógica (por ejemplo, creando dos `account.payment` duplicados al pagar o registrando dos aprobaciones simultáneas).

### Nuestra solución en PostgreSQL (`_lock_rows_for_update`)
Tanto en `action_approve()`, `_apply_rejection()` como en `_register_supplier_payment()` se ejecuta primero:

```sql
SELECT id, state FROM payment_request WHERE id IN %s FOR UPDATE NOWAIT
```

seguido de `self.env.invalidate_all()` para forzar al ORM a releer el estado fresco desde la base de datos dentro del bloqueo:
1. **Si dos usuarios actúan al mismo milisegundo:** La primera transacción adquiere el bloqueo exclusivo de fila (`ROW SHARE / FOR UPDATE`) en PostgreSQL; la segunda recibe de inmediato `psycopg2.OperationalError` (`could not obtain lock on row`) gracias a `NOWAIT`, que capturamos y transformamos en un `UserError` claro para el usuario sin dejar conexones colgadas esperando.
2. **Si la segunda transacción entra justo después del commit de la primera:** Tras adquirir el bloqueo e invalidar la caché del ORM, relee `self.state` directamente desde la tabla y detecta que el estado ya cambió a `approved` o `paid`, abortando la operación con `UserError`.

---

## 2. Atomicidad transaccional al registrar el pago (`account.payment`)

En `_register_supplier_payment()`, la creación del pago contable (`account.payment`), su publicación (`action_post()`) y la transición de la solicitud a `state = 'paid'` se ejecutan dentro de un `SAVEPOINT` explícito (`with self.env.cr.savepoint():`):
- Si `Payment.create()` o `payment.action_post()` lanza cualquier excepción (por ejemplo, cuenta contable faltante, período cerrado o validación bancaria), PostgreSQL revierte automáticamente el savepoint completo.
- Como resultado, la solicitud `payment.request` **nunca queda en estado `paid`** ni con un `payment_id` huérfano si el asiento contable no se completó con éxito.

---

## 3. Conversión multimoneda (`USD → VES`) a la tasa de la fecha de pago

En Venezuela es habitual recibir facturas o solicitudes de pago nominadas en dólares (`USD`) y liquidarlas desde cuentas bancarias nacionales en bolívares (`VES`):
- El método `_register_supplier_payment(journal, payment_date)` determina la moneda destino del desembolso como `target_currency = journal.currency_id or self.company_id.currency_id`.
- Si `self.currency_id != target_currency`, delega en el motor nativo de tasas de Odoo:
  ```python
  payment_amount = self.currency_id._convert(
      self.amount, target_currency, self.company_id, payment_date
  )
  ```
- Esto garantiza el redondeo monetario oficial de la moneda destino (`target_currency.rounding`) y el uso exacto de la tasa vigente en `res.currency.rate` para la fecha `payment_date` y la compañía de la solicitud.

---

## 4. Aislamiento Multi-compañía

- Tanto `payment.request` como `payment.approval.level` definen `_check_company_auto = True` y un campo `company_id` obligatorio indexado.
- Se declararon dos reglas de registro globales (`global = True` en `ir.rule`) con dominio `[('company_id', 'in', company_ids)]` sobre ambos modelos. En Odoo, las reglas globales se intersectan con `AND` frente a las reglas de grupo, garantizando que ningún usuario (ni siquiera un Aprobador o Tesorería) pueda ver o modificar solicitudes o niveles de una compañía a la que no tiene acceso.
