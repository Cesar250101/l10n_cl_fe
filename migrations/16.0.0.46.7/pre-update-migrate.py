import logging

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning("Pre Migrating l10n_cl_fe from version %s to 16.0.0.46.7" % installed_version)

    cr.execute("""
        UPDATE account_journal 
        SET use_documents = FALSE 
        WHERE use_documents = TRUE 
        AND type NOT IN ('sale', 'purchase')
    """)