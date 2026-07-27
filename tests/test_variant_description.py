from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.tests import tagged


@tagged('-at_install', 'post_install')
class TestVariantDescription(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sale_journal = cls.company_data['default_journal_sale'].copy({
            'name': 'Variant descriptions',
            'code': 'VAR',
            'use_documents': False,
        })
        color = cls.env['product.attribute'].create({
            'name': 'Color',
            'create_variant': 'always',
        })
        size = cls.env['product.attribute'].create({
            'name': 'Tamaño',
            'create_variant': 'always',
        })
        gold = cls.env['product.attribute.value'].create({
            'name': 'Dorado',
            'attribute_id': color.id,
        })
        large = cls.env['product.attribute.value'].create({
            'name': 'Grande',
            'attribute_id': size.id,
        })
        template = cls.env['product.template'].create({
            'name': 'MG 008',
            'invoice_policy': 'order',
            'attribute_line_ids': [
                (0, 0, {
                    'attribute_id': color.id,
                    'value_ids': [(6, 0, gold.ids)],
                }),
                (0, 0, {
                    'attribute_id': size.id,
                    'value_ids': [(6, 0, large.ids)],
                }),
            ],
        })
        cls.product = template.product_variant_id
        cls.product_without_variants = cls.env['product.product'].create({
            'name': 'MG 009',
            'invoice_policy': 'order',
        })

    def _create_invoice(self, description='Descripción original', product=None):
        product = product or self.product
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': self.sale_journal.id,
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [(0, 0, {
                'name': description,
                'product_id': product.id,
                'quantity': 1,
                'price_unit': 100,
            })],
        })

    def test_variant_description_replaces_invoice_and_dte_description(self):
        self.sale_journal.use_variant_description = True

        invoice = self._create_invoice()
        line = invoice.invoice_line_ids
        expected = 'MG 008 Color: Dorado, Tamaño: Grande'

        self.assertEqual(line.name, expected)
        self.assertEqual(invoice._get_dte_line_description(line), expected)

    def test_product_without_variants_uses_its_template_name(self):
        self.sale_journal.use_variant_description = True

        invoice = self._create_invoice(product=self.product_without_variants)

        self.assertEqual(invoice.invoice_line_ids.name, 'MG 009')

    def test_disabled_journal_keeps_existing_description(self):
        self.sale_journal.use_variant_description = False

        invoice = self._create_invoice()

        self.assertEqual(invoice.invoice_line_ids.name, 'Descripción original')

    def test_enabling_journal_updates_drafts_but_not_posted_invoices(self):
        self.sale_journal.use_variant_description = False
        draft_invoice = self._create_invoice('Descripción borrador')
        posted_invoice = self._create_invoice('Descripción publicada')
        posted_invoice.with_context(check_move_validity=False).write({'state': 'posted'})

        self.sale_journal.use_variant_description = True

        expected = 'MG 008 Color: Dorado, Tamaño: Grande'
        self.assertEqual(draft_invoice.invoice_line_ids.name, expected)
        self.assertEqual(posted_invoice.invoice_line_ids.name, 'Descripción publicada')

    def test_sale_order_line_description_is_normalized_on_invoice_creation(self):
        self.sale_journal.use_variant_description = True
        order = self.env['sale.order'].create({
            'partner_id': self.partner_a.id,
            'order_line': [(0, 0, {
                'name': 'Descripción desde pedido de venta',
                'product_id': self.product.id,
                'product_uom_qty': 1,
                'price_unit': 100,
            })],
        })
        invoice_line_values = order.order_line._prepare_invoice_line()
        invoice = self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': self.sale_journal.id,
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [(0, 0, invoice_line_values)],
        })

        self.assertEqual(
            invoice.invoice_line_ids.name,
            'MG 008 Color: Dorado, Tamaño: Grande',
        )
