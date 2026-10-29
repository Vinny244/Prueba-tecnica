# Reporte de Incidente — Ticket T-200 (`sale_commission`)

- **Cliente:** Comercial Los Andes C.A.
- **Severidad:** Crítica (Bloqueo de confirmación de pedidos para todos los vendedores)
- **Fecha/Hora de detección:** Viernes 5:40 p.m. (tras despliegue de las 12:00 m.)
- **Rama de corrección:** `hotfix/T-200` (lista para abrir Pull Request al publicar el repositorio)

---

## Tramo A — Reproducción, Causa Raíz, Corrección y Prueba

### 1. Cómo se reproduce el error
1. Iniciar sesión con cualquier usuario que pertenezca al grupo **Ventas / Usuario: solo documentos propios** (`sales_team.group_sale_salesman`) y que **no** tenga el grupo **Ventas / Administrador** (`sales_team.group_sale_manager`).
2. Crear un presupuesto (`sale.order`) con al menos un producto y pulsar el botón **Confirmar** (`action_confirm`).
3. **Resultado observado antes de la corrección:** Odoo lanza un cuadro de error de permisos (`AccessError`):
   > *«No tiene permitido acceder a registros de 'Comisión por categoría de producto' (sale.commission.rule). Esta operación está permitida para los siguientes grupos: - Ventas / Administrador»*

### 2. Causa raíz
Se identificaron **dos defectos** introducidos en la actualización desplegada al mediodía:

1. **Causa raíz del bloqueo (`AccessError`):** Al confirmar un pedido (`SaleOrder.action_confirm`), se llama a `line._get_commission_percent()`, el cual ejecuta `self.env["sale.commission.rule"].search(...)`. Sin embargo, en `security/ir.model.access.csv` solo se definió permiso para `sales_team.group_sale_manager` (`1,1,1,1`) y se omitió otorgar permiso de lectura (`perm_read = 1`) al grupo `sales_team.group_sale_salesman`.
2. **Defecto colateral en el cálculo del porcentaje (`self.env.user` vs `self.order_id.user_id`):** En `models/sale_order_line.py` (línea 34), `_get_commission_percent()` devolvía `self.env.user.commission_percent` (el usuario conectado que pulsa el botón *Confirmar*) en lugar de `self.order_id.user_id.commission_percent` (el vendedor asignado al pedido).

### 3. Corrección mínima aplicada
Sin reescribir el módulo ni otorgar privilegios excesivos ni usar `sudo()` injustificado:
- **`__manifest__.py`:** Se incrementó la versión del módulo de `1.1.0` a `1.1.1`.
- **`security/ir.model.access.csv`:** Se añadió la regla `access_sale_commission_rule_salesman` que otorga únicamente permiso de lectura (`perm_read=1, perm_write=0, perm_create=0, perm_unlink=0`) sobre `sale.commission.rule` al grupo `sales_team.group_sale_salesman`.
- **`models/sale_order_line.py`:** Se cambió `return self.env.user.commission_percent` por `return self.order_id.user_id.commission_percent`.
- **`models/sale_order.py`:** En `action_recompute_commissions()` se delegó el cálculo a `line._get_commission_percent()`, corrigiendo la búsqueda de reglas que ignoraba jerarquías de categoría (`parent_of`) y compañía.

### 4. Prueba automatizada
En `tests/test_sale_commission.py`:
- `test_commission_on_confirm_as_salesman`: Ejecuta `order.with_user(self.salesman).action_confirm()` como vendedor sin permisos de administrador (falla con `AccessError` antes de la corrección y pasa después).
- `test_manager_confirming_salesman_order_uses_salesman_commission`: Verifica que si el gerente (`commission_percent = 0.0`) confirma el pedido de un vendedor (`commission_percent = 5.0`), la línea recibe el `5.0 %` del vendedor.
- `test_salesman_cannot_modify_commission_rules`: Comprueba que el vendedor sigue sin poder crear ni modificar reglas en `sale.commission.rule`.

---

## Tramo B — Contención, Identificación del Commit, Despliegue y Comunicación

### 1. Plan de contención en los primeros 15 minutos (antes de tener el hotfix desplegado)
Para que el cliente pueda vender el sábado a las 8:00 a.m. incluso antes de desplegar código:

- **Medida de contención inmediata (vía UI en menos de 2 minutos):**
  1. Entrar como Administrador a *Ajustes › Técnico › Seguridad › Permisos de acceso (`ir.model.access`)*.
  2. Crear un registro temporal:
     - **Nombre:** `CONTENCION-T200 sale.commission.rule read salesman`
     - **Modelo:** `Comisión por categoría de producto (sale.commission.rule)`
     - **Grupo:** `Ventas / Usuario: solo documentos propios`
     - **Permisos:** `[x] Leer`, `[ ] Escribir`, `[ ] Crear`, `[ ] Eliminar`.
