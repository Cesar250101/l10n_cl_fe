from odoo import SUPERUSER_ID, api
from facturacion_electronica import clase_util as fe_util
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, installed_version):
    _logger.warning("Post Migrating l10n_cl_fe from version %s to 16.0.0.41.1" % installed_version)

    env = api.Environment(cr, SUPERUSER_ID, {})
    def detect(self, att):
        name = att.name.upper()
        if att.mimetype not in ["text/plain"] or name.find(".XML") == -1 or not att.datas:
            return
        xml = self._parse_xml(att.datas)
        for dte in env['mail.message.dte.document']._get_dtes(xml):
            self.xml_id = att.id
    i = 0
    for r in env['mail.message.dte'].search([('xml_id','=', False)]):
        try:
            if r.mail_id:
                for att in r.mail_id.attachment_ids:
                    detect(r, att)
            else:
                for att in env['ir.attachment'].search([('res_id', '=', r.id), ('res_model', '=', 'mail.message.dte')]):
                    detect(r, att)
        except:
            pass
        if r.document_ids or i> 50:
            continue
        i+=1
        try:
            r.pre_process()
        except:
            pass
