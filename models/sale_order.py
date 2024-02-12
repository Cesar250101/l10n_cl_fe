# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.fields import Command


class SO(models.Model):
    _inherit = "sale.order"

    def _search_default_journal(self):
        company_id = (self.company_id or self.env.company).id
        domain = [('company_id', '=', company_id), ('type', '=', 'sale')]
        currency_id = self.currency_id.id or self._context.get('default_currency_id')
        if currency_id and currency_id != self.company_id.currency_id.id:
            domain += [('currency_id', '=', currency_id)]
        return self.env['account.journal'].search(domain, limit=1)

    @api.onchange('journal_id')
    @api.depends('journal_id')
    def _get_dc_ids(self):
        for r in self:
            r.document_class_ids = [j.sii_document_class_id.id for j in r.journal_id.journal_document_class_ids.filtered(lambda x: x.sii_document_class_id.document_type == 'invoice')]

    acteco_ids = fields.Many2many("partner.activities", related="partner_invoice_id.acteco_ids",)
    acteco_id = fields.Many2one("partner.activities", string="Partner Activity",)
    referencia_ids = fields.One2many("sale.order.referencias", "so_id", string="Referencias de documento")
    journal_id = fields.Many2one(
        'account.journal',
        default=_search_default_journal,
        domain="[('type', '=', 'sale')]"
    )
    document_class_ids = fields.Many2many(
        "sii.document_class", compute="_get_dc_ids", string="Available Document Classes",
    )
    journal_document_class_id = fields.Many2one(
        "account.journal.sii_document_class",
        string="Documents Type",
        domain="[('sii_document_class_id', '=', document_class_ids)]",
    )
    use_documents = fields.Boolean(
        string="Use Documents?",
    )

    @api.onchange("journal_id")
    def _default_journal_document_class_id(self):
        self.journal_document_class_id = self.env["account.journal.sii_document_class"].search(
            [("journal_id", "=", self.journal_id.id), ("sii_document_class_id.document_type", "in", ['invoice']),], limit=1
        )

    @api.onchange("journal_id")
    def _default_use_documents(self):
        self.use_documents =  bool(self.journal_document_class_id)

    def _prepare_invoice(self):
        self.ensure_one()
        vals = super(SO, self)._prepare_invoice()
        if self.acteco_id:
            vals["acteco_id"] = self.acteco_id.id
        vals['use_documents']= self.use_documents
        if self.use_documents:
            vals.update({
                'journal_id': self.journal_id.id,
                'journal_document_class_id': self.journal_document_class_id.id,
                'document_class_id': self.journal_document_class_id.sii_document_class_id.id,
            })
        vals['referencias'] = []
        for r in self.referencia_ids:
            vals['referencias'].append(Command.create({
                'origen': r.folio,
                'fecha_documento': r.fecha_documento,
                'sii_referencia_TpoDocRef': r.sii_referencia_TpoDocRef.id,
                'motivo': r.motivo,
            }))
        return vals

    @api.depends("order_line.price_total")
    def _amount_all(self):
        """
        Compute the total amounts of the SO.
        """
        for order in self:
            amount_untaxed = amount_tax = 0.0
            for line in order.order_line:
                amount_untaxed += line.price_subtotal
                amount_tax += line.price_tax
            if order.currency_id:
                amount_untaxed = order.currency_id.round(amount_untaxed)
                amount_tax = order.currency_id.round(amount_tax)
            order.update(
                {
                    "amount_untaxed": amount_untaxed,
                    "amount_tax": amount_tax,
                    "amount_total": amount_untaxed + amount_tax,
                }
            )


class SOL(models.Model):
    _inherit = "sale.order.line"

    @api.depends("product_uom_qty", "discount", "price_unit", "tax_id")
    def _compute_amount(self):
        """
        Compute the amounts of the SO line.
        """
        return super(SOL, self)._compute_amount()
        ''' Esto quedará aquí hasta comprobar de que la nueva forma de cálculo de odoo esté bien'''
        for line in self:
            taxes = line.tax_id.compute_all(
                line.price_unit,
                line.order_id.currency_id,
                line.product_uom_qty,
                product=line.product_id,
                partner=line.order_id.partner_shipping_id,
                discount=line.discount,
                uom_id=line.product_uom,
            )
            line.update(
                {
                    "price_tax": sum(t.get("amount", 0.0) for t in taxes.get("taxes", [])),
                    "price_total": taxes["total_included"],
                    "price_subtotal": taxes["total_excluded"],
                }
            )