- **Por qué es realista y reversible:** Desbloquea de inmediato a todos los vendedores para confirmar sus propios pedidos sin reiniciar el servidor Odoo, sin darles permisos de gerente y sin permitirles editar reglas. Al desplegar el módulo actualizado, el permiso queda gestionado por el CSV oficial y se elimina el registro manual.
- **Riesgos de la contención temporal:**
  1. Los vendedores podrán ver los porcentajes de comisión de las categorías si consultan el modelo por RPC, lo cual es aceptable porque ya ven el `%` aplicado en sus líneas de venta.
  2. Mientras no se despliegue el cambio en `sale_order_line.py`, cada vendedor **debe confirmar sus propios pedidos** (si el gerente confirma el pedido de otro vendedor, se seguirá aplicando el `%` del gerente hasta desplegar el hotfix).

### 2. Qué commit introdujo el error y por qué pasó la revisión
Ejecutando `git log -p -- src/custom/prueba-tecnica/sale_commission`:

- **Commit culpable:** `3f4d73fb2810f1fd650ce1de24557cb9b49624b3` (`[FEAT] sale_commission: porcentaje de comisión por categoría de producto`).
- **Por qué pasó la revisión y las pruebas automatizadas:**
  1. En ese mismo commit se modificó `tests/test_sale_commission.py` quitando `.with_user(user)` del helper `_create_order`:
     ```diff
     - return self.env["sale.order"].with_user(user).create({
     + return self.env["sale.order"].create({
     ```
     y además `order.action_confirm()` se ejecutaba como `self.env.user` (**Administrador / SUPERUSER**), por lo que las pruebas jamás validaron los permisos de `sales_team.group_sale_salesman` al confirmar un pedido.
  2. Además, el autor agregó en `setUpClass` la línea `cls.env.user.commission_percent = 5.0` (exactamente el mismo valor `5.0` que `cls.salesman.commission_percent`), lo que ocultó por completo que `_get_commission_percent()` estaba leyendo `self.env.user.commission_percent` en lugar de `self.order_id.user_id.commission_percent`.

### 3. Pasos para desplegar la corrección y verificarla en producción
1. Abrir y aprobar el Pull Request desde la rama `hotfix/T-200` hacia la rama principal tras verificar que pasa la suite de pruebas en CI/staging.
2. En el servidor de producción, actualizar el código y ejecutar la actualización únicamente del módulo `sale_commission`:
   ```bash
   ./odoo update <INSTANCIA> -d <BD_PRODUCCION> -m sale_commission
   ```
3. Si se aplicó el registro manual de contención en `ir.model.access`, eliminarlo desde *Ajustes › Técnico › Seguridad › Permisos de acceso*.
4. **Verificación post-despliegue en producción:**
   - Iniciar sesión con un usuario de rol **Vendedor** (o probar en ventana privada con usuario vendedor de prueba), confirmar un pedido de prueba y verificar que pasa a estado *Pedido de venta* sin error y calcula la comisión del vendedor.
   - Verificar que en *Ventas › Configuración › Categorías de producto* el vendedor no puede editar el campo *Comisión (%)*.
   - Ejecutar el script de recálculo sobre los pedidos afectados de la tarde del viernes (ver Tramo C).

### 4. Mensaje para el cliente (Administración — Comercial Los Andes C.A.)
> Buenas tardes. Ya identificamos y corregimos el inconveniente que impedía a los vendedores confirmar sus pedidos tras la actualización del mediodía.
> A partir de este momento todos los vendedores pueden confirmar sus pedidos con normalidad para la jornada de mañana sábado desde las 8:00 a.m.
> Además, revisamos los pedidos que el gerente confirmó hoy durante la tarde y ajustamos las comisiones para que cada una quede asignada con el porcentaje de su vendedor correspondiente. Quedamos atentos durante la apertura de mañana para acompañarlos.

---

## Tramo C — Impacto en los Datos, Auditoría y Prevención

