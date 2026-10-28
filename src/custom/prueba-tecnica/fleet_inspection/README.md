# Inspecciones de vehículos (`fleet_inspection`)

Módulo migrado de **Odoo 16.0** a **Odoo 18.0** (`18.0.2.0.0`) que registra inspecciones de vehículos con checklist de puntos críticos, control de vencimiento a los 7 días, reporte PDF y catálogo configurable de tipos de vehículo (`fleet.inspection.vehicle.type`).

## Tramos completados

- **Tramo A (Completo):** Migración integral de Odoo 16 a Odoo 18.0 (manifiesto, ORM Python, vistas XML `<list>`, expresiones directas sin `attrs`/`states`, `<chatter/>`, `ir.cron` sin `numbercall`, QWeb `t-out` y pruebas).
- **Tramo B (Completo):** Conversión del tipo de vehículo a catálogo (`fleet.inspection.vehicle.type`, `Many2one`) con datos semilla (`motorcycle`, `car`, `truck`, `other`), scripts en `migrations/18.0.2.0.0/` (`pre-migrate.py` y `post-migrate.py`) y prueba automatizada que verifica la conservación de todos los tipos (incluido «Otro»).
- **Tramo C (Completo):** Migración idempotente por lotes (`BATCH_SIZE = 1000`) mediante CTEs en PostgreSQL sin cargar registros en memoria de Python, prueba de 10.000 inspecciones y plan operativo de migración para producción en [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md).

---

## Tabla de cambios de versión (Odoo 16 → Odoo 18.0)

| Archivo / Componente | Qué cambió | Por qué | Cómo lo resolviste |
| :--- | :--- | :--- | :--- |
| `__manifest__.py` | Versión `16.0.1.0.0` → `18.0.1.0.0` (Tramo A) → `18.0.2.0.0` (Tramo B) y ubicación a `src/custom/prueba-tecnica/fleet_inspection`. | En Odoo 17+ el prefijo de serie en el manifiesto debe coincidir con la versión del servidor (`18.0`), de lo contrario impide iniciar o instalar el módulo. | Se movió el módulo al directorio de addons activos, se actualizó el prefijo a `18.0` y se declaró `data/fleet_inspection_vehicle_type_data.xml` y `views/fleet_inspection_vehicle_type_views.xml`. |
| `models/fleet_inspection.py` (`states` en campos) | Se eliminaron `readonly=True, states={"draft": [("readonly", False)]}` de `vehicle_id` y `vehicle_type`. | En Odoo 17+ se eliminó el parámetro `states` en la definición de campos Python (`fields.*`), generando error/advertencia al cargar el modelo. | Se removió `states` del modelo Python y se trasladó la condición `readonly="state != 'draft'"` directamente a los campos en la vista formulario (`views/fleet_inspection_views.xml`). |
| `models/fleet_inspection.py` (`create`) | `@api.model def create(self, vals)` → `@api.model_create_multi def create(self, vals_list)`. | En Odoo 17+ sobrescribir `create` sin `@api.model_create_multi` emite advertencia de obsolescencia y degrada la creación en lote. | Se decoró con `@api.model_create_multi`, iterando sobre `vals_list` y consultando una sola vez `fleet.inspection.item` para precargar las líneas del checklist. |
| `models/fleet_inspection.py` (`name_get`) | `def name_get(self)` → `@api.depends(...) def _compute_display_name(self)`. | En Odoo 17+ `name_get()` quedó obsoleto y fue sustituido por el campo computado `display_name` a través de `_compute_display_name()`. | Se implementó `_compute_display_name()` dependiendo de `name`, `vehicle_id.license_plate` y `vehicle_id.name`, asignando `inspection.display_name = f"{label} - {vehicle_ref}"`. |
| `data/ir_cron_data.xml` | Se eliminaron `<field name="numbercall">-1</field>` y `<field name="doall" eval="False"/>`. | En Odoo 18.0 los campos `numbercall` y `doall` fueron eliminados del modelo `ir.cron`; mantenerlos provoca fallo de validación XML al instalar. | Se conservaron únicamente los campos vigentes en Odoo 18.0 (`name`, `model_id`, `state`, `code`, `interval_number`, `interval_type`, `active`). |
| `views/fleet_inspection_views.xml` y `views/fleet_inspection_item_views.xml` (`<tree>` → `<list>`) | Etiquetas `<tree>` → `<list>` y `view_mode` `tree,form` → `list,form`. | En Odoo 18.0 la vista de lista pasó a llamarse `<list>` en lugar de `<tree>` (Sección 9 del instructivo). | Se reemplazaron todas las etiquetas `<tree>` por `<list>` y los `view_mode` en las acciones de ventana. |
| `views/fleet_inspection_views.xml` (`attrs` y `states`) | Eliminación de `attrs="{...}"` y `states="..."` en botones, alertas y campos. | Desde Odoo 17 se eliminaron `attrs` y `states` en XML en favor de expresiones Python directas en `invisible`, `readonly` y `required`. | Se convirtieron los botones a `invisible="state != 'draft'"`, la alerta a `invisible="not is_overdue"`, los campos a `readonly="state in ('approved', 'rejected')"` y `required="state == 'in_progress'"`. |
| `views/fleet_inspection_views.xml` (`column_invisible` y `<chatter/>`) | `invisible="1"` dentro de `<list>` → `column_invisible="True"`, y `<div class="oe_chatter">` → `<chatter/>`. | En Odoo 17/18 ocultar una columna de tabla requiere `column_invisible="True"`, y en Odoo 18 el bloque chatter se declara con la etiqueta `<chatter/>`. | Se reemplazó `invisible="1"` en columnas de `<list>` por `column_invisible="True"` y el bloque chatter por `<chatter/>`. |
| `report/fleet_inspection_report.xml` | `t-esc` → `t-out`. | En QWeb de Odoo 17/18 `t-esc` está obsoleto en favor de `t-out` (que escapa automáticamente salvo `Markup`). | Se sustituyeron todas las directivas `t-esc` por `t-out`. |
| `tests/test_fleet_inspection.py` | Importación desde `odoo.tests` y verificación sobre `inspection.display_name`. | `name_get()` fue reemplazado por `display_name` en Odoo 17/18. | Se actualizó `test_display_name_includes_plate` para verificar `self.assertIn("AB123CD", inspection.display_name)` y se añadieron pruebas de migración y lote de 10.000 registros. |

