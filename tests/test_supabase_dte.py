import json
from unittest.mock import patch

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError

from odoo.addons.l10n_cl_fe.models.supabase_dte import SupabaseDteClient


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class TestSupabaseDteClient(TransactionCase):
    def setUp(self):
        super().setUp()
        self.client = SupabaseDteClient(
            "https://supabase.example.cl",
            "anon-key",
            "test-key",
            "odoo:test",
            500,
        )

    def test_claim_normalizes_batch_size_and_payload(self):
        with patch(
            "odoo.addons.l10n_cl_fe.models.supabase_dte.urlopen",
            return_value=FakeResponse([]),
        ) as urlopen_mock:
            self.assertEqual(self.client.claim(["779866483"]), [])

        request = urlopen_mock.call_args.args[0]
        self.assertEqual(request.full_url, "https://supabase.example.cl/rest/v1/rpc/claim_dte_inbox_documents")
        self.assertEqual(json.loads(request.data.decode("utf-8"))["p_limit"], 200)

    def test_complete_requires_positive_rpc_result(self):
        with patch(
            "odoo.addons.l10n_cl_fe.models.supabase_dte.urlopen",
            return_value=FakeResponse([{ "completed": True }]),
        ):
            self.client.complete("dte-id", "claim-id", 42)

    def test_invalid_batch_size_does_not_build_a_client(self):
        with self.assertRaises(UserError):
            SupabaseDteClient(
                "https://supabase.example.cl",
                "anon-key",
                "test-key",
                "odoo:test",
                "invalid",
            )

    def test_normalizes_company_rut(self):
        document_model = self.env["mail.message.dte.document"]
        self.assertEqual(document_model._supabase_normalize_rut("CL77.986.648-3"), "779866483")
