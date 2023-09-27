from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

class AccountMoveComision(models.Model):
    _name = 'account.move.comision'

    name = fields.Char(string="Glosa")
    move_id = fields.Many2one(
        'account.move',
        string="Movimiento"
    )
    tipo_movimiento = fields.Selection([
        ('C','Comisiones'),
        ('O','Otros')
        ],
        string="Tipo de Comisión"
    )
    tasa_comision = fields.Float(string="Tasa de Comision")
    valor_neto_comision = fields.Monetary(string="Valor Neto de Comision", currency_field='currency_id',)
    valor_neto_comision_currency = fields.Float(
        compute='_compute_amounts',
        string="Monto neto en moneda",
        store=True)
    valor_exento_comision = fields.Monetary(string="Valor de Comsiones Exentas", currency_field='currency_id',)
    valor_exento_comision_currency = fields.Float(
        compute='_compute_amounts',
        string="Monto exento en moneda",
        store=True)
    valor_iva_comision = fields.Monetary(string="Valor de Comisiones Afectas",currency_field='currency_id',)
    sequence = fields.Integer("Orden", default=0)
    iva = fields.Many2one(
        'account.tax',
        string="IVA a usar",
        default=lambda self: self.env['account.tax'].search([('sii_code','=', 14), ('type_tax_use', '=', 'sale'), ('activo_fijo', '=', False) ], limit=1).id,
        domain="[('sii_code','=', 14), ('type_tax_use', '=', 'sale'), ('activo_fijo', '=', False)]"
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        string='Currency',
        related='move_id.currency_id',
    )
    account_id = fields.Many2one(
        'account.account',
        string='Account',
        required=True,
        check_company=True,
        domain="[('deprecated', '=', False), ('company_id', '=', company_id), ('is_off_balance', '=', False)]",
        default=lambda self: self.move_id.journal_id.default_comision_account_id
    )
    company_id = fields.Many2one(
        related='move_id.company_id', store=True, readonly=True, precompute=True,
        index=True,
    )

    _order = 'sequence'

    def _compute_amounts(self):
        for c in self:
            currency = c.company_id.currency_id
            c.valor_exento_comision_currency = c.currency_id._convert(
                c.valor_neto_comision,
                currency_id,
                c.company_id,
                c.move_id.invoice_date
            )
            c.valor_neto_comision_currency = c.currency_id._convert(
                c.valor_exento_comision,
                currency_id,
                c.company_id,
                c.move_id.invoice_date
            )


    @api.onchange("tasa_comision")
    def calcular_desde_tasa(self):
        if self.tasa_comision:
            resumen = self.move_id._invoice_lines()
            totales = self._totales(resumen)
            self.valor_neto_comision = totales.get('MntNeto', 0) * (self.tasa_comision /100.0)
            self.valor_exento_comision = totales.get('MntExe', 0) * (self.tasa_comision /100.0)

    @api.onchange("valor_neto_comision")
    def calcular_iva(self):
        if self.valor_neto_comision and not self.valor_iva_comision and self.iva:
            is_refund = self.move_id.document_class_id.es_nc()
            taxes = self.iva.compute_all(
                self.valor_neto_comision,
                quantity=1,
                currency=self.currency_id,
                is_refund=is_refund,
            )
            self.valor_iva_comision = taxes['taxes'][0]['amount']
