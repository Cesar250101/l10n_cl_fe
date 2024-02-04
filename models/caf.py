import logging
from datetime import date
import pytz
import ast
from dateutil.relativedelta import relativedelta
from lxml import etree

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.tools.translate import _

_logger = logging.getLogger(__name__)

try:
    import base64
except ImportError:
    pass


class CAF(models.Model):
    _name = "dte.caf"
    _description = "Archivo CAF"

    @api.onchange('start_nm', 'final_nm', 'folio_actual')
    @api.depends('start_nm', 'final_nm', 'folio_actual')
    def _get_qty_available(self):
        for r in self:
            r.qty_available = 0
            if r.state not in ['draft', 'spent']:
                r.qty_available = 1 + (r.final_nm - r.folio_actual)

    def _get_tables(self):
        return ['account_move']

    def _account_move_where_string_and_param(self):
        where_string = """WHERE
            state IN ('posted', 'cancel')
            AND document_class_id = %(document_class_id)s
            AND use_documents
        """
        param = {
            'document_class_id': self.document_class_id.id
        }
        return where_string, param

    def _get_folio_actual(self):
        folio = 0
        if not self.document_class_id:
            return folio
        tables = self._get_tables()
        where_clauses = []
        for table in tables:
            where_string, param = getattr(self, "_%s_where_string_and_param" % table)()
            where_clauses.append("""
                    SELECT {field} FROM {table}
                    {where_string}
                    AND {field} >= {start_nm} AND {field} <= {final_nm}
            """.format(
                table=table,
                where_string=where_string,
                field='sii_document_number',
                start_nm= self.start_nm,
                final_nm= self.final_nm,
            ))
        if not where_clauses:
            return 0
        union = 'UNION ALL '.join(where_clauses)
        query = '''SELECT MAX({field})
FROM ({union}) AS combined'''.format(
            field='sii_document_number',
            union=union
        )
        self.env.cr.execute(query, param)
        folio = int((self.env.cr.fetchone() or [None])[0] or 0)
        if self.start_nm <= folio < self.final_nm:
            folios_anulados = ast.literal_eval(self.folios_anulados or '[]')
            def check_anulado(folio_check):
                folio_check += 1
                if folio_check in folios_anulados:
                    return check_anulado(folio_check)
                if folio_check > self.final_nm:
                    return self.final_nm
                return folio_check
            folio = check_anulado(folio)
            if folio > self.final_nm:
                self.state = 'spent'
                return self.final_nm
            if self.document_class_id.es_factura_afecta() or self.document_class_id.es_nc() or self.document_class_id.es_nd():
                folios_vencidos = ast.literal_eval(self.folios_vencidos or '[]')
                tz = pytz.timezone("America/Santiago")
                if folio in folios_vencidos or fields.Date.context_today(self.with_context(tz=tz)) >= self.expiration_date:
                    self.state = 'spent'
                    return self.final_nm
            return folio
        if folio > 0:
            self.state = 'spent'
            return self.final_nm
        return self.start_nm

    def compute_folio_actual(self):
        self.folio_actual = self._get_folio_actual()

    @api.onchange('caf_file', 'caf_string')
    @api.depends('caf_file', 'caf_string')
    def _load_data(self):
        for r in self:
            r.issued_date = False
            r.expiration_date = False
            r.document_class_id = False
            r.start_nm = False
            r.final_nm = False
            r.rut_n = False
            if r.caf_file:
                r.load_caf()

    name = fields.Char(string="File Name", readonly=True, related="filename",)
    filename = fields.Char(string="File Name", required=True,)
    caf_file = fields.Binary(string="CAF XML File", help="Upload the CAF XML File in this holder",)
    caf_string = fields.Text(string="Archivo CAF")
    issued_date = fields.Date(string="Issued Date", compute='_load_data', store=True)
    expiration_date = fields.Date(string="Expiration Date", compute='_load_data', store=True)
    document_class_id = fields.Many2one(
        'sii.document_class',
        string="SII Document Class",
        compute='_load_data', store=True
    )
    start_nm = fields.Integer(
        string="Start Number",
        help="CAF Starts from this number", compute='_load_data', store=True
    )
    final_nm = fields.Integer(
        string="End Number",
        help="CAF Ends to this number", compute='_load_data', store=True
    )
    state = fields.Selection(
        [("draft", "Draft"), ("in_use", "In Use"), ("spent", "Spent"),],
        string="Status",
        default="draft",
        help="""Draft: means it has not been used yet. You must put in in used
in order to make it available for use. Spent: means that the number interval
has been exhausted.""",
    )
    rut_n = fields.Char(string="RUT", compute='_load_data', store=True)
    company_id = fields.Many2one(
        "res.company", string="Company", required=False, default=lambda self: self.env.user.company_id,
    )
    sequence_id = fields.Many2one("ir.sequence", string="Sequence",
        domain="[('is_dte', '=', True)]")
    use_level = fields.Float(string="Use Level", compute="_used_level",)
    folio_actual = fields.Integer(
        string="Folio Actual",
        default=_get_folio_actual,
        )
    cantidad_folios = fields.Integer(
        string="Cantidad de Folios",
        compute='_get_cantidad_folios')
    qty_available = fields.Integer(
        string="Cantidad Disponible",
        compute="_get_qty_available",
        store=True,
        )
    cantidad_usados = fields.Integer(
        string="Cantidad de Folios Usados",
        compute='_get_usados')
    cantidad_folios_sin_usar = fields.Integer(
        string="Cantidad folios sin usar",
        default=0)
    folios_sin_usar = fields.Text(
        string="Folios sin usar")
    cantidad_folios_anulados = fields.Integer(
        string="Cantidad folios anulados",
        default=0)
    folios_anulados = fields.Text(
        string="Folios anulados")
    cantidad_folios_vencidos_sin_anular = fields.Integer(
        string="Cantidad folios vencidos sin anular",
        default=0)
    cantidad_folios_vencidos = fields.Integer(
        string="Cantidad folios vencidos",
        default=0)
    folios_vencidos = fields.Text(
        string="Folios Vencidos")
    _sql_constraints = [
        ("filename_unique", "unique(filename)", "Error! Filename Already Exist!"),
    ]
    _order = "start_nm DESC"

    def obtener_folios_sin_usar(self):
        if not self.folios_sin_usar:
            return []
        return ast.literal_eval(self.folios_sin_usar)

    def ingresar_folio_sin_usar(self, folio):
        folios = self.obtener_folios_sin_usar()
        if folio not in folios:
            folios.append(folio)
        self.folios_sin_usar = str(sorted(folios))
        self.cantidad_folios_sin_usar += 1

    def eliminar_folio_sin_usar(self, folio):
        folios_sin_usar = self.obtener_folios_sin_usar()
        if folio in folios_sin_usar:
            folios_sin_usar.remove(folio)
        self.folios_sin_usar = str(folios_sin_usar)

    def _join_inspeccionar(self):
        return 'LEFT JOIN account_move a on s = a.sii_document_number and a.document_class_id = %s' % self.document_class_id.id

    def _where_inspeccionar(self):
        return 'a.sii_document_number is null'

    def inspeccionar_folios_sin_usar(self):
        joins = self._join_inspeccionar()
        wheres = self._where_inspeccionar()
        self._cr.execute("SELECT s FROM generate_series({0},{1},1) s {2} WHERE {3}".format(
            self.start_nm,
            self.folio_actual,
            joins,
            wheres,
        ))
        folios = sorted([x[0] for x in self._cr.fetchall()])
        if self.folio_actual in folios:
            folios.remove(self.folio_actual)
        self.write({
            'folios_sin_usar': str(folios),
            'cantidad_folios_sin_usar': len(folios)
            })

    def load_caf(self):
        if not self.caf_file and not self.caf_string:
            return
        if not self.sequence_id:
            context = dict(self._context or {})
            self.sequence_id = context.get("default_sequence_id", False)
        if not self.caf_string:
            self.caf_string = base64.b64decode(self.caf_file).decode("ISO-8859-1")
        result = self.decode_caf().find("CAF/DA")
        self.start_nm = result.find("RNG/D").text
        self.final_nm = result.find("RNG/H").text
        dc = self.env["sii.document_class"].search([("sii_code", "=", result.find("TD").text)])
        self.document_class_id = dc.id
        fa = result.find("FA").text
        self.issued_date = fa
        if dc.es_factura_afecta() or dc.es_nc() or dc.es_nd() or dc.es_liquidacion() or dc.es_factura_compra():
            self.expiration_date = date(int(fa[:4]), int(fa[5:7]), int(fa[8:10])) + relativedelta(months=6)
        self.rut_n = result.find("RE").text
        if self.rut_n != self.company_id.partner_id.rut():
            raise UserError(
                _("Company vat %s should be the same that assigned company's vat: %s!")
                % (self.rut_n, self.company_id.partner_id.rut())
            )
        elif dc != self.sequence_id.sii_document_class_id:
            raise UserError(
                _(
                    """SII Document Type for this CAF is %s and selected sequence
associated document class is %s. This values should be equal for DTE Invoicing
to work properly!"""
                )
                % (self.document_class_id.sii_code, self.sequence_id.sii_document_class_id.sii_code)
            )
        self.state = "in_use"
        self.compute_folio_actual()

    def _get_cantidad_folios(self):
        for r in self:
            if r.state == 'draft':
                r.cantidad_folios = 0
            else:
                r.cantidad_folios = ((r.final_nm +1) - r.start_nm)

    def _get_usados(self):
        for r in self:
            r.cantidad_usados = r.cantidad_folios - r.qty_available

    def _used_level(self):
        for r in self:
            r.use_level = float(100 * r.cantidad_usados) / r.cantidad_folios

    def decode_caf(self):
        return etree.fromstring(self.caf_string)

    def expirar_folios(self):
        query = '''SELECT numero
FROM generate_series({0}, {1}) numero
WHERE NOT EXISTS (
    SELECT 1
    FROM account_move m
    WHERE m.sii_document_number = numero and m.document_class_id={2}
);'''.format(
    self.start_nm,
    self.final_nm,
    self.document_class_id.id
)
        folios_vencidos = []
        for x in self._cr.fetchall():
            self.eliminar_folio_sin_usar(x[0])
            folios_vencidos.append(x[0])
        self.write({
            'folios_vencidos': str(folios_vencidos),
            'cantidad_folios_vencidos': len(folios_vencidos),
            'cantidad_folios_vencidos_sin_anular': len(folios_vencidos)
            })

    def obtener_folios_anulados(self):
        if not self.folios_anulados:
            return []
        return ast.literal_eval(self.folios_anulados)

    def ingresar_folio_anulado(self, folio):
        folios = self.obtener_folios_anulados()
        if folio not in folios:
            folios.append(folio)
        self.folios_anulados = str(sorted(folios))
        self.cantidad_folios_anulados += 1

    def eliminar_folio_anulado(self, folio):
        folios = self.obtener_folios_anulados()
        if folio in folios:
            folios.remove(folio)
        self.folios_anulados = str(sorted(folios))

    def anular_folio(self, desde, hasta=False):
        if not hasta:
            hasta = desde
        wiz = self.env["dte.caf.apicaf"].create({
            'operacion': 'anular',
            'comany_id': self.company_id.id,
            'firma': self.env.user.get_digital_signature(self.company_id).id,

        })
        linea = False
        for l in wiz.lineas_disponibles:
            if l.inicial<=desde <= line.final:
                linea = l
        wiz.write({
            'folio_ini': desde,
            'foio_fin': hasta,
            'motivo': "Vencido",
            'linea_disponible_seleccionada': linea.id
        })
        wiz.obtener_caf()
        wiz.confirmar()
        self.cantidad_folios_anulados += len(hasta+1-desde)

    def after_anular_folios(self, inicio, final):
        folios_vencidos = ast.literal_eval(self.folios_vencidos or '[]')
        folios_sin_usar = self.obtener_folios_sin_usar()
        for r in range(inicio, final+1):
            if r in folios_vencidos:
                folios_vencidos.remove(r)
            if r in folios_sin_usar:
                self.eliminar_folio_sin_usar(r)
        self.write({
            'folios_vencidos': str(folios_vencidos),
            'cantidad_folios_vencidos': len(folios_vencidos),
            'cantidad_folios_vencidos_sin_anular': len(folios_vencidos)
            })
