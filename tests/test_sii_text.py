import copy

from odoo.tests import TransactionCase, tagged

from odoo.addons.l10n_cl_fe.tools.sii_text import (
    SiiRequiredFieldError,
    sanitize_dte_payload,
    sanitize_sii_text,
)


@tagged('-at_install', 'post_install')
class TestSiiText(TransactionCase):

    CASES = [
        ('Comercial “Pérez” & Cía Ltda.', 'Comercial Pérez Y Cía Ltda.'),
        ('Ñandú – Ñuñoa…', 'Ñandú - Ñuñoa...'),
        ('A\tB\nC\r\nD', 'A B C D'),
        ('Café 😀', 'Café'),
        ('ﬁno™', 'finoTM'),
        ('Őrs', 'Ors'),
        ("O'Higgins", 'OHiggins'),
        ('<b>x</b>', 'bx/b'),
        ('25°C ºª ¿¡', '25°C ºª ¿¡'),
        ('é', 'é'),
        ('x\x00y\x7fz\x85w', 'xyzw'),
        ('ＡＢＣ＆', 'ABCY'),
        ('  doble   espacio  ', 'doble espacio'),
    ]

    def test_sanitize_cases(self):
        for value, expected in self.CASES:
            with self.subTest(value=value):
                self.assertEqual(sanitize_sii_text(value), expected)

    def test_idempotent_and_latin1(self):
        for value, _expected in self.CASES:
            result = sanitize_sii_text(value)
            self.assertEqual(sanitize_sii_text(result), result)
            result.encode('ISO-8859-1')

    def test_non_str_untouched(self):
        for value in (None, False, 0, 12.5):
            self.assertIs(sanitize_sii_text(value), value)

    def test_max_len_after_sanitize(self):
        self.assertEqual(sanitize_sii_text('abc…', 4), 'abc.')
        self.assertEqual(sanitize_sii_text('a' * 10 + ' b', 11), 'a' * 10)

    def _payload(self):
        return {
            'Emisor': {'RznSoc': 'Empresa “X”', 'RUTEmisor': '76.000.000-0',
                       'CorreoEmisor': "o'neil@x.cl", 'GiroEmis': 'Venta – menor'},
            'firma_electronica': {'subject_name': '“x” & <y>'},
            'Documento': [{
                'TipoDTE': 33,
                'caf_file': ['<AUTORIZACION>&</AUTORIZACION>'],
                'documentos': [{
                    'Encabezado': {
                        'IdDoc': {'Folio': 10, 'FchEmis': '2026-10-01'},
                        'Receptor': {'RUTRecep': '11.111.111-1', 'RznSocRecep': 'Pérez & Hijos',
                                     'CorreoRecep': 'a&b@x.cl', 'CiudadRecep': ''},
                    },
                    'Detalle': [{'NmbItem': 'Prod\t1', 'DscItem': 'Línea\nlarga',
                                 'CdgItem': [{'TpoCodigo': 'INT1', 'VlrCodigo': 'A&B'}],
                                 'MontoItem': 1000}],
                    'Referencia': [{'TpoDocRef': 'SET', 'FolioRef': 1, 'RazonRef': 'x' * 100}],
                    'DscRcgGlobal': [{'GlosaDR': 'Descuento “especial”'}],
                }],
            }],
        }

    def test_payload_sanitizes_whitelisted_keys_only(self):
        data = self._payload()
        original = copy.deepcopy(data)
        clean, changes = sanitize_dte_payload(data)
        self.assertEqual(data, original, 'el payload de entrada no debe mutar')

        self.assertEqual(clean['Emisor']['RznSoc'], 'Empresa X')
        self.assertEqual(clean['Emisor']['GiroEmis'], 'Venta - menor')
        self.assertEqual(clean['Emisor']['RUTEmisor'], '76.000.000-0')
        self.assertEqual(clean['Emisor']['CorreoEmisor'], "o'neil@x.cl")
        self.assertEqual(clean['firma_electronica'], original['firma_electronica'])
        self.assertEqual(clean['Documento'][0]['caf_file'], original['Documento'][0]['caf_file'])

        doc = clean['Documento'][0]['documentos'][0]
        receptor = doc['Encabezado']['Receptor']
        self.assertEqual(receptor['RznSocRecep'], 'Pérez Y Hijos')
        self.assertEqual(receptor['CorreoRecep'], 'a&b@x.cl')
        self.assertEqual(receptor['RUTRecep'], '11.111.111-1')
        self.assertEqual(receptor['CiudadRecep'], '')
        self.assertEqual(doc['Encabezado']['IdDoc'], {'Folio': 10, 'FchEmis': '2026-10-01'})

        line = doc['Detalle'][0]
        self.assertEqual(line['NmbItem'], 'Prod 1')
        self.assertEqual(line['DscItem'], 'Línea larga')
        self.assertEqual(line['CdgItem'], [{'TpoCodigo': 'INT1', 'VlrCodigo': 'A&B'}])
        self.assertEqual(line['MontoItem'], 1000)
        self.assertEqual(doc['Referencia'][0]['RazonRef'], 'x' * 90)
        self.assertEqual(doc['Referencia'][0]['TpoDocRef'], 'SET')
        self.assertEqual(doc['DscRcgGlobal'][0]['GlosaDR'], 'Descuento especial')

        changed_keys = {key for key, _old, _new in changes}
        self.assertEqual(changed_keys, {'RznSoc', 'GiroEmis', 'RznSocRecep', 'NmbItem',
                                        'DscItem', 'RazonRef', 'GlosaDR'})

    def test_required_field_emptied_raises(self):
        with self.assertRaises(SiiRequiredFieldError):
            sanitize_dte_payload({'Detalle': [{'NmbItem': '😀'}]})

    def test_required_field_emptied_uses_fallback(self):
        clean, changes = sanitize_dte_payload(
            {'RznSocRecep': '王伟', 'NmbItem': '😀'},
            fallbacks={'RznSocRecep': 'Usuario Anonimo', 'NmbItem': 'Producto'},
        )
        self.assertEqual(clean, {'RznSocRecep': 'Usuario Anonimo', 'NmbItem': 'Producto'})
        self.assertEqual(len(changes), 2)

    def test_required_field_already_empty_is_kept(self):
        clean, changes = sanitize_dte_payload({'NmbItem': ''})
        self.assertEqual(clean, {'NmbItem': ''})
        self.assertEqual(changes, [])
