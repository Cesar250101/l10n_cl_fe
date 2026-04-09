import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

def migrate(cr, installed_version):
    env = api.Environment(cr, SUPERUSER_ID, {})

    _logger.warning("Pre Migrating l10n_cl_fe from version %s to 16.0.0.46.7" % installed_version)

    query = """
        UPDATE account_move
        SET use_documents = FALSE
        WHERE use_documents = TRUE
        AND document_class_id IS NOT NULL
        AND document_class_id IN (
            SELECT id FROM sii_document_class
            WHERE dte = FALSE
        )
    """

    cr.execute(query)
    affected_rows = cr.rowcount

    _logger.info(f"Migración completada: {affected_rows} registros actualizados")
