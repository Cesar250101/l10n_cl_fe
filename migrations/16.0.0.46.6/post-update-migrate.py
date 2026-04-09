from odoo import SUPERUSER_ID, api
from facturacion_electronica import clase_util as fe_util
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning("Post Migrating l10n_cl_fe from version %s to 16.0.0.46.6" % installed_version)

    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['account.move.line'].search([
        ('discount', '>', 0),
        ('discount_amount', '=', 0)
    ])
    lines.set_discount_amount()
