import base64
import logging
import os
import tempfile
from datetime import datetime
import pytz
import requests

from odoo import api, fields, models, tools
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)


def update_next_by_caf(self, folio, caf):
    if not self.sii_document_class_id:
        return 0
    if not caf:
        _logger.warning("No quedan folios disponibles CAFs para %s disponibles" % caf.name)
        return 0
    folio = caf.folio_actual
    if self.implementation == "no_gap":
        self.flush_recordset(['number_next'])
        number_next = self.number_next
        self._cr.execute("SELECT number_next FROM %s WHERE id=%%s FOR UPDATE NOWAIT" % self._table, [self.id])
        self._cr.execute("UPDATE %s SET number_next=%%s WHERE id=%%s " % self._table, (folio, self.id))
        self.invalidate_recordset(['number_next'])
    else:
        self.sudo().write({"number_next": folio})
    return folio

class IRSequence(models.Model):
    _inherit = "ir.sequence"

    def get_qty_available(self, folio=None):
        folio = int(folio or self.number_next_actual)
        try:
            cafs = self.get_caf_files(folio)
        except Exception as ex:
            _logger.warning("Problema al obtener cafs",
            exc_info=True)
            cafs = self.env["dte.caf"]
        available = 0
        if folio > 0:
            for c in cafs:
                available += c.qty_available
            if available <= self.nivel_minimo:
                alert_msg = "Nivel bajo de folios del CAF para {}, quedan {} folios. Recuerde verificar su token apicaf.cl".format(
                    self.sii_document_class_id.name, available,
                )
                #self.env["bus.bus"]._sendone(
                #    self.env.user.partner_id,
                #    'ir.sequence/display_notification',
                #    {"title": "Alerta sobre Folios", "message": alert_msg, "url": "res_config", "type": "dte_notif"}
                #)
        return available

    def write(self, vals):
        result = super(IRSequence, self).write(vals)
        if self:
            for i in self.dte_caf_ids:
                i.company_id = self.company_id.id
        return result

    @api.onchange("dte_caf_ids", "number_next_actual")
    def _qty_available(self):
        for i in self:
            i.qty_available = 0
            if i.is_dte and i.sii_document_class_id:
                i.qty_available = i.get_qty_available()

    sii_document_class_id = fields.Many2one("sii.document_class", string="Tipo de Documento",)
    is_dte = fields.Boolean(string="IS DTE?", default=False)
    dte_caf_ids = fields.One2many("dte.caf", "sequence_id", string="DTE CAF",)
    qty_available = fields.Integer(string="Quantity Available", compute="_qty_available")
    nivel_minimo = fields.Integer(string="Nivel Mínimo de Folios", default=5,)  # @TODO hacerlo configurable
    autoreponer_caf = fields.Boolean(string="Reposición Automática de CAF", default=False)
    autoreponer_cantidad = fields.Integer(string="Cantidad de Folios a Reponer", default=2)
    folios_sin_usar = fields.Integer(string="Folios sin usar", compute="set_folios_sin_usar", store=True)

    @api.model
    def check_cafs(self):
        self._cr.execute("SELECT id FROM dte_caf WHERE expiration_date <= NOW() and cantidad_folios_sin_usar > 0")
        for r in self.env["dte.caf"].sudo().browse([x[0] for x in self._cr.fetchall()]):
            try:
                r.expirar_folios()
            except:
                _logger.warning("no se pudo auto anular")
            try:
                r.auto_anular()
            except:
                _logger.warning("no se pudo auto anular")
        self._cr.execute("SELECT id FROM ir_sequence WHERE autoreponer_caf")
        for r in self.env["ir.sequence"].sudo().browse([x[0] for x in self._cr.fetchall()]):
            if r and r.qty_available < r.nivel_minimo:
                try:
                    r.solicitar_caf()
                except Exception as e:
                    _logger.warning(
                        "Error al solictar folios a secuencia {}: {}".format(
                            r.sii_document_class_id.name, str(e)),
                        exc_info=True
                    )

    @api.onchange('sii_document_class_id')
    def _auto_set_is_dte(self):
        self.is_dte = self.sii_document_class_id.dte

    def solicitar_caf(self):
        if self.qty_available == self.nivel_minimo:
            self.inspeccionar_folios_sin_usar()
            if self.qty_available >= self.nivel_minimo:
                return
        firma = self.env.user.sudo().get_digital_signature(self.company_id)
        wiz_caf = self.env["dte.caf.apicaf"].create(
            {"company_id": self.company_id.id, "sequence_id": self.id, "firma": firma.id,}
        )
        wiz_caf.conectar_api()
        alert_msg = False
        if not wiz_caf.id_peticion:
            alert_msg = "Problema al conectar con apicaf.cl" + " - " + wiz_caf.message 
        else:
            cantidad = self.autoreponer_cantidad
            if wiz_caf.api_max_autor > 0 and cantidad > wiz_caf.api_max_autor:
                cantidad = wiz_caf.api_max_autor
            elif wiz_caf.api_max_autor == 0:
                self.autoreponer_caf = False
                alert_msg = (
                    "El SII no permite solicitar más CAFs para %s, consuma los %s folios disponibles o verifique situación tributaria en www.sii.cl"
                    % (self.sii_document_class_id.name, wiz_caf.api_folios_disp)
                )
        if alert_msg:
            _logger.warning(alert_msg)
            self.env["bus.bus"]._sendone(
                self.env.user.partner_id,
                'ir.sequence/display_notification',
                {"title": "Alerta sobre Folios", "message": alert_msg, "url": "res_config", "type": "dte_notif",},
            )
            return
        wiz_caf.cant_doctos = cantidad
        wiz_caf.obtener_caf()

    @api.depends('dte_caf_ids.cantidad_folios_sin_usar')
    def set_folios_sin_usar(self):
        for r in self:
            folios_sin_usar = 0
            for caf in r.dte_caf_ids:
                folios_sin_usar += caf.cantidad_folios_sin_usar
            r.folios_sin_usar = folios_sin_usar

    def obtener_folios_sin_usar(self):
        folios = []
        for caf in self.dte_caf_ids:
            folios += caf.obtener_folios_sin_usar()
        return folios

    #@api.onchange('qty_available')
    def inspeccionar_folios_sin_usar(self):
        for caf in self.dte_caf_ids:
            caf.inspeccionar_folios_sin_usar()

    def get_folio(self, number_next=False):
        caf = self.env['dte.caf'].search([
            ('sequence_id', '=', self.id),
            ('final_nm', '>=', number_next or self.number_next),
        ],
        order='folio_actual ASC',
        limit=1)
        if not caf:
            if not self.dte_caf_ids:
                return 0
            caf = self.dte_caf_ids[0]
            if int(self.number_next) == caf.final_nm:
                return 0
        # caf.compute_folio_actual()
        # folio_actual = caf.folio_actual
        # if folio_actual != int(self.number_next):
        #     update_next_by_caf(self, folio_actual, caf)
        # if caf.qty_available == 0:
        #     if caf == self.dte_caf_ids[0]:
        #         return 0
        #     return self.get_folio(folio_actual+1)
        return self.number_next

    def time_stamp(self, formato="%Y-%m-%dT%H:%M:%S"):
        tz = pytz.timezone("America/Santiago")
        return datetime.now(tz).strftime(formato)

    def get_caf_file(self, folio=False, decoded=True):
        folio = int(folio or self.number_next_actual)
        caffiles = self.get_caf_files(folio)
        msg = """No Hay caf para el documento: {}, está fuera de rango . \
Solicite un nuevo CAF en el sitio www.sii.cl""".format(
            folio
        )
        if not caffiles:
            raise UserError(
                _(
                    """No hay caf disponible para el documento %s folio %s. \
Por favor solicite y suba un CAF en el portal del SII o Utilice la opción \
obtener folios en la secuencia (usando apicaf.cl)."""
                    % (self.name, folio)
                )
            )
        for caffile in caffiles:
            if folio >= caffile.start_nm and folio <= caffile.final_nm:
                if caffile.expiration_date:
                    if fields.Date.context_today(self) > caffile.expiration_date:
                        msg = "CAF Vencido. %s" % msg
                        continue
                if decoded:
                    return caffile.decode_caf()
                return base64.b64encode(caffile.caf_string.encode("ISO-8859-1"))
        raise UserError(_(msg))

    def get_caf_files(self, folio=None):
        """
            Devuelvo caf actual y futuros
        """
        folio = int(folio or self.number_next_actual)
        if not self.dte_caf_ids:
            _logger.warning(
                """No hay CAFs disponibles para la secuencia de %s. Por favor \
suba un CAF o solicite uno en el SII."""
                % (self.name)
            )
            return self.dte_caf_ids
        cafs = self.dte_caf_ids.filtered(
                lambda caf: folio <= caf.final_nm
            ).sorted(key=lambda caf: caf.start_nm)
        return cafs

    def _next_do(self):
        if self.is_dte:
            folio = self.get_folio()
            if folio == 0:
                raise UserError(
                    """No hay más folios disponibles para el documento %s. \
Por favor solicite y suba un CAF en el portal del SII o Utilice la opción \
obtener folios en la secuencia (usando apicaf.cl)."""
                    % (self.name)
                )
            return self.get_next_char(folio)
        return super(IRSequence, self)._next_do()
    

