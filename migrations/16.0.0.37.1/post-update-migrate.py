import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning("Post Migrating l10n_cl_fe from version %s to 16.0.0.37.1" % installed_version)

    env = api.Environment(cr, SUPERUSER_ID, {})
    '''Reparar facturas mal importadas '''
    cr.execute('''UPDATE account_move am
      SET name='/'
      FROM account_journal aj
      WHERE am.journal_id=aj.id AND aj.type IN ('sale', 'purchase') ''')
    cr.execute('''UPDATE account_move am
      SET use_documents=True
      FROM sii_document_class dc
      WHERE am.use_documents is False
      AND document_class_id IS NOT NULL
      AND sii_document_number IS NOT NULL
      AND sii_document_number != 0 AND dc.dte AND move_type IN ('out_invoice', 'out_refund') AND am.document_class_id=dc.id ''')
    cr.execute('''UPDATE account_move am
      SET use_documents=True
      FROM sii_document_class dc
      WHERE am.use_documents is FALSE AND document_class_id IS NOT NULL AND sii_document_number IS NOT NULL AND sii_document_number != 0 AND dc.sii_code = 46 AND move_type IN ('in_invoice') AND am.document_class_id=dc.id ''')
    ''' reparación casos incompletos  posteados'''
    cr.execute('''UPDATE account_move
      SET use_documents=False
      WHERE use_documents AND document_class_id is NULL AND  (sii_document_number IS NULL OR sii_document_number = 0) AND move_type IN ('in_invoice', 'in_refund', 'out_invoice', 'out_refund') AND state IN ('posted', 'cancel') ''')
    cr.execute('''UPDATE account_move
      SET use_documents=False, document_class_id=NULL
      WHERE use_documents AND (sii_document_number IS NULL OR sii_document_number = 0) AND move_type IN ('in_invoice', 'in_refund', 'out_invoice', 'out_refund') AND state IN ('posted', 'cancel') ''')
    cr.execute('''UPDATE account_move
      SET use_documents=FALSE, document_class_id=NULL, sii_document_number = NULL, journal_document_class_id=NULL
      WHERE use_documents AND (document_class_id IS NULL OR sii_document_number IS NULL OR sii_document_number = 0) ''')
    cr.execute('''UPDATE account_move
      SET journal_document_class_id = NULL
      WHERE use_documents is FALSE AND journal_document_class_id IS NOT NULL AND move_type IN ('in_invoice', 'in_refund') ''')
    cr.execute('''UPDATE account_move am
SET name = CASE
             WHEN am.sii_document_number = 0 THEN (1000000000 + am.id)::text
             WHEN am.use_documents = True THEN dc.doc_code_prefix || am.sii_document_number::text
             ELSE 'no_use' || am.id::text
           END
FROM sii_document_class dc
WHERE am.move_type IN ('in_invoice', 'in_refund', 'out_invoice', 'out_refund')
  AND am.state = 'posted'
  AND am.document_class_id = dc.id
  AND am.use_documents ''')
    ''' reparación casos facturas proveedor marcadas como factura emisión (pensaron que era compra)'''
    cr.execute('''UPDATE account_move am
      SET use_documents=FALSE
      FROM sii_document_class dc
      WHERE am.move_type = 'in_invoice' AND am.state='posted' AND dc.id = am.document_class_id AND dc.sii_code NOT IN (46, 56)''')
    ''' reparación la mayor parte'''
    moves = env["account.move"].sudo().search([("journal_id.type", "in", ["sale", "purchase"]), ('state', 'in', ('posted', 'cancel'))], order="date ASC")
    moves._compute_name()
