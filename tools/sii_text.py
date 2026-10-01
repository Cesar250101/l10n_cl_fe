"""Saneamiento de texto libre para DTE del SII.

El XML del DTE se serializa en ISO-8859-1 (librería facturacion_electronica):
cualquier carácter fuera de Latin-1, de control o tipográfico (comillas curvas,
guiones largos, NBSP, emojis...) termina como referencia numérica o rompe el
esquema, y el SII rechaza el documento. Este módulo no depende del ORM.

Mantener sincronizado con l10n_cl_dte_point_of_sale/static/src/js/sii_text.js
(TED impreso en el ticket POS).
"""
import copy
import logging
import re
import unicodedata

from markupsafe import Markup, escape

_logger = logging.getLogger(__name__)

# Reemplazos explícitos. Se aplican antes del filtro de rangos válidos.
SII_CHAR_MAP = {
    # Espacios y saltos de línea -> espacio simple
    "\t": " ", "\n": " ", "\r": " ", "\v": " ", "\f": " ",
    " ": " ", " ": " ", " ": " ", "　": " ",
    " ": " ", " ": " ",
    # Caracteres invisibles -> eliminar
    "­": "", "​": "", "‌": "", "‍": "", "⁠": "", "﻿": "",
    # Guiones tipográficos -> guion simple
    "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
    "―": "-", "−": "-",
    # Viñetas
    "•": "-", "·": "-",
    # Elipsis
    "…": "...",
    # Comillas (tipográficas y rectas) y acentos sueltos -> eliminar
    '"': "", "'": "", "`": "", "´": "",
    "‘": "", "’": "", "‚": "", "‛": "",
    "“": "", "”": "", "„": "", "‟": "",
    "«": "", "»": "", "‹": "", "›": "",
    # Caracteres reservados XML (compatibilidad con _special_characters_replace)
    "&": "Y", "<": "", ">": "",
    # Monedas fuera de Latin-1
    "€": "EUR",
}
for _cp in range(0x2000, 0x200B):  # espacios Unicode de ancho variable
    SII_CHAR_MAP[chr(_cp)] = " "

# Claves de texto libre del payload de timbrado y su largo máximo según el XSD SII.
SII_TEXT_FIELDS = {
    # Emisor
    "RznSoc": 100, "RznSocEmisor": 100, "GiroEmis": 80, "GiroEmisor": 80,
    "Sucursal": 20, "DirOrigen": 70, "CmnaOrigen": 20, "CiudadOrigen": 20,
    # Receptor
    "RznSocRecep": 100, "GiroRecep": 40, "Contacto": 80, "DirRecep": 70,
    "CmnaRecep": 20, "CiudadRecep": 20,
    # Transporte
    "Patente": 8, "NombreChofer": 30, "DirDest": 70, "CmnaDest": 20, "CiudadDest": 20,
    # Detalle
    "NmbItem": 80, "DscItem": 1000, "UnmdItem": 4,
    # Descuentos/recargos globales, referencias y comisiones
    "GlosaDR": 45, "RazonRef": 90, "Glosa": 60,
}

# Campos obligatorios para el SII: no pueden quedar vacíos tras sanear.
SII_REQUIRED_FIELDS = {"RznSoc", "RznSocEmisor", "GiroEmis", "GiroEmisor", "RznSocRecep", "NmbItem"}

# Ramas del payload que no son texto del documento (firma, CAF, request ya firmado).
SII_SKIP_KEYS = {"firma_electronica", "caf_file", "sii_xml_request"}

_MULTI_SPACE = re.compile(r" {2,}")


class SiiRequiredFieldError(ValueError):
    """Un campo obligatorio quedó vacío después del saneamiento."""

    def __init__(self, field, original):
        super().__init__(field, original)
        self.field = field
        self.original = original


def _is_valid(ch):
    o = ord(ch)
    return 0x20 <= o <= 0x7E or 0xA0 <= o <= 0xFF


