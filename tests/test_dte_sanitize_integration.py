from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('-at_install', 'post_install')
class TestDteSanitizeIntegration(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sale_journal = cls.company_data['default_journal_sale'].copy({
            'name': 'Sanitize SII',
            'code': 'SII',
            'use_documents': False,
        })
        cls.invoice = cls.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': cls.sale_journal.id,
            'partner_id': cls.partner_a.id,
            'invoice_line_ids': [(0, 0, {
                'name': 'Servicio\tespecial “premium”',
                'quantity': 1,
                'price_unit': 100,
            })],
        })

    def _payload(self):
        return {
            'Emisor': {'RznSoc': 'Emisor “Uno” & Cía', 'GiroEmis': 'Comercio', 'RUTEmisor': '76.000.000-0'},
            'Documento': [{
                'TipoDTE': 33,
                'documentos': [{
                    'Encabezado': {'Receptor': {'RznSocRecep': 'Cliente – Sur 😀', 'RUTRecep': '11.111.111-1'}},
                    'Detalle': [{'NmbItem': self.invoice.invoice_line_ids.name, 'MontoItem': 100}],
                }],
            }],
        }

    def test_option_enabled_by_default(self):
        self.assertTrue(self.env['res.company'].new({}).dte_sanitize_text)

    def test_disabled_returns_same_payload(self):
        self.invoice.company_id.dte_sanitize_text = False
        payload = self._payload()
        self.assertIs(self.invoice._sii_sanitize_payload(payload), payload)

    def test_enabled_sanitizes_header_and_detail_and_logs(self):
        self.invoice.company_id.dte_sanitize_text = True
        messages_before = len(self.invoice.message_ids)

        clean = self.invoice._sii_sanitize_payload(self._payload())

        self.assertEqual(clean['Emisor']['RznSoc'], 'Emisor Uno Y Cía')
        self.assertEqual(clean['Emisor']['RUTEmisor'], '76.000.000-0')
        doc = clean['Documento'][0]['documentos'][0]
        self.assertEqual(doc['Encabezado']['Receptor']['RznSocRecep'], 'Cliente - Sur')
        self.assertEqual(doc['Detalle'][0]['NmbItem'], 'Servicio especial premium')
        self.assertEqual(doc['Detalle'][0]['MontoItem'], 100)
        self.assertEqual(len(self.invoice.message_ids), messages_before + 1)
        self.assertIn('RznSocRecep', self.invoice.message_ids[0].body)

    def test_required_field_emptied_raises_user_error(self):
        self.invoice.company_id.dte_sanitize_text = True
        payload = self._payload()
        payload['Documento'][0]['documentos'][0]['Detalle'][0]['NmbItem'] = '😀'
        with self.assertRaises(UserError):
            self.invoice._sii_sanitize_payload(payload)
