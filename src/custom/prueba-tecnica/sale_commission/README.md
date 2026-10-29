# Comisiones de vendedores (`sale_commission`)

Calcula la comisión del vendedor en cada línea de pedido de venta y ofrece un análisis mensual por vendedor.

## Tramos completados (Ejercicio 3 — Ticket T-200)

- **Tramo A (Completo):** Reproducción del `AccessError` al confirmar pedidos con un usuario vendedor (`sales_team.group_sale_salesman`), corrección mínima en `security/ir.model.access.csv` (lectura sobre `sale.commission.rule` para el vendedor), corrección en `models/sale_order_line.py` (`self.order_id.user_id.commission_percent` en lugar de `self.env.user.commission_percent`), lectura segura en `models/res_users.py` (`SELF_READABLE_FIELDS`) y pruebas ejecutadas con usuarios reales sin privilegios de administrador.
- **Tramo B (Completo):** Plan de contención en 15 minutos, análisis de riesgos, identificación del commit causante (`3f4d73fb2810f1fd650ce1de24557cb9b49624b3`) y de por qué pasó la revisión, pasos de despliegue y mensaje al cliente documentados en [`INCIDENT.md`](INCIDENT.md).
- **Tramo C (Completo):** Análisis de impacto de los pedidos confirmados por el gerente durante la tarde, script de auditoría de solo lectura en [`scripts/audit_t200_affected_orders.py`](scripts/audit_t200_affected_orders.py), plan de remediación, corrección del patrón duplicado en `action_recompute_commissions` y propuesta de prevención en [`INCIDENT.md`](INCIDENT.md).

## Configuración

- **Porcentaje del vendedor:** Ajustes › Usuarios › pestaña *Comisiones* (solo gerentes de ventas).
- **Porcentaje por categoría (desde la 1.1):** Inventario/Ventas › Configuración › Categorías de producto,
  campo *Comisión (%)*. Si la categoría (o una categoría padre) tiene porcentaje, reemplaza al del vendedor.

## Cómo funciona

- Al confirmar el pedido se fija el porcentaje en cada línea (según la regla de categoría más específica o el porcentaje del vendedor asignado al pedido `order.user_id`) y se calcula la comisión sobre el subtotal sin impuestos.
- El botón *Recalcular comisiones* del pedido vuelve a aplicar los porcentajes vigentes respetando la jerarquía de categorías.
- Ventas › Reportes › *Comisiones*: tabla dinámica y gráfico por vendedor y mes. Cada vendedor ve solo lo suyo.

## Supuestos y limitaciones conocidas

- El porcentaje de comisión se congela en la línea al momento de confirmar el pedido (`action_confirm`) y solo cambia si se ejecuta explícitamente la acción *Recalcular comisiones* (`action_recompute_commissions`).
- Los vendedores tienen acceso de solo lectura a `sale.commission.rule` para que el cálculo automático al confirmar pedidos funcione sin usar `sudo()`; la creación, edición y eliminación de reglas sigue restringida exclusivamente a `sales_team.group_sale_manager`.

## Cómo probarlo

```bash
./odoo test -d prueba_limpia -m sale_commission
```
