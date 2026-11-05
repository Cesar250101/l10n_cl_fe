import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    """Deja compartido el producto marcador ``l10n_cl_fe.no_product``.

    El producto se crea sin ``company_id`` (``data/product.xml``), pero en bases donde
    alguien asignó una compañía queda invisible para el resto por la regla
    multi-compañía: ``account.move.copy()`` no lo encontraba al crear la línea de la
    nota de crédito "Corrige texto", la línea quedaba sin producto ni descripción y el
    DTE se generaba sin ``<Detalle>`` (rechazo del XSD con "Element Referencia: This
    element is not expected. Expected is ( {...}Detalle )").
    """
    _logger.warning("Post Migrating l10n_cl_fe from version %s to 16.0.0.40.7" % installed_version)

    env = api.Environment(cr, SUPERUSER_ID, {})
    plantilla = env.ref("l10n_cl_fe.no_product", raise_if_not_found=False)
    if plantilla and plantilla.company_id:
        _logger.warning(
            "l10n_cl_fe.no_product (%s) estaba asignado a la compañía %s: se deja compartido",
            plantilla.id,
            plantilla.company_id.display_name,
        )
        plantilla.write({"company_id": False})
