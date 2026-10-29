"""Script de solo lectura para auditar pedidos afectados por el incidente T-200.

Ejecución en Odoo Shell (no realiza ningún cambio ni escritura en base de datos):
    ./odoo shell prueba-tecnica -d <NOMBRE_BD> < src/custom/prueba-tecnica/sale_commission/scripts/audit_t200_affected_orders.py
"""


def find_affected_order_lines(env, date_from=None, date_to=None):
    """Identifica líneas de pedidos confirmados cuyo % de comisión difiere del esperado.

    Durante la tarde del incidente T-200, el gerente confirmó pedidos en nombre de los
    vendedores y `_get_commission_percent()` tomó `self.env.user.commission_percent`
    (el porcentaje del gerente) en lugar de `self.order_id.user_id.commission_percent`
    (el porcentaje del vendedor asignado al pedido).

    Esta función es 100 % de solo lectura: no modifica ningún registro.
    """
    domain = [("state", "=", "sale")]
    if date_from:
        domain.append(("date_order", ">=", date_from))
    if date_to:
        domain.append(("date_order", "<=", date_to))

    orders = env["sale.order"].search(domain, order="date_order asc, id asc")
    discrepancies = []

    for order in orders:
        for line in order.order_line.filtered(lambda l: not l.display_type):
            expected_percent = line._get_commission_percent()
            has_rule = bool(
                env["sale.commission.rule"].search_count([
                    ("categ_id", "parent_of", line.product_id.categ_id.id),
                    ("company_id", "in", [False, line.company_id.id]),
                ])
            )
            source = "category_rule" if has_rule else "salesman"

            current_percent = line.commission_percent
            if round(current_percent, 4) != round(expected_percent, 4):
                expected_amount = line.price_subtotal * expected_percent / 100.0
                discrepancies.append({
                    "order_id": order.id,
                    "order_name": order.name,
                    "date_order": str(order.date_order),
                    "salesman_id": order.user_id.id,
                    "salesman_name": order.user_id.name,
                    "line_id": line.id,
                    "product_name": line.product_id.display_name,
                    "price_subtotal": line.price_subtotal,
                    "current_percent": current_percent,
                    "expected_percent": expected_percent,
                    "current_amount": line.commission_amount,
                    "expected_amount": expected_amount,
                    "difference_amount": round(expected_amount - line.commission_amount, 2),
                    "rule_source": source,
                })

    return discrepancies


def print_audit_report(env, date_from=None, date_to=None):
    rows = find_affected_order_lines(env, date_from=date_from, date_to=date_to)
    print("=" * 100)
    filtro_str = f"desde {date_from}" if date_from else "todos los pedidos confirmados"
    print(f"AUDITORÍA T-200 (SOLO LECTURA) — Líneas con comisión afectada ({filtro_str})")
    print("=" * 100)
    if not rows:
        print("No se encontraron líneas con discrepancias de comisión.")
        return rows

    print(
        f"{'Pedido':<12} {'Vendedor':<22} {'Línea ID':<10} "
        f"{'% Actual':>10} {'% Esperado':>12} {'Com. Actual':>14} {'Com. Esperada':>14}"
    )
    print("-" * 100)
    total_diff = 0.0
    affected_orders = set()
    for r in rows:
        affected_orders.add(r["order_id"])
        total_diff += r["difference_amount"]
        print(
            f"{r['order_name']:<12} {r['salesman_name'][:20]:<22} {r['line_id']:<10} "
            f"{r['current_percent']:>9.2f}% {r['expected_percent']:>11.2f}% "
            f"{r['current_amount']:>14.2f} {r['expected_amount']:>14.2f}"
        )
    print("-" * 100)
    print(
        f"Total pedidos afectados: {len(affected_orders)} | "
        f"Total líneas afectadas: {len(rows)} | "
        f"Diferencia neta en comisiones: {total_diff:+.2f}"
    )
    print("=" * 100)
    return rows


if "env" in globals():
    print_audit_report(env)  # noqa: F821
