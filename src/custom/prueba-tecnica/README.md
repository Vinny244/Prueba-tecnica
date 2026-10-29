# Prueba técnica — Desarrollador Odoo (Odoo 18.0)

- **Versión de Odoo declarada:** `18.0` (`ODOO_VERSION=18.0` en `.env`)
- **Módulos entregados en esta carpeta (`src/custom/prueba-tecnica/`):**

| Ejercicio | Módulo | Tramos completados | Documentación incluida |
| :--- | :--- | :--- | :--- |
| **1. Integración con API para tienda en línea** | [`shop_integration_api`](shop_integration_api/) | **A, B y C** | [`README.md`](shop_integration_api/README.md), [`openapi.yaml`](shop_integration_api/openapi.yaml), [`AI_LOG.md`](shop_integration_api/AI_LOG.md) |
| **2. Migración del módulo de inspecciones** | [`fleet_inspection`](fleet_inspection/) | **A, B y C** | [`README.md`](fleet_inspection/README.md), [`MIGRATION_PLAN.md`](fleet_inspection/MIGRATION_PLAN.md), [`AI_LOG.md`](fleet_inspection/AI_LOG.md) |
| **3. Ticket urgente de última hora (T-200)** | [`sale_commission`](sale_commission/) | **A, B y C** *(rama `hotfix/T-200`)* | [`README.md`](sale_commission/README.md), [`INCIDENT.md`](sale_commission/INCIDENT.md), [`AI_LOG.md`](sale_commission/AI_LOG.md), [`scripts/audit_t200_affected_orders.py`](sale_commission/scripts/audit_t200_affected_orders.py) |
| **4. Solicitudes de pago con aprobación** | [`payment_request`](payment_request/) | **A, B y C** | [`README.md`](payment_request/README.md), [`ARCHITECTURE.md`](payment_request/ARCHITECTURE.md), [`AI_LOG.md`](payment_request/AI_LOG.md) |

## Levantar el entorno y ejecutar las pruebas

1. Configurar `instances.json` apuntando a **Odoo 18.0** y a `src/custom/prueba-tecnica`:

   ```json
   "prueba-tecnica": {
     "odoo_version": "18.0",
     "external_port": 8069,
     "database": "v18",
     "odoo_config": "18.0_default",
     "overwrite_odoo_config": {
       "addons": ["src/custom/prueba-tecnica"],
       "dev_mode": true
     }
   }
   ```

2. Construir y levantar: `./odoo build` y `./odoo start`.
3. Ejecutar toda la suite de pruebas sobre una base de datos limpia:

   ```bash
   ./odoo test -d prueba_limpia \
     -m shop_integration_api,fleet_inspection,sale_commission,payment_request
   ```
