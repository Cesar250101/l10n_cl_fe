# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


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
        journal = self.journal_id.id or self.env["account.move"].with_context(default_move_type='out_invoice')._search_default_journal().id
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

    def _create_invoices(self, sale_orders):
        self.ensure_one()
        if self.advance_payment_method == 'delivered':
            return sale_orders.with_context(default_referencias=self._prepare_referencias())._create_invoices(final=self.deduct_down_payments)
        else:
            self.sale_order_ids.ensure_one()
            self = self.with_company(self.company_id)
            order = self.sale_order_ids

            # Create deposit product if necessary
            if not self.product_id:
                self.product_id = self.env['product.product'].create(
                    self._prepare_down_payment_product_values()
                )
                self.env['ir.config_parameter'].sudo().set_param(
                    'sale.default_deposit_product_id', self.product_id.id)

            # Create down payment section if necessary
            if not any(line.display_type and line.is_downpayment for line in order.order_line):
                self.env['sale.order.line'].create(
                    self._prepare_down_payment_section_values(order)
                )

            down_payment_so_line = self.env['sale.order.line'].create(
                self._prepare_so_line_values(order)
            )

            invoice = self.env['account.move'].sudo().create(
                self._prepare_invoice_values(order, down_payment_so_line)
            ).with_user(self.env.uid)  # Unsudo the invoice after creation

            invoice.message_post_with_view(
                'mail.message_origin_link',
                values={'self': invoice, 'origin': order},
                subtype_id=self.env.ref('mail.mt_note').id)

            return invoice
