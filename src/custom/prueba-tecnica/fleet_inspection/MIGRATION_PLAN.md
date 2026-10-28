# Plan de Migración en Producción — `fleet_inspection` (`18.0.1.0.0` → `18.0.2.0.0`)

Este documento detalla el procedimiento operativo paso a paso para ejecutar la actualización del módulo `fleet_inspection` en la base de datos de producción del cliente, convirtiendo el campo `vehicle_type` (`Selection`) al catálogo relacional `fleet.inspection.vehicle.type` (`vehicle_type_id`, `Many2one`) sin pérdida de información.

---

## 1. Estrategia de lotes y registro de tiempos

La migración procesa las inspecciones en lotes de **`BATCH_SIZE = 1000`** registros directamente en PostgreSQL mediante CTEs (`WITH batch AS (...) UPDATE ...`), sin instanciar recordsets en Python:

| Fase | Operación | Comportamiento esperado para 10.000 registros |
| :--- | :--- | :--- |
| Respaldo previo | `scripts/odoo_backup backup <INSTANCIA> -d <BD> -p ./backups` | Genera archivo `.zip` (BD + filestore) antes de tocar el esquema |
| Pre-migración (`pre-migrate.py`) | Respaldo de `vehicle_type` en `vehicle_type_legacy` en lotes de 1.000 | 10 lotes SQL de 1.000 filas; registra el tiempo real en ms en el log |
| Actualización ORM Odoo (`./odoo update`) | Creación de tabla `fleet_inspection_vehicle_type` (`jsonb`), carga de XML semilla y vistas | Sin warnings de deprecación ni colisiones de unicidad |
| Post-migración (`post-migrate.py`) | Asignación de `vehicle_type_id` desde `vehicle_type_legacy` en lotes de 1.000 | 10 lotes SQL de 1.000 filas (`0` filas en una 2.ª corrida idempotente) |

---

## 2. Respaldo previo (Backup)

Antes de ejecutar cualquier cambio en producción, generar un respaldo completo de la base de datos y su filestore usando el script oficial del repositorio:

```bash
# 1. Generar respaldo completo (base de datos + filestore en ZIP)
scripts/odoo_backup backup <INSTANCIA> -d <NOMBRE_BD_PRODUCCION> -p ./backups

# Alternativa directa con pg_dump dentro del contenedor de base de datos:
docker compose -f docker-compose.generated.yml exec db-<DB_SERVICE> \
    pg_dump -U odoo -Fc <NOMBRE_BD_PRODUCCION> > ./backups/pre_fleet_inspection_18_0_2.dump
```

Verificar que el archivo generado exista y tenga tamaño mayor a cero:

```bash
ls -lh ./backups/
```

---

## 3. Verificación previa (Pre-check)

Conectar a `psql` en modo lectura y registrar el conteo exacto de inspecciones por cada valor de `vehicle_type` antes de actualizar:

```sql
-- 3.1 Total de inspecciones existentes
SELECT COUNT(*) AS total_inspecciones FROM fleet_inspection;

-- 3.2 Distribución exacta por tipo de vehículo actual (Selection)
SELECT COALESCE(vehicle_type, 'NULL') AS tipo_actual,
       COUNT(*) AS cantidad
  FROM fleet_inspection
 GROUP BY COALESCE(vehicle_type, 'NULL')
 ORDER BY tipo_actual;
```

Guardar el resultado de esta consulta para compararlo exactamente en el paso 5.

---

## 4. Ejecución de la migración

1. Desplegar el código de la versión `18.0.2.0.0` de `fleet_inspection`.
2. Ejecutar la actualización del módulo con Odoo deteniendo el proceso al finalizar (`--stop-after-init`):

```bash
./odoo update <INSTANCIA> -d <NOMBRE_BD_PRODUCCION> -m fleet_inspection
```

3. Revisar en la salida del registro (`logs`) las dos líneas de confirmación:
   - `INFO ... Iniciando pre-migración de fleet_inspection...`
   - `INFO ... Post-migración de fleet_inspection: X inspecciones migradas en Y lotes (... ms).`

> **Nota sobre idempotencia:** Si el comando se interrumpe o se ejecuta una segunda vez, tanto `pre-migrate.py` como `post-migrate.py` son 100% idempotentes: usan `ON CONFLICT (code) DO NOTHING` en el catálogo y filtran únicamente registros donde `vehicle_type_id IS NULL` o difiera del código legado en lotes de 1.000 registros.

---

## 5. Verificación posterior (Post-check)

Ejecutar las siguientes consultas SQL para confirmar que ninguna inspección quedó sin tipo ni con un tipo distinto al que tenía:

```sql
-- 5.1 Verificar que NO exista ninguna inspección sin tipo (debe devolver 0)
SELECT COUNT(*) AS inspecciones_sin_tipo
  FROM fleet_inspection
 WHERE vehicle_type_id IS NULL;

-- 5.2 Comparar conteo por código en el nuevo catálogo contra el conteo previo del paso 3.2
SELECT vt.code AS codigo_catalogo,
       vt.name AS nombre_catalogo,
       COUNT(fi.id) AS cantidad
  FROM fleet_inspection fi
  JOIN fleet_inspection_vehicle_type vt ON vt.id = fi.vehicle_type_id
 GROUP BY vt.code, vt.name
 ORDER BY vt.code;

-- 5.3 Verificar que NO exista ninguna discrepancia entre vehicle_type_legacy y el nuevo catálogo (debe devolver 0)
SELECT COUNT(*) AS discrepancias
  FROM fleet_inspection fi
  JOIN fleet_inspection_vehicle_type vt ON vt.id = fi.vehicle_type_id
 WHERE fi.vehicle_type_legacy IS NOT NULL
   AND fi.vehicle_type_legacy IN ('motorcycle', 'car', 'truck', 'other')
   AND vt.code != fi.vehicle_type_legacy;
```

**Criterio de éxito:**
- `inspecciones_sin_tipo = 0`
- `discrepancias = 0`
- Los conteos por código (`motorcycle`, `car`, `truck`, `other`) coinciden exactamente con los registrados en el Paso 3.2.

---

## 6. Plan de reversión (Rollback)

En caso de requerir volver a la versión `18.0.1.0.0`:

### Opción A — Reversión rápida en SQL + código (si no hubo nuevas transacciones críticas)
Dado que `pre-migrate.py` preserva los valores en `vehicle_type_legacy` sin eliminar la información original:

```sql
BEGIN;

-- Restaurar la columna vehicle_type desde el catálogo actual o desde vehicle_type_legacy
ALTER TABLE fleet_inspection ADD COLUMN IF NOT EXISTS vehicle_type VARCHAR;

UPDATE fleet_inspection fi
   SET vehicle_type = COALESCE(vt.code, fi.vehicle_type_legacy, 'car')
  FROM fleet_inspection_vehicle_type vt
 WHERE vt.id = fi.vehicle_type_id;

UPDATE ir_module_module
   SET latest_version = '18.0.1.0.0'
 WHERE name = 'fleet_inspection';

COMMIT;
```

Posteriormente, hacer checkout al tag/commit de `18.0.1.0.0` y ejecutar `./odoo update <INSTANCIA> -d <NOMBRE_BD_PRODUCCION> -m fleet_inspection`.

### Opción B — Restauración completa del respaldo del Paso 2
Si se prefiere restaurar el estado exacto previo a la ventana de mantenimiento:

```bash
./odoo restore <INSTANCIA> -z ./backups/<ARCHIVO_BACKUP.zip> -d <NOMBRE_BD_PRODUCCION>
```
