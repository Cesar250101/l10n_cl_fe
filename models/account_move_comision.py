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
        string="Tipo de Comisión",
        default="C"
    )
    tasa_comision = fields.Float(string="Tasa de Comision")
    valor_neto_comision = fields.Monetary(string="Neto", currency_field='currency_id',)
    valor_neto_comision_currency = fields.Float(
        compute='_compute_amounts',
        string="Monto neto en moneda",
        store=True)
    valor_exento_comision = fields.Monetary(string="Exento", currency_field='currency_id',)
    valor_exento_comision_currency = fields.Float(
        compute='_compute_amounts',
        string="Monto exento en moneda",
        store=True)
    valor_iva_comision = fields.Monetary(string="IVA",currency_field='currency_id',)
    sequence = fields.Integer("Orden", default=0)
    iva = fields.Many2one(
        'account.tax',
        string="IVA a usar",
        compute='_compute_iva',
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

    _order = 'sequence ASC'
    _sql_constraints = [
        ('name_uniq_per_move', 'unique(name, move_id)', 'Ya existe una línea con esta glosa para el documento')
    ]

    @api.onchange('valor_neto_comision')
    @api.depends('move_id.move_type')
    def _compute_iva(self):
        for r in self:
            type_tax_use = ('sale' if r.move_id.is_sale_document() else 'purchase')
            sii_code = 15 if r.move_id.document_class_id.es_factura_compra() or r.move_id.es_nc_factura_compra() else 14
            r.iva = self.env['account.tax'].search([
                ('sii_code','=', sii_code),
                ('type_tax_use', '=', type_tax_use),
                ('activo_fijo', '=', False) ],
                limit=1)

    @api.depends('valor_neto_comision', 'valor_exento_comision', 'move_id.date')
    def _compute_amounts(self):
        for c in self:
            sign = -1 if c.move_id.is_sale_document() else 1
            currency = c.company_id.currency_id
            c.valor_neto_comision_currency = c.currency_id._convert(
                sign*c.valor_neto_comision,
                currency,
                c.company_id,
                c.move_id.invoice_date or c.move_id.date or fields.Date.context_today(c)
            )
            c.valor_exento_comision_currency = c.currency_id._convert(
                sign*c.valor_exento_comision,
                currency,
                c.company_id,
                c.move_id.invoice_date or c.move_id.date or fields.Date.context_today(c)
            )

    @api.onchange("tasa_comision")
    def calcular_desde_tasa(self):
        if self.tasa_comision:
            resumen = self.move_id._invoice_lines()
            totales = self._totales(resumen)
            self.valor_neto_comision = totales.get('MntNeto', 0) * (self.tasa_comision /100.0)
            self.valor_exento_comision = totales.get('MntExe', 0) * (self.tasa_comision /100.0)

    @api.onchange("valor_neto_comision", 'iva')
    def calcular_iva(self):
        if self.valor_neto_comision and self.iva:
            is_refund = self.move_id.document_class_id.es_nc()
            taxes = self.iva.compute_all(
                self.valor_neto_comision,
                quantity=1,
                currency=self.currency_id,
                is_refund=is_refund,
                handle_price_include=True,
            )
            self.valor_iva_comision = taxes['taxes'][0]['amount']
