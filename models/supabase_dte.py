import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from odoo.exceptions import UserError
from odoo.tools.translate import _


class SupabaseDteError(Exception):
    """Error controlado al consumir las RPC privadas de Supabase."""


class SupabaseDteClient:
    PARAM_URL = "l10n_cl_fe.supabase_dte_url"
    PARAM_API_KEY = "l10n_cl_fe.supabase_dte_api_key"
    PARAM_KEY = "l10n_cl_fe.supabase_dte_key"
    PARAM_CONSUMER = "l10n_cl_fe.supabase_dte_consumer"
    PARAM_BATCH_SIZE = "l10n_cl_fe.supabase_dte_batch_size"

    def __init__(self, base_url, api_key, access_token, consumer_id, batch_size=50):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.access_token = access_token or ""
        self.consumer_id = consumer_id or ""
        try:
            batch_size = int(batch_size or 50)
        except (TypeError, ValueError) as error:
            raise UserError(_("El tama\\u00f1o de lote de Supabase debe ser un n\\u00famero.")) from error
        self.batch_size = max(1, min(batch_size, 200))

    @classmethod
    def from_env(cls, env):
        params = env["ir.config_parameter"].sudo()
        consumer_id = params.get_param(cls.PARAM_CONSUMER) or "odoo:%s" % env.cr.dbname
        return cls(
            params.get_param(cls.PARAM_URL),
            params.get_param(cls.PARAM_API_KEY),
            params.get_param(cls.PARAM_KEY),
            consumer_id,
            params.get_param(cls.PARAM_BATCH_SIZE, default=50),
        )

    def validate(self):
        missing = []
        if not self.base_url:
            missing.append("URL de Supabase")
        if not self.api_key:
            missing.append("clave API publica de Supabase")
        if not self.access_token:
            missing.append("clave de sincronizaci\\u00f3n")
        if not self.consumer_id:
            missing.append("identificador de consumidor")
        if missing:
            raise UserError(_("Falta configurar %s para DTE desde Supabase.") % ", ".join(missing))

    def _rpc(self, name, payload):
        self.validate()
        request = Request(
            "%s/rest/v1/rpc/%s" % (self.base_url, name),
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "apikey": self.api_key,
                "Authorization": "Bearer %s" % self.access_token,
                "Content-Type": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                body = response.read().decode("utf-8")
        except HTTPError as error:
            raise SupabaseDteError("Supabase respondi\\u00f3 HTTP %s" % error.code) from error
        except URLError as error:
            raise SupabaseDteError("No fue posible conectar con Supabase: %s" % error.reason) from error
        except OSError as error:
            raise SupabaseDteError("Error de red hacia Supabase: %s" % error) from error

        try:
            result = json.loads(body)
        except ValueError as error:
            raise SupabaseDteError("Supabase devolvi\\u00f3 una respuesta inv\\u00e1lida") from error
        if not isinstance(result, list):
            raise SupabaseDteError("Supabase devolvi\\u00f3 una respuesta inesperada")
        return result

    def claim(self, receiver_ruts):
        return self._rpc(
            "claim_dte_inbox_documents",
            {
                "p_consumer_id": self.consumer_id,
                "p_rut_receptores": receiver_ruts,
                "p_limit": self.batch_size,
            },
        )

    def complete(self, document_id, claim_token, odoo_document_id):
        result = self._rpc(
            "complete_dte_inbox_document_sync",
            {
                "p_document_id": document_id,
                "p_consumer_id": self.consumer_id,
                "p_claim_token": claim_token,
                "p_odoo_document_id": odoo_document_id,
            },
        )
        if not result or not result[0].get("completed"):
            raise SupabaseDteError("No fue posible confirmar el DTE reclamado en Supabase")

    def fail(self, document_id, claim_token, error_message):
        result = self._rpc(
            "fail_dte_inbox_document_sync",
            {
                "p_document_id": document_id,
                "p_consumer_id": self.consumer_id,
                "p_claim_token": claim_token,
                "p_error_message": error_message,
            },
        )
        if not result or not result[0].get("failed"):
            raise SupabaseDteError("No fue posible registrar el error del DTE en Supabase")

    def retry_errors(self):
        result = self._rpc(
            "retry_dte_inbox_document_sync_errors",
            {"p_consumer_id": self.consumer_id},
        )
        return result[0].get("reset_count", 0) if result else 0
