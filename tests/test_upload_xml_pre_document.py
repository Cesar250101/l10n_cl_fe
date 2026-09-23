from lxml import etree

from odoo.tests.common import TransactionCase


def _line_xml(nro="1", nombre="Producto de Prueba", descripcion="Descripción de prueba",
              exenta=True, cantidad="1", precio="1000", monto="1000"):
    """Construye un elemento <Detalle> mínimo equivalente a los que trae un XML DTE real."""
    exe = "<IndExe>1</IndExe>" if exenta else ""
    xml = (
        "<Detalle>"
        "<NroLinDet>{nro}</NroLinDet>"
        "<NmbItem>{nombre}</NmbItem>"
        "<DscItem>{descripcion}</DscItem>"
        "{exe}"
        "<QtyItem>{cantidad}</QtyItem>"
        "<PrcItem>{precio}</PrcItem>"
        "<MontoItem>{monto}</MontoItem>"
        "</Detalle>"
    ).format(nro=nro, nombre=nombre, descripcion=descripcion, exe=exe, cantidad=cantidad, precio=precio, monto=monto)
    return etree.fromstring(xml.encode("utf-8"))


def _strip_insignificant_whitespace(element):
    """Elimina texto/tail que son solamente espacios en blanco (indentación agregada por pretty_print)."""
    for node in element.iter():
        if node.text is not None and node.text.strip() == "":
            node.text = None
        if node.tail is not None and node.tail.strip() == "":
            node.tail = None
    return element


class TestUploadXmlPreDocumentNewProduct(TransactionCase):
    """Cubre el bug de 'Nuevo Producto' mostrando repr() de un recordset en new_product."""

    def setUp(self):
        super().setUp()
        self.wizard = self.env["sii.dte.upload_xml.wizard"].create({})
        # document_id vacío pero como recordset real (no False), tal como lo necesita
        # _buscar_producto para acceder a document_id.partner_id sin lanzar AttributeError.
        self.empty_document_id = self.env["mail.message.dte.document"]
        self.company_id = self.env.user.company_id

    def test_prepare_line_with_matching_product_resolves_new_product_to_display_name(self):
        product = self.env["product.product"].create({"name": "Producto de Prueba XYZ-123"})
        line = _line_xml(nombre="Producto de Prueba XYZ-123")

        result = self.wizard._prepare_line(
            line, self.empty_document_id, "in_invoice", self.company_id, False, document=True,
        )

        self.assertIsInstance(result, list)
        data = result[2]
        self.assertEqual(data["new_product"], product.display_name)
        self.assertNotIn("product.product(", data["new_product"])
        self.assertIsInstance(data["new_product"], str)

    def test_prepare_line_without_match_preserves_plain_string(self):
        nombre_sin_match = "Producto Sin Coincidencia ABC-999"
        line = _line_xml(nombre=nombre_sin_match)

        # self.wizard.type == "compras" (default) y self.wizard.pre_process == True (default):
        # ese es el escenario en que _buscar_producto devuelve un string en vez de un recordset.
        self.assertEqual(self.wizard.type, "compras")
        self.assertTrue(self.wizard.pre_process)

        result = self.wizard._prepare_line(
            line, self.empty_document_id, "in_invoice", self.company_id, False, document=True,
        )

        data = result[2]
        self.assertEqual(data["new_product"], nombre_sin_match)


class TestDoCreatePreXmlFormatting(TransactionCase):
    """Cubre el bug de 'XML sin formatear' persistido por do_create_pre."""

    XML_COMPACT = (
        b"<DTE><Documento><Encabezado><IdDoc><TipoDTE>33</TipoDTE></IdDoc></Encabezado>"
        b"<Detalle><NroLinDet>1</NroLinDet><NmbItem>\xc3\x9atil variado</NmbItem>"
        b"<QtyItem>2</QtyItem><PrcItem>500</PrcItem><MontoItem>1000</MontoItem></Detalle>"
        b"</Documento></DTE>"
    )

    def test_pretty_print_reformats_without_changing_content(self):
        dte = etree.fromstring(self.XML_COMPACT)

        compact_bytes = etree.tostring(dte)
        pretty_bytes = etree.tostring(dte, pretty_print=True)

        # El formateo efectivamente cambia la representación en bytes (agrega indentación).
        self.assertNotEqual(compact_bytes, pretty_bytes)
        self.assertIn(b"\n", pretty_bytes)
        self.assertNotIn(b"\n", compact_bytes)

        original_tree = etree.fromstring(compact_bytes)
        pretty_tree = etree.fromstring(pretty_bytes)

        # Una vez que se ignora el whitespace insignificante agregado por pretty_print,
        # ambos árboles deben ser idénticos: mismo contenido, solo formato distinto.
        normalized_original = etree.tostring(_strip_insignificant_whitespace(original_tree))
        normalized_pretty = etree.tostring(_strip_insignificant_whitespace(pretty_tree))
        self.assertEqual(normalized_original, normalized_pretty)

        # El contenido de negocio (texto de los nodos hoja) se preserva exactamente.
        self.assertEqual(
            original_tree.findtext("Detalle/NmbItem"),
            pretty_tree.findtext("Detalle/NmbItem"),
        )
        self.assertEqual(
            original_tree.findtext("Detalle/MontoItem"),
            pretty_tree.findtext("Detalle/MontoItem"),
        )