### 1. Qué datos quedaron incorrectos por la confirmación del gerente
Durante la tarde del viernes (entre las 12:00 m. y las 5:40 p.m.), el gerente confirmó los pedidos de todos los vendedores. Debido a que `SaleOrderLine._get_commission_percent()` devolvía `self.env.user.commission_percent` (el usuario que ejecutó la confirmación) en lugar de `self.order_id.user_id.commission_percent` (el vendedor del pedido):
- En todas las líneas de pedidos confirmados por el gerente cuyos productos **no** tenían una regla de comisión por categoría, se guardó el **porcentaje de comisión del gerente** (por ejemplo `0 %`) en vez del **porcentaje configurado para el vendedor del pedido** (`order.user_id.commission_percent`), dejando `commission_percent` y `commission_amount` con valores incorrectos en `sale_order_line` y en el reporte `sale.commission.report`.

### 2. Script de solo lectura para listar los registros afectados
Se entregó el script [`scripts/audit_t200_affected_orders.py`](scripts/audit_t200_affected_orders.py), que recorre los pedidos confirmados sin modificar ningún dato y compara el `%` y monto actual de cada línea contra el valor que le corresponde según la categoría o el vendedor del pedido:

```bash
./odoo shell <INSTANCIA> -d <BD_PRODUCCION> < src/custom/prueba-tecnica/sale_commission/scripts/audit_t200_affected_orders.py
```

### 3. Plan paso a paso para corregir los registros afectados en producción
Una vez desplegado el hotfix `T-200` (que también corrige el botón `action_recompute_commissions`):

1. **Paso 1 — Auditar antes de modificar:** Ejecutar `scripts/audit_t200_affected_orders.py` en `odoo shell` y guardar la lista de pedidos y líneas afectadas en un archivo de respaldo.
2. **Paso 2 — Recalcular comisiones de los pedidos afectados:**
   - **Desde la interfaz de Odoo:** Filtrar en *Ventas › Pedidos* los pedidos confirmados el viernes desde las 12:00 m., abrirlos (o seleccionarlos) y pulsar el botón **Recalcular comisiones** (`action_recompute_commissions`).
   - **O desde `odoo shell` en un solo lote transaccional:**
     ```python
     from odoo.addons.sale_commission.scripts.audit_t200_affected_orders import find_affected_order_lines
     rows = find_affected_order_lines(env)
     order_ids = list({r["order_id"] for r in rows})
     orders = env["sale.order"].browse(order_ids)
     orders.action_recompute_commissions()
     env.cr.commit()
     ```
3. **Paso 3 — Verificar:** Volver a correr `scripts/audit_t200_affected_orders.py` y confirmar que el resultado sea `No se encontraron líneas con discrepancias de comisión`.

### 4. Revisión del mismo patrón de error en el resto del módulo
Al auditar todos los archivos de `sale_commission` se encontró un segundo defecto en `models/sale_order.py` dentro del método `action_recompute_commissions`:
- Antes de nuestra corrección, `action_recompute_commissions` hacía:
  ```python
  rules = self.env["sale.commission.rule"].search([])
  rule = rules.filtered(lambda r: r.categ_id == line.product_id.categ_id)
  line.commission_percent = rule[:1].percent if rule else order.user_id.commission_percent
  ```
- **Problemas detectados en ese método:**
  1. Comparaba `r.categ_id == line.product_id.categ_id` por igualdad exacta en vez de jerarquía `parent_of` y sin filtrar por `company_id`, por lo que al pulsar el botón *Recalcular comisiones* en un pedido con productos en subcategorías se perdía la comisión heredada de la categoría padre.
  2. Tampoco podía ser ejecutado por un vendedor porque consultaba `sale.commission.rule` sin permisos de lectura.
- **Solución:** Se unificó `action_recompute_commissions` para que llame directamente a `line._get_commission_percent()`, garantizando una única fuente de verdad.

### 5. Propuesta de prevención para el equipo (Pruebas y Revisión de Código)
1. **Regla obligatoria en pruebas automatizadas:** Prohibido ejecutar flujos de negocio en tests con el usuario `admin` por defecto (`self.env.user`). Toda prueba de acción de negocio (`action_confirm`, botones de formulario, reportes) debe ejecutarse explícitamente con `.with_user(self.salesman)` y `.with_user(self.manager)` usando usuarios creados con `new_test_user` y únicamente los grupos mínimos del rol.
2. **Datos distintos por actor en los fixtures de prueba:** Nunca asignar el mismo valor de prueba a distintos actores (en el commit defectuoso, tanto `cls.salesman.commission_percent` como `cls.env.user.commission_percent` valían `5.0`, enmascarando el uso de `self.env.user` en vez de `order.user_id`).
3. **Checklist de Pull Request en Odoo:** Todo PR que agregue un modelo nuevo (`_name = "..."`) debe incluir en su revisión de seguridad qué grupos solo-lectura lo consultan indirectamente durante flujos transaccionales (como `action_confirm`, `action_post`, etc.).
