# AI_LOG — sale_commission

## Herramientas
- Claude 3.5 Sonnet / Antigravity

## Prompts clave (3 a 5)
1. «Revisa el git log de sale_commission y dime qué commit rompió la confirmación de pedidos para los vendedores.»
   - Encontró el commit culpable (`3f4d73fb`) donde agregaron el modelo de reglas pero se les olvidó darle permisos de lectura al vendedor en el CSV.
2. «Qué pasa si el gerente confirmó pedidos en vez del vendedor? Revisa la lógica de cálculo de comisiones.»
   - Analizó el código y se dio cuenta de un bug silencioso gravísimo: el código usaba `self.env.user.commission_percent` en vez del vendedor de la orden (`self.order_id.user_id.commission_percent`). O sea, le pagaban la tasa del gerente a las ventas del vendedor.
3. «Escribe un script de solo lectura para correr en odoo shell que liste los pedidos afectados por este problema.»
   - Me dio el script tabular que compara la comisión guardada contra la que debió ser, sumando la diferencia en dinero sin escribir en la base de datos.

## Lo que la IA hizo mal
- Cuando le pedí solucionar el error de permisos, su primera respuesta fue: *«ponle `.sudo()` a la búsqueda de reglas o dale permisos de administrador al vendedor»*. Es la típica mala práctica que abre agujeros de seguridad.
- También me sugirió modificar `res_users.py` y meter campos a `SELF_READABLE_FIELDS`. Al revisar el código vi que no hacía falta tocar usuarios porque los vendedores ya pueden leer a sus compañeros. La solución real era simplemente poner `1` en lectura sobre `sale.commission.rule` en `ir.model.access.csv`.

## Lo que escribiste tú sin IA
- La decisión de mantener la solución quirúrgica: solo una línea cambiada en el CSV de accesos y una línea en el cálculo de comisión para apuntar al vendedor de la orden.
- El plan de contención de 15 minutos en `INCIDENT.md` explicando cómo resolverlo por interfaz en Odoo sin tener que reiniciar el servidor ni tumbar el servicio a las 5:45 PM, y el correo formal para la gerencia.