---

## Generación de 10.000 inspecciones y medición de tiempos (Tramo C)

Para verificar el rendimiento y consumo constante de memoria sin cargar los registros en el worker de Python:

1. **Cómo se generan los datos:** En `test_migration_batch_10000_inspections` (`tests/test_fleet_inspection.py`) se utiliza `generate_series(1, 10000)` en PostgreSQL insertando 10.000 registros en `fleet_inspection` distribuidos equitativamente (2.500 `motorcycle`, 2.500 `car`, 2.500 `truck`, 2.500 `other`) con `vehicle_type_id = NULL` y el código legado en `vehicle_type_legacy`.
2. **Estrategia por lotes:** El script `migrations/18.0.2.0.0/post-migrate.py` procesa bloques de `BATCH_SIZE = 1000` usando una CTE (`WITH batch AS (SELECT fi.id, ... LIMIT 1000) UPDATE fleet_inspection ...`), manteniendo el consumo de memoria RAM en $O(1)$ y ejecutando exactamente 10 lotes de actualización para 10.000 registros.
3. **Registro de tiempos (`elapsed_ms`):** `migrate_vehicle_types_in_batches` mide con `time.perf_counter()` el tiempo real de ejecución en milisegundos y lo emite en el log de Odoo (`INFO ... Post-migración de fleet_inspection: 10000 inspecciones migradas en 10 lotes (X.XX ms)`). En una segunda corrida consecutiva (prueba de idempotencia), realiza `0` actualizaciones en `0` lotes.

## Supuestos y limitaciones

- Se conserva la columna `vehicle_type_legacy` en la tabla `fleet_inspection` tras la migración como respaldo auditable y para permitir reversión inmediata sin pérdida de datos (ver [`MIGRATION_PLAN.md`](MIGRATION_PLAN.md)).
- Cualquier valor huérfano o no reconocido en `vehicle_type` se asigna de forma segura al registro de catálogo `other` («Otro») mediante `COALESCE(vt.id, vt_other.id)` para garantizar que ninguna inspección quede sin tipo.

## Cómo probarlo

```bash
./odoo test prueba-tecnica -d prueba_limpia -m fleet_inspection
```
