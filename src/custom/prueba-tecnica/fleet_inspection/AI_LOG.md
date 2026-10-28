# AI_LOG — fleet_inspection

## Herramientas
- Claude 3.5 Sonnet / Antigravity

## Prompts clave (3 a 5)
1. «Revisa este módulo de Odoo 16 y dime qué cosas ya no sirven en Odoo 18.»
   - Me listó los cambios típicos: cambiar `<tree>` por `<list>`, quitar `attrs` y `states` por expresiones directas, y reemplazar `name_get` por `_compute_display_name`.
2. «Crea el catálogo fleet.inspection.vehicle.type y un script de migración pre/post para pasar el selection a many2one.»
   - Me armó los scripts, pero en el pre-migrate intentó crear la tabla e insertar los registros a mano en SQL. Tuve que frenarlo porque en Odoo 18 los campos `name` traducidos son columnas `jsonb`, no VARCHAR.
3. «Hazme un test en Odoo para probar la migración con 10.000 registros usando generate_series.»
   - Me dio la base del test insertando con SQL rápido. Lo ajusté para medir el tiempo real en milisegundos y verificar que los 2.500 registros con valor 'otro' no se perdieran.

## Lo que la IA hizo mal
- En `pre-migrate.py` quiso hacer un `INSERT INTO fleet_inspection_vehicle_type` de los tipos base ('carro', 'moto', etc.) antes de que Odoo cargara el XML. Cuando corría la migración, Odoo intentaba cargar su archivo `data.xml` con los mismos códigos y reventaba con error de clave duplicada (`UniqueViolation`).
- Tampoco tomó en cuenta que en Odoo 18 el campo `name` es traducible (`jsonb`). Si metía strings planos en SQL, la interfaz gráfica fallaba al renderizar el nombre del tipo.
- Tuve que reescribir la migración para que `pre-migrate` solo respaldara en una columna temporal `vehicle_type_legacy`, dejar que Odoo cree su tabla y datos limpios, y luego en `post-migrate` actualizar los IDs por lotes con un CTE de SQL.

## Lo que escribiste tú sin IA
- La definición de la estrategia de migración por lotes y la verificación de que ningún registro antiguo de tipo 'otro' se perdiera.
- El documento `MIGRATION_PLAN.md` completo: los comandos de backup con `pg_dump`, las queries de pre y post verificación para el DBA y los dos caminos de rollback.
