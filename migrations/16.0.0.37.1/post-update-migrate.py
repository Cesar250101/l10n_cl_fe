import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning("Post Migrating l10n_cl_fe from version %s to 16.0.0.37.1" % installed_version)

    env = api.Environment(cr, SUPERUSER_ID, {})
    ''' reparación casos incompletos  posteados'''
    cr.execute('''update account_move set name='/', use_documents=false, document_class_id=NULL, sii_document_number=0 where use_documents AND (document_class_id IS NULL OR sii_document_number = 0) ''')
    '''Reparación manual de name bien formados'''
    cr.execute('''UPDATE account_move am
SET name = CASE
             WHEN am.sii_document_number = 0 THEN (1000000000 + am.id)::text
             WHEN am.use_documents = True THEN dc.doc_code_prefix || am.sii_document_number::text
             ELSE 'no_use' || am.id::text
           END
FROM sii_document_class dc
WHERE am.move_type IN ('in_invoice', 'in_refund', 'out_invoice', 'out_refund')
  AND am.state = 'posted'
  AND am.document_class_id = dc.id''')
    ''' reparación casos facturas proveedor marcadas como factura emisión (pensaron que era compra)'''
    cr.execute('''update account_move am set use_documents=False FROM sii_document_class dc where am.move_type = 'in_invoice' AND am.state='posted' AND dc.id = am.document_class_id AND dc.sii_code not in (46, 56)''')
    ''' reparación casos entradas directas no invoice'''
    cr.execute('''update account_move set name='/' where use_documents = FALSE AND move_type in ('in_invoice', 'in_refund', 'out_invoice', 'out_refund') AND state='posted' ''')
    ''' reparación la mayor parte'''
    moves = env["account.move"].sudo().search([("move_type", "in", ['in_invoice', 'in_refund', 'out_invoice', 'out_refund']), ('state', '=', 'posted'), ('use_documents', '=', False)], order="date ASC")
    moves._compute_name()
