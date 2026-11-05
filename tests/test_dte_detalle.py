from odoo.addons.account.tests.common import AccountTestInvoicingCommon
from odoo.exceptions import UserError
from odoo.tests import tagged


@tagged('-at_install', 'post_install')
class TestDteDetalle(AccountTestInvoicingCommon):
    """Regresiones del detalle del DTE (NroLinDet y notas "Corrige texto")."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sale_journal = cls.company_data['default_journal_sale'].copy({
            'name': 'Detalle DTE',
            'code': 'DDT',
            'use_documents': False,
        })
        cls.product = cls.env['product.product'].create({
            'name': 'Producto de prueba',
            'list_price': 100,
        })
        cls.tipo_factura = cls.env['sii.document_class'].search(
            [('sii_code', '=', 33), ('dte', '=', True)], limit=1)

    def _create_invoice(self, **line_vals):
        values = {
            'name': 'Línea de prueba',
            'product_id': self.product.id,
            'quantity': 1,
            'price_unit': 100,
        }
        values.update(line_vals)
        return self.env['account.move'].create({
            'move_type': 'out_invoice',
            'journal_id': self.sale_journal.id,
            'partner_id': self.partner_a.id,
            'invoice_line_ids': [(0, 0, values)],
        })

    def _no_producto(self):
        return self.env['product.product'].sudo().with_context(active_test=False).search(
            [('default_code', '=', 'NO_PRODUCT')], limit=1)

    def test_nro_lin_det_respeta_secuencia_valida(self):
        invoice = self._create_invoice()
        invoice.invoice_line_ids.sequence = 3

        detalle = invoice._invoice_lines()['Detalle']

        self.assertEqual([line['NroLinDet'] for line in detalle], [3])

    def test_nro_lin_det_corrige_secuencia_invalida(self):
        """Las líneas creadas por código quedan con sequence -1 y rompen el XML."""
        invoice = self._create_invoice()
        invoice.invoice_line_ids.sequence = -1

        detalle = invoice._invoice_lines()['Detalle']

        self.assertEqual([line['NroLinDet'] for line in detalle], [1])

    def test_nro_lin_det_evita_duplicados(self):
        invoice = self._create_invoice()
        invoice.write({
            'invoice_line_ids': [(0, 0, {
                'name': 'Segunda línea',
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100,
            })],
        })
        invoice.invoice_line_ids.write({'sequence': 1})

        detalle = invoice._invoice_lines()['Detalle']

        self.assertEqual([line['NroLinDet'] for line in detalle], [1, 2])

    def test_nro_lin_det_evita_duplicados_con_secuencia_mixta(self):
        """Una secuencia válida ya usada no debe repetirse con el relleno posicional."""
        invoice = self._create_invoice()
        invoice.write({
            'invoice_line_ids': [(0, 0, {
                'name': 'Segunda línea',
                'product_id': self.product.id,
                'quantity': 1,
                'price_unit': 100,
            })],
        })
        lineas = invoice.invoice_line_ids
        lineas[0].sequence = 2
        lineas[1].sequence = -1

        detalle = invoice._invoice_lines()['Detalle']

        self.assertEqual([line['NroLinDet'] for line in detalle], [2, 3])

    def test_dte_sin_detalle_lanza_error_claro(self):
        """Sin líneas válidas el error debe nombrar el documento, no el XML del SII."""
        invoice = self._create_invoice(product_id=False, name=False)
        invoice.invoice_line_ids.write({'product_id': False, 'name': False})

        with self.assertRaises(UserError) as error:
            invoice._dte()

        self.assertIn('detalle', str(error.exception).lower())

    def test_producto_no_product_se_encuentra_en_otra_compania(self):
        """El marcador NO_PRODUCT puede quedar asignado a otra compañía o archivado."""
        plantilla = self.env.ref('l10n_cl_fe.no_product')
        otra_compania = self.env['res.company'].create({'name': 'Otra compañía'})
        plantilla.sudo().write({'company_id': otra_compania.id})

        self.assertFalse(
            self.env['product.product'].search([('product_tmpl_id', '=', plantilla.id)]),
            "La búsqueda normal debe quedar filtrada por la regla multi-compañía",
        )
        self.assertEqual(self.env['account.move']._get_producto_no_product(), self._no_producto())

    def test_producto_no_product_archivado_se_encuentra(self):
        self._no_producto().active = False

        self.assertTrue(self.env['account.move']._get_producto_no_product())

    def test_corrige_texto_crea_linea_valida(self):
        """copy() con referencia CodRef=2 debe dejar una línea timbrable."""
        invoice = self._create_invoice()
        plantilla = self.env.ref('l10n_cl_fe.no_product')
        otra_compania = self.env['res.company'].create({'name': 'Compañía del marcador'})
        plantilla.sudo().write({'company_id': otra_compania.id})

        nota = invoice.copy({
            'referencias': [(0, 0, {
                'sii_referencia_TpoDocRef': self.tipo_factura.id,
                'origen': '3105',
                'sii_referencia_CodRef': '2',
                'motivo': 'Dice: a Debe Decir: b',
            })],
        })

        linea = nota.invoice_line_ids
        self.assertEqual(len(linea), 1)
        self.assertEqual(linea.product_id, self._no_producto())
        self.assertEqual(linea.sequence, 1)
        self.assertEqual([line['NroLinDet'] for line in nota._invoice_lines()['Detalle']], [1])

    def test_producto_no_product_inexistente_lanza_error_claro(self):
        # Al borrar su única variante, Odoo borra también la plantilla y su xmlid.
        self._no_producto().sudo().unlink()

        with self.assertRaises(UserError) as error:
            self.env['account.move']._get_producto_no_product()

        self.assertIn('NO_PRODUCT', str(error.exception))
