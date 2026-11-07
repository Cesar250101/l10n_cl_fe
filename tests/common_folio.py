from unittest import mock

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


class FolioCommon(AccountTestInvoicingCommon):
    """Fixtures de folios: diario con documentos DTE, secuencia, CAF y documentos ya publicados.

    Las subclases llaman a `_setup_folio(sii_code, move_type)`. Solo se crean datos de prueba; ninguna
    prueba llama al SII (el timbrado, la cola y la consulta del receptor se neutralizan en `_publicar`).
    """

    NOMBRE_SECUENCIA = "FOLTEST"
    CAF_INICIO = 1
    CAF_FIN = 100
    # l10n_cl_fe depende del plan chileno; l10n_generic_coa (el de AccountTestInvoicingCommon) puede no estar.
    CHART_TEMPLATE = "l10n_cl_chart_of_account.cl_chart_template_sii"

    @classmethod
    def setUpClass(cls, chart_template_ref=None):
        super().setUpClass(chart_template_ref=chart_template_ref or cls.CHART_TEMPLATE)

    @classmethod
    def _crear_secuencia(cls, tipo, journal, nombre, inicio=None, fin=None, siguiente=1):
        secuencia = cls.env["ir.sequence"].create({
            "name": nombre,
            "implementation": "no_gap",
            "is_dte": True,
            "sii_document_class_id": tipo.id,
            "company_id": cls.env.company.id,
            "number_next": siguiente,
            "padding": 0,
        })
        caf = cls.env["dte.caf"].create({
            "filename": "%s.xml" % nombre,
            "sequence_id": secuencia.id,
            "folio_actual": inicio or cls.CAF_INICIO,
        })
        # start_nm/final_nm son calculados a partir del XML del CAF; se fijan directo para la prueba.
        cls.env.flush_all()
        cls.env.cr.execute(
            "UPDATE dte_caf SET start_nm = %s, final_nm = %s, state = 'in_use' WHERE id = %s",
            (inicio or cls.CAF_INICIO, fin or cls.CAF_FIN, caf.id),
        )
        cls.env.invalidate_all()
        cls.env["account.journal.sii_document_class"].create({
            "journal_id": journal.id,
            "sii_document_class_id": tipo.id,
            "sequence_id": secuencia.id,
        })
        return secuencia

    @classmethod
    def _setup_folio(cls, sii_code, move_type="out_invoice"):
        cls.move_type_folio = move_type
        cls.tipo = cls.env["sii.document_class"].search([("sii_code", "=", sii_code)], limit=1)
        cls.otro_tipo = cls.env["sii.document_class"].search(
            [("sii_code", "!=", sii_code), ("sii_code", "in", (33, 34, 61))], limit=1)
        base = cls.company_data["default_journal_sale"]
        cls.journal = base.copy({"name": "Folios DTE", "code": "FDT", "use_documents": True, "alias_name": "foltest1"})
        cls.otro_journal = base.copy({"name": "Folios DTE 2", "code": "FD2", "use_documents": True, "alias_name": "foltest2"})
        cls.secuencia = cls._crear_secuencia(cls.tipo, cls.journal, cls.NOMBRE_SECUENCIA)
        cls.otra_secuencia = cls._crear_secuencia(cls.tipo, cls.otro_journal, "FOLTEST2")
        cls.producto = cls.env["product.product"].create({"name": "Producto folio", "list_price": 100})

    def _crear_borrador(self, journal=None, move_type=None):
        journal = journal or self.journal
        move = self.env["account.move"].create({
            "move_type": move_type or self.move_type_folio,
            "journal_id": journal.id,
            "partner_id": self.partner_a.id,
            "invoice_line_ids": [(0, 0, {
                "name": "Línea de prueba",
                "product_id": self.producto.id,
                "quantity": 1,
                "price_unit": 100,
            })],
        })
        if move.move_type in ("out_invoice", "out_refund"):
            # En la interfaz los pone el onchange del diario; creado por código hay que fijarlos.
            move.write({
                "use_documents": True,
                "journal_document_class_id": self.env["account.journal.sii_document_class"].search(
                    [("journal_id", "=", journal.id), ("sii_document_class_id", "=", self.tipo.id)], limit=1).id,
                "document_class_id": self.tipo.id,
            })
        return move

    def _crear_publicado(self, folio, nombre=None, estado="posted", journal=None, tipo=None):
        """Crea un documento ya publicado/anulado con el folio dado, sin pasar por _post."""
        move = self._crear_borrador(journal=journal)
        tipo = tipo or self.tipo
        self.env.flush_all()
        self.env.cr.execute(
            """UPDATE account_move
                  SET state = %s, name = %s, sii_document_number = %s, document_class_id = %s,
                      use_documents = TRUE
                WHERE id = %s""",
            (estado, nombre or "%s%s" % (self.NOMBRE_SECUENCIA, folio), folio, tipo.id, move.id),
        )
        self.env.invalidate_all()
        return self.env["account.move"].browse(move.id)

    def _fijar_siguiente(self, numero, secuencia=None):
        secuencia = secuencia or self.secuencia
        self.env.flush_all()
        self.env.cr.execute("UPDATE ir_sequence SET number_next = %s WHERE id = %s", (numero, secuencia.id))
        self.env.invalidate_all()

    def _siguiente_en_bd(self, secuencia=None):
        secuencia = secuencia or self.secuencia
        self.env.flush_all()
        self.env.cr.execute("SELECT number_next FROM ir_sequence WHERE id = %s", [secuencia.id])
        return self.env.cr.fetchone()[0]

    def _publicar(self, move):
        """Publica `move` con el código real de _post, sin efectos externos (SII, cola, red)."""
        move_model = type(self.env["account.move"])
        cola_model = type(self.env["sii.cola_envio"])
        self.env["ir.config_parameter"].sudo().set_param("account.send_dte_method", "manual")
        with mock.patch.object(move_model, "_timbrar", lambda self_, n_atencion=None: True), \
                mock.patch.object(move_model, "_validaciones_uso_dte", lambda self_: True), \
                mock.patch.object(move_model, "_complete_dte_receiver_data_before_post", lambda self_: None), \
                mock.patch.object(cola_model, "lanzar_trabajo", lambda self_: True):
            move.action_post()
        return move
