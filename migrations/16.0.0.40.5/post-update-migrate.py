import logging


_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    """Restore the required LATAM identification type on legacy partners."""
    cr.execute(
        """
        UPDATE res_partner
           SET l10n_latam_identification_type_id = data.res_id
          FROM ir_model_data AS data
         WHERE res_partner.l10n_latam_identification_type_id IS NULL
           AND data.module = 'l10n_latam_base'
           AND data.name = 'it_vat'
           AND data.model = 'l10n_latam.identification.type'
        """
    )
    _logger.info(
        "Restored the LATAM identification type on %s partners while upgrading "
        "l10n_cl_fe from version %s.",
        cr.rowcount,
        installed_version,
    )
