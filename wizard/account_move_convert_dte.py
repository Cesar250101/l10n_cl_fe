import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from datetime import datetime
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class AccountMoveConvertDTE(models.TransientModel):
    _name = "account.move.convert.dte"

    @api.model
    def default_get(self, fields):
        res = super(AccountMoveConvertDTE, self).default_get(fields)
        move_ids = self.env['account.move'].browse(self.env.context['active_ids']) if self.env.context.get('active_model') == 'account.move' else self.env['account.move']
        if any(not m.document_class_id.es_voucher() for m in move_ids):
            raise UserError("Solo se pueden retimbrar Vouchers")
        if 'company_id' in fields:
            res['company_id'] = move_ids.company_id.id or self.env.company.id
        if 'move_ids' in fields:
            res['move_ids'] = [(6, 0, move_ids.ids)]
        return res

    move_ids = fields.Many2many(
        'account.move',
        domain=[
            ('state', '=', 'posted'),
            ('document_class_id.dte', '=', False)
        ]
    )
    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Use Specific Journal',
        required=True,
        compute='_compute_journal_id',
        readonly=False,
        store=True,
        check_company=True,
        help='If empty, uses the journal of the journal entry to be reversed.',
    )
    jdc_id = fields.Many2one(
        "account.journal.sii_document_class",
        string="Documents Type",
        check_company=True,
    )
    company_id = fields.Many2one('res.company', required=True, readonly=True)
    warning_message = fields.Html(
        string="Aviso importante",
        compute="_compute_warning_message",
        help="Información sobre el manejo de vouchers convertidos a DTE"
    )

    @api.depends('move_ids')
    def _compute_journal_id(self):
        for record in self:
            if record.journal_id:
                record.journal_id = record.journal_id
            else:
                journals = record.move_ids.journal_id.filtered(lambda x: x.active)
                record.journal_id = journals[0] if journals else None

    @api.onchange('move_ids', 'journal_id')
    def _onchange_move_ids(self):
        domain = []
        if self.move_ids and self.journal_id:
            move_types = self.move_ids.mapped('move_type')
            dc_types = []
            
            if 'out_invoice' in move_types:
                dc_types.extend(['invoice', 'invoice_in'])
            if any(t in move_types for t in ['out_refund', 'in_refund']):
                dc_types.extend(['credit_note', 'debit_note'])
                
            if dc_types:
                domain = [
                    ('journal_id', '=', self.journal_id.id),
                    ('sii_document_class_id.document_type', 'in', dc_types),
                    ('sii_document_class_id.dte', '=', True)
                ]
        return {'domain': {'jdc_id': domain}}

    @api.depends('move_ids')
    def _compute_warning_message(self):
        for record in self:
            message = ""
            voucher_count = 0
            vouchers_por_dia = {}
            
            for move in record.move_ids:
                if move.document_class_id.es_voucher():
                    voucher_count += 1
                    dia = move.invoice_date.strftime('%d/%m/%Y')
                    
                    if dia not in vouchers_por_dia:
                        vouchers_por_dia[dia] = {
                            'cantidad': 0,
                            'total_neto': 0,
                            'total_iva': 0,
                            'total': 0
                        }
                    
                    vouchers_por_dia[dia]['cantidad'] += 1
                    vouchers_por_dia[dia]['total_neto'] += move.amount_untaxed
                    vouchers_por_dia[dia]['total_iva'] += move.amount_tax
                    vouchers_por_dia[dia]['total'] += move.amount_total
            
            if voucher_count > 0:
                detalle_dias = ""
                for dia, totales in vouchers_por_dia.items():
                    detalle_dias += f"""
                        <tr>
                            <td>{dia}</td>
                            <td>{totales['cantidad']}</td>
                            <td>${totales['total_neto']:,.0f}</td>
                            <td>${totales['total_iva']:,.0f}</td>
                            <td>${totales['total']:,.0f}</td>
                        </tr>
                    """
                
                message = f"""
                <div class="alert alert-warning">
                    <h4><i class="fa fa-warning"></i> Aviso Importante - Conversión de Vouchers</h4>
                    <p><strong>Se convertirán {voucher_count} voucher(s) a documentos DTE.</strong></p>
                    
                    <p><strong>Resumen diario de vouchers a convertir:</strong></p>
                    <table class="table table-sm table-striped">
                        <thead>
                            <tr>
                                <th>Fecha</th>
                                <th>Cantidad</th>
                                <th>Total Neto</th>
                                <th>Total IVA</th>
                                <th>Total</th>
                            </tr>
                        </thead>
                        <tbody>
                            {detalle_dias}
                        </tbody>
                    </table>
                    
                    <p><strong>Acción requerida en el SII:</strong></p>
                    <p>Deberá rebajar manualmente estos montos <strong>en cada día correspondiente</strong> 
                    en la propuesta de declaración de IVA en la página del SII, ya que estos vouchers 
                    ahora están respaldados por facturas electrónicas.</p>
                    <p class="text-danger"><strong>IMPORTANTE:</strong> Si no realiza esta rebaja, 
                    <strong>pagará doble IVA</strong> por estos montos.</p>
                    <p><em>Los vouchers convertidos quedarán marcados como respaldados por factura.</em></p>
                </div>
                """
            
            record.warning_message = message

    def convert(self):
        to_send = {}
        for inv in self.move_ids:
            inv.journal_document_class_id = self.jdc_id
            inv.document_class_id = self.jdc_id.sii_document_class_id
            inv.use_documents = True
            inv._set_next_sequence()
            inv.sii_result = "NoEnviado"
            if inv.journal_id.restore_mode or self._context.get("restore_mode", False):
                inv.sii_result = "Proceso"
            else:
                inv._validaciones_uso_dte()
                inv._timbrar()
                to_send.setdefault(inv.company_id, self.env['account.move'])
                to_send[inv.company_id] += inv
        for company, invoices in to_send.items():
            ISCP = self.env["ir.config_parameter"].sudo()
            tiempo_pasivo = datetime.now()
            tipo_trabajo = 'envio'
            self.env["sii.cola_envio"].create(
                {
                    "company_id": company.id,
                    "doc_ids": invoices.ids,
                    "model": "account.move",
                    "user_id": self.env.uid,
                    "tipo_trabajo": tipo_trabajo,
                    "date_time": tiempo_pasivo,
                    "send_email": False
                    if company.dte_service_provider == "SIICERT"
                    or not ISCP.get_param("account.auto_send_email", default=True)
                    else True,
                }
            )
