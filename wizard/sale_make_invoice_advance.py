# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class SaleAdvancePaymentInvReference(models.TransientModel):
    _name = "sale.advance.payment.inv.referencia"
    _description = "Línea de Referencias DTE para Pedidos de Venta desde Wizard"

    fecha_documento = fields.Date(string="Fecha Documento", required=True,)
    folio = fields.Char(string="Folio Referencia",)
    sii_referencia_TpoDocRef = fields.Many2one("sii.document_class", string="Tipo de Documento SII",)
    motivo = fields.Char(string="Motivo",)
    wiz_id = fields.Many2one("sale.advance.payment.inv", ondelete="cascade", index=True, copy=False, string="Documento",)


class SaleAdvancePaymentInv(models.TransientModel):
    _inherit = "sale.advance.payment.inv"

    def _default_journal_document_class_id(self):
        if not self.env["ir.model"].search([("model", "=", "sii.document_class")]):
            return False
        journal = self.journal_id.id or self.env["account.move"]._search_default_journal().id
        jdc = self.env["account.journal.sii_document_class"].search(
            [("journal_id", "=", journal), ("sii_document_class_id.document_type", "in", ['invoice']),], limit=1
        )
        return jdc

    def _default_use_documents(self):
        if self._default_journal_document_class_id():
            return True
        return False

    @api.onchange('journal_id')
    @api.depends('journal_id')
    def _get_dc_ids(self):
        for r in self:
            r.document_class_ids = [j.sii_document_class_id.id for j in r.journal_id.journal_document_class_ids.filtered(lambda x: x.sii_document_class_id.document_type == 'invoice')]


    journal_id = fields.Many2one(
        'account.journal',
        default=lambda self: self.env['account.move'].with_context(default_move_type='out_invoice')._search_default_journal(),
        domain="[('type', '=', 'sale')]"
    )
    document_class_ids = fields.Many2many(
        "sii.document_class", compute="_get_dc_ids", string="Available Document Classes",
    )
    journal_document_class_id = fields.Many2one(
        "account.journal.sii_document_class",
        string="Documents Type",
        default=lambda self: self._default_journal_document_class_id(),
        domain="[('sii_document_class_id', '=', document_class_ids)]",
    )
    use_documents = fields.Boolean(
        string="Use Documents?",
       default=lambda self: self._default_use_documents(),
    )

    @api.model
    def _default_referencias(self):
        refs = []
        if self._context.get('active_model') == 'sale.order' and self._context.get('active_id', False):
            so = self.env['sale.order'].browse(self._context.get('active_id'))
            for r in so.referencia_ids:
                refs.append((0, 0, {
                    'fecha_documento': r.fecha_documento,
                    'folio': r.folio,
                    'sii_referencia_TpoDocRef': r.sii_referencia_TpoDocRef.id,
                    'motivo': r.motivo
                }))
        return refs

    referencia_ids = fields.One2many(
        'sale.advance.payment.inv.referencia',
        'wiz_id',
        string="Referencias DTE",
        default=_default_referencias
    )

    def _prepare_referencias(self):
        return [(0,0,{
            'fecha_documento': r.fecha_documento,
            'origen': r.folio,
            'sii_referencia_TpoDocRef': r.sii_referencia_TpoDocRef.id,
            'motivo': r.motivo
        }) for r in self.referencia_ids]

    def _prepare_invoice_values(self, order, name, amount, so_line):
        vals = super(SaleAdvancePaymentInv, self)._prepare_invoice_values(order, name, amount, so_line)
        return vals

    def create_invoices(self):
        sale_orders = self.env['sale.order'].browse(self._context.get('active_ids', []))
        if self.advance_payment_method == 'delivered':
            sale_orders.with_context(default_referencias=self._prepare_referencias())._create_invoices(final=self.deduct_down_payments)
        else:
            # Create deposit product if necessary
            if not self.product_id:
                vals = self._prepare_deposit_product()
                self.product_id = self.env['product.product'].create(vals)
                self.env['ir.config_parameter'].sudo().set_param('sale.default_deposit_product_id', self.product_id.id)

            sale_line_obj = self.env['sale.order.line']
            for order in sale_orders:
                amount, name = self._get_advance_details(order)

                if self.product_id.invoice_policy != 'order':
                    raise UserError(_('The product used to invoice a down payment should have an invoice policy set to "Ordered quantities". Please update your deposit product to be able to create a deposit invoice.'))
                if self.product_id.type != 'service':
                    raise UserError(_("The product used to invoice a down payment should be of type 'Service'. Please use another product or update this product."))
                taxes = self.product_id.taxes_id.filtered(lambda r: not order.company_id or r.company_id == order.company_id)
                tax_ids = order.fiscal_position_id.map_tax(taxes, self.product_id, order.partner_shipping_id).ids
                analytic_tag_ids = []
                for line in order.order_line:
                    analytic_tag_ids = [(4, analytic_tag.id, None) for analytic_tag in line.analytic_tag_ids]

                so_line_values = self._prepare_so_line(order, analytic_tag_ids, tax_ids, amount)
                so_line = sale_line_obj.create(so_line_values)
                self._create_invoice(order, so_line, amount)
        if self._context.get('open_invoices', False):
            return sale_orders.action_view_invoice()
        return {'type': 'ir.actions.act_window_close'}