#     def consultar_folios_disponibles_sii(self, tipo_dte):
#         company = self.company_id or self.env.company
#         firma = self.env.user.sudo().get_digital_signature(company)
#         if not firma:
#             raise UserError(_("No se encontró una firma digital válida para la empresa %s") % company.name)

#         rut_certificado = firma.subject_serial_number
#         password = firma.password or ''
#         rut_empresa = (company.vat or '').replace('CL', '').strip()
#         ambiente = 1 if company.dte_service_provider == 'SII' else 0
#         base_url_servicios = company.simple_api_servidor

#         url = "{}/api/folios/get/{}".format(base_url_servicios, tipo_dte)

#         pfx_bytes = base64.b64decode(firma.file_content)
#         tmp_dir = tempfile.mkdtemp()
#         pfx_path = os.path.join(tmp_dir, firma.name)
#         try:
#             with open(pfx_path, 'wb') as f:
#                 f.write(pfx_bytes)

#             payload = {
#                 'input': '''{
#    "RutCertificado":"%s",
#    "Password":"%s",
#    "RutEmpresa":"%s",
#    "Ambiente":%s
# }''' % (rut_certificado, password, rut_empresa, ambiente)
#             }

#             headers = {
#                 'Authorization': company.simple_api_token,
#             }

#             with open(pfx_path, 'rb') as pfx_file:
#                 files = [
#                     ('files', (firma.name, pfx_file, 'application/octet-stream'))
#                 ]
#                 response = requests.post(url, headers=headers, data=payload, files=files, timeout=30)
#         finally:
#             if os.path.exists(pfx_path):
#                 os.remove(pfx_path)
#             os.rmdir(tmp_dir)
#         _logger.info("Folios SII - Status: %s, Response: %s", response.status_code, response.text)
#         return response.text

