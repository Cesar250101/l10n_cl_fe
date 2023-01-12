import logging

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


class AccountMoveReversal(models.TransientModel):
    """
    Account move reversal wizard, it cancel an account move by reversing it.
    """
    _inherit = "account.move.reversal"

    def _dominio_nc(self):
        move_ids = self.env['account.move'].browse(self.env.context['active_ids']) if self.env.context.get('active_model') == 'account.move' else self.env['account.move']
        docs = []
        for doc in move_ids:
            if doc.document_class_id.sii_code in [110]:
                if doc.move_type in ['out_invoice', 'in_invoice']:
                    docs.append(112)
                docs.append(111)
            else:
                if doc.move_type in ['out_invoice', 'in_invoice']:
                    docs += [60, 61]
                docs += [55, 56]
        return [
            ('sii_code', 'in', docs),
            ('dte', '=', True),
        ]

    @api.model
    def default_get(self, fields):
        res = super(AccountMoveReversal, self).default_get(fields)
        move_ids = self.env['account.move'].browse(self.env.context['active_ids']) if self.env.context.get('active_model') == 'account.move' else self.env['account.move']
        if any(doc.document_class_id for doc in move_ids):
            ncs = self.env['sii.document_class'].search(
                self._dominio_nc())
            res.update({
                'refund_method': 'cl_refund',
                'tipo_nota': ncs[-1].id
            })
        return res

    tipo_nota = fields.Many2one(
            'sii.document_class',
            string="Tipo De nota",
            domain=lambda self: self._dominio_nc(),
        )
    refund_method = fields.Selection(
        selection_add=[("cl_refund", 'Rectificativa modo chileno')],
        ondelete={'cl_refund': 'cascade'}
    )
    cl_refund = fields.Selection(
            [
                ('1', 'Anula Documento de Referencia'),
                ('2', 'Corrige texto Documento Referencia'),
                ('3', 'Corrige montos'),
            ],
            default='1',
            string='Refund Method',
            required=True,
            help='Refund base on this type. You can not Modify and Cancel if the invoice is already reconciled',
        )

    @api.onchange("cl_refund")
    def _set_template(self):
        if self.cl_refund == "2":
            self.reason = _("Dice:   Debe Decir: ")

    def _prepare_default_reversal(self, move):
        vals = super(AccountMoveReversal, self)._prepare_default_reversal(move)
        if self.refund_method == 'cl_refund':
            jdc = self.env['account.journal.sii_document_class'].search(
                    [
                        ('sii_document_class_id.sii_code','=', self.tipo_nota.sii_code),
                        ('journal_id', '=', (self.journal_id or move.journal_id).id),
                    ],
                    limit=1,
                )
            referencias = []
            i = 1
            referencias.append([0,0, {
                    'sequence': i,
                    'origen': move.sii_document_number,
                    'sii_referencia_TpoDocRef': move.document_class_id.id,
                    'sii_referencia_CodRef': self.cl_refund,
                    'motivo': self.reason or move.name,
                    'fecha_documento': move.invoice_date
                }])
            vals.update({
                'journal_document_class_id': jdc.id,
                'document_class_id': jdc.sii_document_class_id.id,
                'use_documents': True,
                'referencias': referencias,
            })
        return vals


    def reverse_moves(self):
        self.ensure_one()
        if self.refund_method != 'cl_refund':
            return super(AccountMoveReversal, self).reverse_moves()
        moves = self.move_ids
        mode = self.cl_refund
        # Create default values.
        default_values_list = []
        for move in moves:
            default_values_list.append(self._prepare_default_reversal(move))

        batches = [
            [self.env['account.move'], [], True],   # Moves to be cancelled by the reverses.
            [self.env['account.move'], [], False],  # Others.
        ]
        for move, default_vals in zip(moves, default_values_list):
            is_auto_post = bool(default_vals.get('auto_post'))
            is_cancel_needed = not is_auto_post and self.refund_method in ('cancel', 'modify')
            batch_index = 0 if is_cancel_needed else 1
            batches[batch_index][0] |= move
            batches[batch_index][1].append(default_vals)

        # Handle reverse method.
        moves_to_redirect = self.env['account.move']
        for moves, default_values_list, is_cancel_needed in batches:
            new_moves = moves._reverse_moves(default_values_list, cancel=is_cancel_needed)

            if self.refund_method == 'modify':
                moves_vals_list = []
                for move in moves.with_context(include_business_fields=True):
                    moves_vals_list.append(move.copy_data({'date': self.date if self.date_mode == 'custom' else move.date})[0])
                new_moves = self.env['account.move'].create(moves_vals_list)
            moves_to_redirect |= new_moves

        self.new_move_ids = moves_to_redirect

        # Create action.
        action = {
            'name': _('Reverse Moves'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
        }
        if len(moves_to_redirect) == 1:
            action.update({
                'view_mode': 'form',
                'res_id': moves_to_redirect.id,
            })
        else:
            action.update({
                'view_mode': 'tree,form',
                'domain': [('id', 'in', moves_to_redirect.ids)],
            })
        return action
