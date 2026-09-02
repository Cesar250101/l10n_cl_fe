from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestPartnerDteAutocomplete(TransactionCase):

    def setUp(self):
        super().setUp()
        self.partner = self.env["res.partner"].create({
            "name": "Cliente DTE",
            "document_number": "76086428-5",
        })
        self.activity = self.env["partner.activities"].search([], limit=1)

    def test_completes_only_missing_receiver_data(self):
        data = {
            "glosa_giro": "Servicios de prueba",
            "actecos": [self.activity.code],
            "dte_email": "dte@example.cl",
        }
        with patch.object(
            type(self.partner), "get_remote_user_data", return_value=data,
        ) as remote_lookup:
            self.partner.complete_missing_dte_data_from_remote()

        remote_lookup.assert_called_once_with(
            self.partner.document_number, process_data=False,
        )
        self.assertEqual(self.partner.dte_email, "dte@example.cl")
        self.assertEqual(self.partner.activity_description.name, "Servicios de prueba")
        self.assertEqual(self.partner.acteco_ids, self.activity)

    def test_keeps_existing_receiver_data_and_skips_lookup(self):
        giro = self.env["sii.activity.description"].create({"name": "Giro existente"})
        self.partner.write({
            "activity_description": giro.id,
            "acteco_ids": [(6, 0, self.activity.ids)],
            "dte_email": "existente@example.cl",
        })

        with patch.object(type(self.partner), "get_remote_user_data") as remote_lookup:
            self.partner.complete_missing_dte_data_from_remote()

        remote_lookup.assert_not_called()
        self.assertEqual(self.partner.dte_email, "existente@example.cl")

    def test_preserves_each_existing_receiver_value(self):
        giro = self.env["sii.activity.description"].create({"name": "Giro existente"})
        replacement = self.env["partner.activities"].search(
            [("id", "!=", self.activity.id)], limit=1,
        ) or self.activity
        data = {
            "glosa_giro": "Giro remoto",
            "actecos": [replacement.code],
            "dte_email": "remoto@example.cl",
        }
        for field, value in (
            ("activity_description", giro.id),
            ("acteco_ids", [(6, 0, self.activity.ids)]),
            ("dte_email", "existente@example.cl"),
        ):
            self.partner.write({
                "activity_description": False,
                "acteco_ids": [(5, 0, 0)],
                "dte_email": False,
                field: value,
            })
            with patch.object(type(self.partner), "get_remote_user_data", return_value=data):
                self.partner.complete_missing_dte_data_from_remote()

            if field == "activity_description":
                self.assertEqual(self.partner.activity_description, giro)
            elif field == "acteco_ids":
                self.assertEqual(self.partner.acteco_ids, self.activity)
            else:
                self.assertEqual(self.partner.dte_email, "existente@example.cl")

    def test_remote_failure_does_not_block_completion(self):
        with patch.object(
            type(self.partner), "get_remote_user_data", side_effect=ConnectionError,
        ):
            self.partner.complete_missing_dte_data_from_remote()

        self.assertFalse(self.partner.dte_email)

    def test_invalid_rut_skips_remote_lookup(self):
        self.partner.document_number = "11111111-1"

        with patch.object(type(self.partner), "get_remote_user_data") as remote_lookup:
            self.partner.complete_missing_dte_data_from_remote()

        remote_lookup.assert_not_called()

    def test_remote_data_is_not_published_again(self):
        company = self.partner.company_id
        company.write({
            "url_remote_partners": "https://remote.example.cl",
            "token_remote_partners": "test-token",
            "sync_remote_partners": True,
        })
        self.partner.write({"sync": True})

        with patch.object(
            type(self.partner),
            "get_remote_user_data",
            return_value={"dte_email": "dte@example.cl"},
        ), patch.object(type(self.partner), "put_remote_user_data") as remote_publish:
            self.partner.complete_missing_dte_data_from_remote()

        remote_publish.assert_not_called()
        self.assertTrue(self.partner.sync)
        self.assertEqual(self.partner.dte_email, "dte@example.cl")

    def test_only_customer_invoices_request_receiver_data(self):
        customer_invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "use_documents": True,
        })
        vendor_bill = self.env["account.move"].create({
            "move_type": "in_invoice",
            "partner_id": self.partner.id,
            "use_documents": True,
        })
        customer_without_documents = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "use_documents": False,
        })
        posted_customer_invoice = self.env["account.move"].create({
            "move_type": "out_invoice",
            "partner_id": self.partner.id,
            "use_documents": True,
        })
        posted_customer_invoice.with_context(check_move_validity=False).write({"state": "posted"})

        with patch.object(
            type(self.partner), "complete_missing_dte_data_from_remote",
        ) as autocomplete:
            (
                customer_invoice
                | vendor_bill
                | customer_without_documents
                | posted_customer_invoice
            )._complete_dte_receiver_data_before_post()

        autocomplete.assert_called_once()
