import logging

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning("Pre Migrating l10n_cl_fe from version %s to 16.0.0.42.4" % installed_version)

    cr.execute("""UPDATE ir_model_data SET module='l10n_cl_fe'
        WHERE name IN ('UF', 'UTM', 'OTR') AND model='res.currency'
        """)
