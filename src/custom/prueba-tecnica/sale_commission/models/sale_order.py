from odoo import models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        res = super().action_confirm()
        for line in self.order_line.filtered(lambda l: not l.display_type):
            line.commission_percent = line._get_commission_percent()
        return res

    def action_recompute_commissions(self):
        """Vuelve a calcular la comisión de las líneas, por ejemplo después de cambiar las reglas."""
        for order in self.filtered(lambda o: o.state == "sale"):
            for line in order.order_line.filtered(lambda l: not l.display_type):
                line.commission_percent = line._get_commission_percent()
        return True