#     def solicitar_folios_sii(self, tipo_dte, cantidad_folios):
#         company = self.company_id or self.env.company
#         firma = self.env.user.sudo().get_digital_signature(company)
#         if not firma:
#             raise UserError(_("No se encontró una firma digital válida para la empresa %s") % company.name)

#         rut_certificado = firma.subject_serial_number
#         password = firma.password or ''
#         rut_empresa = (company.vat or '').replace('CL', '').strip()
#         ambiente = 1 if company.dte_service_provider == 'SII' else 0
#         base_url_servicios = company.simple_api_servidor

#         url = "{}/api/folios/get/{}/{}".format(base_url_servicios, tipo_dte, cantidad_folios)

#         pfx_bytes = base64.b64decode(firma.file_content)
#         tmp_dir = tempfile.mkdtemp()
#         pfx_path = os.path.join(tmp_dir, firma.name)
#         try:
#             with open(pfx_path, 'wb') as f:
#                 f.write(pfx_bytes)

#             payload = {
#                 'input': '''{
#    "RutCertificado":"%s",
#    "Password":"%s",
#    "RutEmpresa":"%s",
#    "Ambiente":%s
# }''' % (rut_certificado, password, rut_empresa, ambiente)
#             }

#             headers = {
#                 'Authorization': company.simple_api_token,
#             }

#             with open(pfx_path, 'rb') as pfx_file:
#                 files = [
#                     ('files', (firma.name, pfx_file, 'application/octet-stream'))
#                 ]
#                 response = requests.post(url, headers=headers, data=payload, files=files, timeout=30)
#         finally:
#             if os.path.exists(pfx_path):
#                 os.remove(pfx_path)
#             os.rmdir(tmp_dir)
#         _logger.info("Solicitar Folios SII - Status: %s, Response: %s", response.status_code, response.text)
#         return response.text

    def _get_number_next_actual(self):
        '''Return number from ir_sequence row when no_gap implementation,
        and number from postgres sequence when standard implementation.'''
        seq_dtes = self.filtered('is_dte')
        for seq in seq_dtes:
            folio = seq.get_folio()
            if folio == 0:
                folio = seq.number_next
            seq.number_next_actual = folio
        super(IRSequence, (self-seq_dtes))._get_number_next_actual()
