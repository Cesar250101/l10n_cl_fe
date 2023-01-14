import logging

from odoo import api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


class GlobalDescuentoRecargo(models.Model):
    _name = "account.move.gdr"
    _description = "Linea de descuento global factura"

    def _get_name(self):
        for g in self:
            type = "Descuento"
            if g.type == "R":
                type = "Recargo"
            calculo = "Porcentaje"
            if g.gdr_type == "amount":
                calculo = "Monto"
            g.name = type + "-" + calculo + ": " + (g.gdr_detail or "")

    name = fields.Char(
        compute="_get_name",
        string="Name"
    )
    type = fields.Selection(
        [
            ("D", "Descuento"),
            ("R", "Recargo"),
        ],
        string="Seleccione Descuento/Recargo Global",
        default="D",
        required=True,
    )
    valor = fields.Float(
        string="Descuento/Recargo Global", default=0.00, required=True, digits="Global DR"
    )
    gdr_type = fields.Selection(
        [
            ("amount", "Monto"),
            ("percent", "Porcentaje"),
        ],
        string="Tipo de descuento",
        default="percent",
        required=True,
    )
    gdr_detail = fields.Char(
        string="Razón del descuento",
        oldname="gdr_dtail",)
    aplicacion = fields.Selection(
        [
            ("flete", "Flete"),
            ("seguro", "Seguro"),
        ],
        string="Aplicación del Desc/Rec",)
    impuesto = fields.Selection(
        [
            ("afectos", "Solo Afectos"),
            ("exentos", "Solo Exentos"),
            ("no_facturables", "Solo No Facturables")
        ],
        default="afectos",
    )
    move_id = fields.Many2one(
        "account.move",
        string="Factura",
        copy=False,
    )
    company_id = fields.Many2one(
        related='move_id.company_id', store=True, readonly=True, precompute=True,
        index=True,
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
        check_company=True,
        domain="[('deprecated', '=', False), ('company_id', '=', company_id), ('is_off_balance', '=', False)]",
        default=lambda self: self.move_id.journal_id.default_gd_account_id if self.type == 'D' else self.move_id.journal_id.default_gr_account_id
    )
    amount_untaxed = fields.Float(
        string="Descuento/Recargo Global",
        compute='_compute_gdr_amount',
        store=True)
    amount = fields.Float(
        compute='_compute_gdr_amount',
        string="Monto Total",
        store=True)
    amount_currency = fields.Float(
        compute='_compute_gdr_amount',
        string="Monto Total en moneda",
        store=True)
    taxes = fields.Many2many('account.tax',compute='_compute_gdr_amount',store=True)

    @api.depends('valor', 'gdr_type', 'aplicacion', 'impuesto', 'type')
    def _compute_gdr_amount(self):
        for gdr in self:
            total_currency = 0
            total = 0
            price_subtotal = 0
            taxes = self.env['account.tax']
            if gdr.gdr_type == 'amount':
                gdr.amount = gdr.valor
                gdr.amount_currency = gdr.valor
                continue
            for line in gdr.move_id.invoice_line_ids.filtered(lambda l: not l.is_gd_line and not l.is_gr_line):
                ltaxes = line.tax_ids.filtered(lambda t: t.amount>0 and gdr.impuesto == 'afectos' or t.amount==0 and gdr.impuesto == 'exentos')
                if ltaxes and gdr.gdr_type == 'percent':
                    price_subtotal += line.price_subtotal
                    total += line.price_total
                    total_currency += line.amount_currency
                taxes += ltaxes
            gdr.taxes = taxes
            gdr.amount = total * (gdr.valor /100.0)
            gdr.amount_untaxed = price_subtotal * (gdr.valor /100.0)
            gdr.amount_currency = total_currency * (gdr.valor /100.0)

    @api.onchange('type')
    def set_account(self):
        if not self.account_id:
            if self.type == "D":
                self.account_id = self.move_id.journal_id.default_gd_account_id.id
            else:
                self.account_id = self.move_id.journal_id.default_gr_account_id.id

    def _get_valores(self, tipo="afectos"):
        afecto = 0.00
        for line in self[0].move_id.invoice_line_ids:
            for tl in line.tax_ids:
                if tl.amount > 0 and tipo == "afectos":
                    afecto += line.price_subtotal
                elif tipo == "exentos":
                    afecto += line.price_subtotal
        return afecto

    def get_agrupados(self):
        result = {"D": 0.00, "R": 0.00, "D_exe": 0.00, "R_exe": 0.00}
        for gdr in self:
            if gdr.impuesto == "exentos":
                result[gdr.type + "_exe"] += gdr.amount_untaxed_global_dr
            else:
                result[gdr.type] += gdr.amount_untaxed_global_dr
        return result

    def get_monto_aplicar(self):
        grouped = self.get_agrupados()
        monto = 0
        for key, value in grouped.items():
            valor = value
            if key in ["D", "D_exe"]:
                valor = float(value) * (-1)
            monto += valor
        return monto

    @api.model
    def default_get(self, fields_list):
        ctx = self.env.context.copy()
        # FIX: la accion de Notas de credito pasa por contexto default_type: 'out_refund'
        # pero al existir en esta clase de descuentos un campo llamado type
        # el ORM lo interpreta como un valor para ese campo,
        # pero el valor no esta dentro de las opciones del selection, por ello sale error
        # asi que si no esta en los valores soportados, eliminarlo del contexto
        if "default_type" in ctx and ctx.get("default_type") not in ("D", "R"):
            ctx.pop("default_type")
        values = super(GlobalDescuentoRecargo, self.with_context(ctx)).default_get(fields_list)
        return values