def _clean_char(ch, fallback=True):
    if ch in SII_CHAR_MAP:
        return SII_CHAR_MAP[ch]
    if _is_valid(ch):
        return ch
    category = unicodedata.category(ch)
    if category.startswith("Z"):
        return " "
    if category.startswith("C") or not fallback:
        return ""
    # Respaldo: descomposición de compatibilidad sin marcas combinables (ő -> o, ﬁ -> fi, ™ -> TM)
    decomposed = unicodedata.normalize("NFKD", ch)
    return "".join(
        _clean_char(c, fallback=False) for c in decomposed if not unicodedata.combining(c)
    )


def sanitize_sii_text(text, max_len=None):
    """Devuelve ``text`` sin caracteres inválidos para el SII.

    Los valores que no son ``str`` (None, False, números) se devuelven tal cual.
    La función es idempotente y el resultado siempre es codificable en ISO-8859-1.
    """
    if not isinstance(text, str):
        return text
    text = unicodedata.normalize("NFC", text)
    text = "".join(_clean_char(ch) for ch in text)
    text = _MULTI_SPACE.sub(" ", text).strip()
    if max_len:
        text = text[:max_len].rstrip()
    return text


def sanitize_dte_payload(data, fallbacks=None):
    """Sanea las claves de texto libre de un payload de ``fe.timbrar``.

    Devuelve ``(payload_saneado, cambios)`` sin modificar ``data``; ``cambios`` es una
    lista de tuplas ``(clave, original, nuevo)``. Las claves se conservan aunque queden
    vacías (la librería ya acepta ''); un campo obligatorio con contenido que queda
    vacío al sanear toma el valor de ``fallbacks`` si existe, o lanza
    ``SiiRequiredFieldError``.
    """
    changes = []
    fallbacks = fallbacks or {}

    def walk(node):
        if isinstance(node, dict):
            result = {}
            for key, value in node.items():
                if key in SII_SKIP_KEYS:
                    result[key] = value
                elif key in SII_TEXT_FIELDS and isinstance(value, str):
                    new = sanitize_sii_text(value, SII_TEXT_FIELDS[key])
                    if not new and value.strip() and key in SII_REQUIRED_FIELDS:
                        if not fallbacks.get(key):
                            raise SiiRequiredFieldError(key, value)
                        new = fallbacks[key]
                    if new != value:
                        changes.append((key, value, new))
                    result[key] = new
                else:
                    result[key] = walk(value)
            return result
        if isinstance(node, (list, tuple)):
            return type(node)(walk(item) for item in node)
        return copy.copy(node)

    return walk(data), changes


def sii_sanitize_record_payload(record, datos, company, fallbacks=None, limit=30):
    """Aplica el saneamiento al payload de timbrado de ``record`` si la compañía lo tiene activo.

    Registra los reemplazos en el chatter del registro (o, sin chatter, solo los nombres
    de campo en el log) y convierte un campo obligatorio vacío sin ``fallbacks`` en
    ``UserError``.
    """
    from odoo import _
    from odoo.exceptions import UserError

    if not company.dte_sanitize_text:
        return datos
    try:
        clean, changes = sanitize_dte_payload(datos, fallbacks)
    except SiiRequiredFieldError as e:
        raise UserError(
            _("El campo %s del DTE queda vacío al eliminar los caracteres inválidos para el SII "
              "(valor original: \"%s\"). Corrija el dato de origen antes de validar.")
            % (e.field, e.original)
        )
    # El Emisor llega dos veces al payload (datos de empresa y Encabezado): no repetir.
    changes = list(dict.fromkeys(changes))
    if changes:
        if hasattr(record, "message_post"):
            items = Markup("").join(
                Markup("<li><b>%s</b>: %s &rarr; %s</li>") % (key, old, new or _("(vacío)"))
                for key, old, new in changes[:limit]
            )
            extra = Markup("")
            if len(changes) > limit:
                extra = Markup("<p>%s</p>") % (_("... y %s más") % (len(changes) - limit))
            record.message_post(
                body=Markup("<p>%s</p><ul>%s</ul>%s") % (
                    _("Caracteres inválidos para el SII reemplazados en el DTE:"), items, extra
                )
            )
        else:
            # Solo nombres de campo: los valores pueden contener datos personales.
            _logger.info(
                "DTE %s,%s: caracteres inválidos SII reemplazados en %s",
                record._name, record.id, sorted({key for key, _old, _new in changes}),
            )
    return clean
