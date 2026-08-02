from odoo import api, fields, models


class FetchmailServer(models.Model):
    _inherit = "fetchmail.server"

    use_supabase_dte_source = fields.Boolean(
        string="Obtener DTE desde Supabase",
        help="El bot\\u00f3n Buscar Ahora importar\\u00e1 DTE desde Supabase y no abrir\\u00e1 IMAP.",
    )

    def fetch_mail(self):
        supabase_servers = self.filtered("use_supabase_dte_source")
        standard_servers = self - supabase_servers
        result = True
        if standard_servers:
            result = super(FetchmailServer, standard_servers).fetch_mail()
        if supabase_servers:
            self.env["mail.message.dte.document"].fetch_dte_supabase()
        return result

    @api.model
    def _fetch_mails(self):
        """Preserva el cron generico, excluyendo los servidores DTE Supabase."""
        servers = self.search(
            [
                ("state", "=", "done"),
                ("server_type", "!=", "local"),
                ("use_supabase_dte_source", "=", False),
            ]
        )
        return servers.fetch_mail()

    @api.model
    def _configure_supabase_dte_source(self):
        """Activa la fuente Supabase para los servidores DTE ya existentes."""
        servers = self.search(
            [
                (
                    "object_id.model",
                    "in",
                    ["mail.message.dte", "mail.message.dte.document"],
                )
            ]
        )
        if servers:
            servers.write({"use_supabase_dte_source": True, "active": False})
        cron = self.env.ref("l10n_cl_fe.ir_cron_fetch_dte_mail", raise_if_not_found=False)
        if cron:
            cron.write(
                {
                    "model_id": self.env.ref("l10n_cl_fe.model_mail_message_dte_document").id,
                    "code": "model._cron_fetch_dte_supabase()",
                    "active": True,
                }
            )
        return True
