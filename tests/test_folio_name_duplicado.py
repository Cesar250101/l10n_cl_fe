from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common_folio import FolioCommon


@tagged('-at_install', 'post_install')
class TestFolioNameDuplicado(FolioCommon):
    """Regresión L10NCLFE-005: «Ya existe otro asiento con el mismo nombre» al confirmar facturas DTE."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._setup_folio(33)

    def test_secuencia_atrasada_avanza_al_siguiente_libre(self):
        self._crear_publicado(5)
        self._crear_publicado(6)
        self._fijar_siguiente(5)
        borrador = self._crear_borrador()

        numero = self.secuencia._sincronizar_numero_siguiente(borrador)

        self.assertEqual(numero, 7)
        self.assertEqual(self._siguiente_en_bd(), 7)

    def test_no_retrocede_la_secuencia(self):
        self._crear_publicado(5)
        self._fijar_siguiente(20)
        borrador = self._crear_borrador()

        numero = self.secuencia._sincronizar_numero_siguiente(borrador)

        self.assertEqual(numero, 20)
        self.assertEqual(self._siguiente_en_bd(), 20)

    def test_secuencia_correcta_no_se_escribe(self):
        self._crear_publicado(5)
        self._fijar_siguiente(6)
        borrador = self._crear_borrador()

        with mock.patch.object(type(self.secuencia), 'write', side_effect=AssertionError('no debe escribir')):
            numero = self.secuencia._sincronizar_numero_siguiente(borrador)

        self.assertEqual(numero, 6)

    def test_sin_documentos_previos_respeta_la_secuencia(self):
        self._fijar_siguiente(1)
        borrador = self._crear_borrador()

        self.assertEqual(self.secuencia._sincronizar_numero_siguiente(borrador), 1)

    def test_folio_anulado_cuenta_como_usado(self):
        self._crear_publicado(9, estado='cancel')
        self._fijar_siguiente(3)
        borrador = self._crear_borrador()

        self.assertEqual(self.secuencia._sincronizar_numero_siguiente(borrador), 10)

    def test_ignora_otra_clase_otro_diario_y_fuera_de_rango(self):
        self._crear_publicado(5)
        self._crear_publicado(50, nombre='OTRACLASE50', tipo=self.otro_tipo)
        self._crear_publicado(60, nombre='OTRODIARIO60', journal=self.otro_journal)
        self._crear_publicado(500, nombre='FUERARANGO500')
        self._fijar_siguiente(1)
        borrador = self._crear_borrador()

        self.assertEqual(self.secuencia._sincronizar_numero_siguiente(borrador), 6)

    def test_nombre_existente_aunque_el_folio_no_lo_muestre_avanza(self):
        """Nombre heredado cuyo folio no coincide: el número candidato igual debe quedar libre."""
        self._crear_publicado(3, nombre='FOLTEST8')
        self._fijar_siguiente(8)
        borrador = self._crear_borrador()

        self.assertEqual(self.secuencia._sincronizar_numero_siguiente(borrador), 9)

    def test_nombre_de_otro_diario_no_cuenta_como_colision(self):
        """El índice único es por (name, journal_id): el mismo nombre en otro diario no bloquea el número."""
        self._crear_publicado(3, nombre='FOLTEST8', journal=self.otro_journal)
        self._fijar_siguiente(8)
        borrador = self._crear_borrador()

        self.assertEqual(self.secuencia._sincronizar_numero_siguiente(borrador), 8)

    def test_nombre_en_borrador_no_cuenta_como_colision(self):
        """El índice único solo aplica a asientos publicados."""
        self._crear_publicado(3, nombre='FOLTEST8', estado='draft')
        self._fijar_siguiente(8)
        borrador = self._crear_borrador()

        self.assertEqual(self.secuencia._sincronizar_numero_siguiente(borrador), 8)

    def test_tope_de_intentos_lanza_error_claro(self):
        for numero in (8, 9, 10, 11):
            self._crear_publicado(3, nombre='FOLTEST%s' % numero)
        self._fijar_siguiente(8)
        borrador = self._crear_borrador()

        with mock.patch.object(type(self.secuencia), '_MAX_INTENTOS_NOMBRE_FOLIO', 3):
            with self.assertRaises(UserError) as error:
                self.secuencia._sincronizar_numero_siguiente(borrador)

        self.assertIn('FOLTEST', str(error.exception))

    def test_publicar_asigna_nombre_y_folio_correctos(self):
        """Caso del reporte: la secuencia apunta a un nombre ya publicado."""
        self._crear_publicado(70)
        self._crear_publicado(71)
        self._fijar_siguiente(71)
        borrador = self._crear_borrador()

        self._publicar(borrador)

        self.assertEqual(borrador.state, 'posted')
        self.assertEqual(borrador.sii_document_number, 72)
        self.assertEqual(borrador.name, 'FOLTEST72')

    def test_publicar_sin_colision_conserva_el_numero(self):
        self._crear_publicado(4)
        self._fijar_siguiente(5)
        borrador = self._crear_borrador()

        self._publicar(borrador)

        self.assertEqual(borrador.sii_document_number, 5)
        self.assertEqual(borrador.name, 'FOLTEST5')

    def test_dos_publicaciones_seguidas_no_chocan(self):
        self._crear_publicado(70)
        self._fijar_siguiente(70)
        primero = self._publicar(self._crear_borrador())
        segundo = self._publicar(self._crear_borrador())

        self.assertEqual((primero.name, segundo.name), ('FOLTEST71', 'FOLTEST72'))

    def test_no_actua_sobre_compras(self):
        self._crear_publicado(5)
        self._fijar_siguiente(5)
        compra = self._crear_borrador(move_type='in_invoice')

        self.assertFalse(compra._sincronizar_folio_antes_de_publicar())
        self.assertEqual(self._siguiente_en_bd(), 5)

    def test_no_actua_con_folio_ya_asignado(self):
        self._crear_publicado(5)
        self._fijar_siguiente(5)
        borrador = self._crear_borrador()
        borrador.sii_document_number = 99

        self.assertFalse(borrador._sincronizar_folio_antes_de_publicar())
        self.assertEqual(self._siguiente_en_bd(), 5)

    def test_no_actua_en_restore_mode(self):
        self._crear_publicado(5)
        self._fijar_siguiente(5)
        self.journal.restore_mode = True
        borrador = self._crear_borrador()

        self.assertFalse(borrador._sincronizar_folio_antes_de_publicar())
        self.assertEqual(self._siguiente_en_bd(), 5)
