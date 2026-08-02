from odoo import api, fields, models
from odoo.exceptions import UserError

try:
    from facturacion_electronica import __version__
except ImportError:
    __version__ = "0.0.0"


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    send_dte_method = fields.Selection([('manual', 'Manual'), ('imediato', 'Inmediato'), ('diferido', 'Diferido')], string="Tiempo de Espera para Enviar DTE automático al SII (en horas)", default='diferido',)
    auto_send_dte = fields.Integer(string="Tiempo de Espera para Enviar DTE automático al SII (en horas)", default=1,)
    auto_send_email = fields.Boolean(string="Enviar Email automático al Auto Enviar DTE al SII", default=True,)
    auto_send_persistencia = fields.Integer(string="Enviar Email automático al Cliente cada  n horas", default=24,)
    dte_email_id = fields.Many2one("mail.alias", related="company_id.dte_email_id", readonly=False)
    limit_dte_lines = fields.Boolean(related="company_id.limit_dte_lines", string="Limitar Cantidad de líneas por documento", readonly=False)
    url_remote_partners = fields.Char(related="company_id.url_remote_partners", string="Url Remote Partners", readonly=False)
    token_remote_partners = fields.Char(related="company_id.token_remote_partners", string="Token Remote Partners", readonly=False)
    sync_remote_partners = fields.Boolean(related="company_id.sync_remote_partners", string="Sync Remote Partners", readonly=False)
    url_apicaf = fields.Char(related="company_id.url_apicaf", string="URL APICAF", readonly=False)
    token_apicaf = fields.Char(related="company_id.token_apicaf", string="Token APICAF", readonly=False)
    supabase_dte_url = fields.Char(
        string="URL Supabase DTE",
        config_parameter="l10n_cl_fe.supabase_dte_url",
    )
    supabase_dte_api_key = fields.Char(
        string="Clave API publica Supabase DTE",
        config_parameter="l10n_cl_fe.supabase_dte_api_key",
    )
    supabase_dte_key = fields.Char(
        string="Clave Supabase DTE",
        config_parameter="l10n_cl_fe.supabase_dte_key",
    )
    supabase_dte_consumer = fields.Char(
        string="Consumidor Supabase DTE",
        config_parameter="l10n_cl_fe.supabase_dte_consumer",
        default=lambda self: "odoo:%s" % self.env.cr.dbname,
    )
    supabase_dte_batch_size = fields.Integer(
        string="DTE por lote Supabase",
        config_parameter="l10n_cl_fe.supabase_dte_batch_size",
        default=50,
    )
    # nro_rec_envio = fields.Integer(related="company_id.nro_rec_envio",string='Nro. Registros Envio', readonly=False)
    # nro_rec_consulta = fields.Integer(related="company_id.nro_rec_consulta",string='Nro. Registros Consulta', readonly=False)
    # nro_rec_pasivo = fields.Integer(related="company_id.nro_rec_pasivo",string='Nro. Registros Pasivo', readonly=False)

    cf_autosend = fields.Boolean(related="company_id.cf_autosend", string="AutoEnviar Consumo de Folios", readonly=False)
    fe_version = fields.Char(string="Versión FE instalado", readonly=True,)
    medios_de_pago_electronico = fields.Many2many(
        'account.journal',
        related="company_id.medios_de_pago_electronico",
        string="Medios de pago Electrónico",
    )

    @api.model
    def get_values(self):
        res = super(ResConfigSettings, self).get_values()
        ICPSudo = self.env["ir.config_parameter"].sudo()
        account_send_dte_method = ICPSudo.get_param("account.send_dte_method", default='diferido')
        account_auto_send_dte = int(ICPSudo.get_param("account.auto_send_dte", default=1))
        account_auto_send_email = ICPSudo.get_param("account.auto_send_email", default=True)
        account_auto_send_persistencia = int(ICPSudo.get_param("account.auto_send_persistencia", default=24))
        res.update(
            send_dte_method=account_send_dte_method,
            auto_send_email=account_auto_send_email,
            auto_send_dte=account_auto_send_dte,
            auto_send_persistencia=account_auto_send_persistencia,
            fe_version=__version__,
        )
        return res

    def set_values(self):
        super(ResConfigSettings, self).set_values()
        ICPSudo = self.env["ir.config_parameter"].sudo()
        if self.dte_email_id and not self.external_email_server_default:
            raise UserError("Debe Cofigurar Servidor de Correo Externo en la pestaña Opciones Generales")
        ICPSudo.set_param("account.send_dte_method", self.send_dte_method)
        ICPSudo.set_param("account.auto_send_dte", self.auto_send_dte)
        ICPSudo.set_param("account.auto_send_email", self.auto_send_email)
        ICPSudo.set_param("account.auto_send_peresistencia", self.auto_send_persistencia)

    def action_retry_supabase_dte_errors(self):
        return self.env["mail.message.dte.document"].retry_supabase_dte_errors()
