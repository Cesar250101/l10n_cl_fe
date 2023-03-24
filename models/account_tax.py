import logging
import re
from datetime import datetime, time
from collections import defaultdict
import dateutil.relativedelta as relativedelta
import pytz
from lxml import html

from odoo import api, models, fields, _, Command
from odoo.tools.misc import formatLang
from .currency import float_round_custom
from odoo.tools.float_utils import float_round as round
from odoo.tools import frozendict

_logger = logging.getLogger(__name__)
try:
    import urllib3

    urllib3.disable_warnings()
    pool = urllib3.PoolManager()
except ImportError:
    _logger.warning("no se ha cargado urllib3")
try:
    import fitz
except Exception as e:
    fitz = False
    _logger.warning("error en PyMUPDF: %s" % str(e))
try:
    from io import BytesIO
except Exception as e:
    _logger.warning("error en BytesIO: %s" % str(e))
try:
    from PIL import Image
except Exception as e:
    _logger.warning("error en PIl: %s" % str(e))
try:
    import pytesseract
except Exception as e:
    pytesseract = False
    _logger.warning("error en pytesseract: %s" % str(e))

meses = {
    1: "Enero",
    2: "Febrero",
    3: "Marzo",
    4: "Abril",
    5: "Mayo",
    6: "Junio",
    7: "Julio",
    8: "Agosto",
    9: "Septiembre",
    10: "Octubre",
    11: "Noviembre",
    12: "Diciembre",
}
_cache_page = {}
_cache_list_page = {}
_cache_page_2 = {}


class SIITax(models.Model):
    _inherit = "account.tax"

    ind_exe = fields.Selection([
            ('1', 'No afecto o exento de IVA (10)'),
            ('2', 'Producto o servicio no es facturable'),
            ('3', 'Garantía de depósito por envases (Cervezas, Jugos, Aguas Minerales, Bebidas Analcohólicas u otros autorizados por Resolución especial)'),
            ('4', 'Ítem No Venta. (Para facturas y guías de despacho (ésta última con Indicador Tipo de Traslado de Bienes igual a 1) y este ítem no será facturado.'),
            ('5', 'Ítem a rebajar. Para guías de despacho NO VENTA que rebajan guía anterior. En el área de referencias se debe indicar la guía anterior.'),
            ('6', 'Producto o servicio no facturable negativo (excepto en liquidaciones-factura)'),
        ],
        string="Indicador Exento por defecto"
    )
    include_base_amount_cl = fields.Boolean(
        string="Base Precio Incluído Chileno"
    )
    mepco_origen = fields.Selection([
        ('sii', 'Página del SII'),
        ('diario', 'Página DiarioOficial.cl'),
        ('pdf', 'PDF subido según formato DiarioOficial'),
        ('manual', 'Manual'),
        ],
        string="Origen actualización Mepco",
        default=lambda self: 'diario' if self.mepco else 'manual',
    )

    @api.onchange('mepco_origen')
    def _verificar_dependencias_python(self):
        if self.mepco_origen in ['diario', 'pdf']:
            if not fitz:
                raise UserError("Debe instalar la dependencia python PyMuPDF y luego reiniciar el servicio de odoo")
            elif fitz.version[0] < "1.21.1":
                raise UserError("Debe actualizar la dependencia python PyMuPDF>=1.21.1 y luego reiniciar el servicio de odoo")
            if not pytesseract:
                raise UserError("Debe instalar la dependencia python pytesseract\
                                y tambien los paquetes deb con sudo apt install \
                                tesseract-ocr libtesseract-dev y luego reiniciar \
                                el servicio de odoo")
            elif pytesseract.__version__ < "0.3.10":
                raise UserError("Debe actualizar la dependencia python pytesseract>=0.3.10 y luego reiniciar el servicio de odoo")

    def es_adicional(self):
        return self.sii_code in [24, 25, 26, 27, 271]

    def es_especifico(self):
        return self.sii_code in [28, 35, 51]

    @api.onchange('sii_code', 'price_include')
    def autoseleccionar_detailed(self):
        self.sii_detailed = self.price_include and (self.es_adicional() or self.es_especifico())
        self.include_base_amount_cl = self.price_include

    def compute_factor(self, uom_id):
        amount_tax = self.amount or 0.0
        if self.uom_id and self.uom_id != uom_id:
            if self._context.get("date"):
                mepco = self._target_mepco(self._context.get("date"))
                amount_tax = mepco.amount
            amount_tax = self.uom_id._compute_price(amount_tax, uom_id)
        return amount_tax

    def _fix_composed_included_tax(self, base, quantity, uom_id):
        composed_tax = {}
        price_included = False
        percent = 0.0
        rec = 0.0
        for tax in self.sorted(key=lambda r: r.sequence):
            if tax.price_include:
                price_included = True
            else:
                continue
            if tax.amount_type == "percent":
                percent += tax.amount
            else:
                amount_tax = tax.compute_factor(uom_id)
                rec += quantity * amount_tax
        if price_included:
            _base = base - rec
            common_base = _base / (1 + percent / 100.0)
            for tax in self.sorted(key=lambda r: r.sequence):
                if tax.amount_type == "percent":
                    composed_tax[tax.id] = common_base * (1 + tax.amount / 100)
        return composed_tax

    def compute_factor(self, uom_id):
        amount_tax = self.amount or 0.0
        if self.uom_id and self.uom_id != uom_id:
            factor = self.uom_id._compute_quantity(1, uom_id)
            amount_tax = (amount_tax / factor)
        return amount_tax

    def _compute_amount(self, base_amount, price_unit, quantity=1.0, product=None, partner=None, fixed_multiplicator=1, uom_id=None):
        """ Returns the amount of a single tax. base_amount is the actual amount on which the tax is applied, which is
            price_unit * quantity eventually affected by previous taxes (if tax is include_base_amount XOR price_include)
        """
        self.ensure_one()
        if self.amount_type == 'fixed':
            # Use copysign to take into account the sign of the base amount which includes the sign
            # of the quantity and the sign of the price_unit
            # Amount is the fixed price for the tax, it can be negative
            # Base amount included the sign of the quantity and the sign of the unit price and when
            # a product is returned, it can be done either by changing the sign of quantity or by changing the
            # sign of the price unit.
            # When the price unit is equal to 0, the sign of the quantity is absorbed in base_amount then
            # a "else" case is needed
            amount_tax = self.compute_factor(uom_id)
            if base_amount:
                return math.copysign(quantity, base_amount) * amount_tax * abs(fixed_multiplicator)
            else:
                return quantity * amount_tax
        price_include = self.price_include or self._context.get('force_price_include')

        if (self.amount_type == 'percent' and not price_include) or (self.amount_type == 'division' and price_include):
            return base_amount * self.amount / 100
        if self.amount_type == 'percent' and price_include:
            return base_amount - (base_amount / (1 + self.amount / 100))
        if self.amount_type == 'division' and not price_include:
            return base_amount / (1 - self.amount / 100) - base_amount

    def compute_all(self, price_unit, currency=None, quantity=1.0, product=None, partner=None, is_refund=False, handle_price_include=True, include_caba_tags=False, fixed_multiplicator=1, discount=None, uom_id=None):
        """Compute all information required to apply taxes (in self + their children in case of a tax group).
        We consider the sequence of the parent for group of taxes.
            Eg. considering letters as taxes and alphabetic order as sequence :
            [G, B([A, D, F]), E, C] will be computed as [A, D, F, C, E, G]



        :param price_unit: The unit price of the line to compute taxes on.
        :param currency: The optional currency in which the price_unit is expressed.
        :param quantity: The optional quantity of the product to compute taxes on.
        :param product: The optional product to compute taxes on.
            Used to get the tags to apply on the lines.
        :param partner: The optional partner compute taxes on.
            Used to retrieve the lang to build strings and for potential extensions.
        :param is_refund: The optional boolean indicating if this is a refund.
        :param handle_price_include: Used when we need to ignore all tax included in price. If False, it means the
            amount passed to this method will be considered as the base of all computations.
        :param include_caba_tags: The optional boolean indicating if CABA tags need to be taken into account.
        :param fixed_multiplicator: The amount to multiply fixed amount taxes by.
        :return: {
            'total_excluded': 0.0,    # Total without taxes
            'total_included': 0.0,    # Total with taxes
            'total_void'    : 0.0,    # Total with those taxes, that don't have an account set
            'base_tags: : list<int>,  # Tags to apply on the base line
            'taxes': [{               # One dict for each tax in self and their children
                'id': int,
                'name': str,
                'amount': float,
                'base': float,
                'sequence': int,
                'account_id': int,
                'refund_account_id': int,
                'analytic': bool,
                'price_include': bool,
                'tax_exigibility': str,
                'tax_repartition_line_id': int,
                'group': recordset,
                'tag_ids': list<int>,
                'tax_ids': list<int>,
            }],
        } """
        if not self:
            company = self.env.company
        else:
            company = self[0].company_id

        # 1) Flatten the taxes.
        taxes, groups_map = self.flatten_taxes_hierarchy(create_map=True)

        # 2) Deal with the rounding methods
        if not currency:
            currency = company.currency_id

        # By default, for each tax, tax amount will first be computed
        # and rounded at the 'Account' decimal precision for each
        # PO/SO/invoice line and then these rounded amounts will be
        # summed, leading to the total amount for that tax. But, if the
        # company has tax_calculation_rounding_method = round_globally,
        # we still follow the same method, but we use a much larger
        # precision when we round the tax amount for each line (we use
        # the 'Account' decimal precision + 5), and that way it's like
        # rounding after the sum of the tax amounts of each line
        prec = currency.rounding

        # In some cases, it is necessary to force/prevent the rounding of the tax and the total
        # amounts. For example, in SO/PO line, we don't want to round the price unit at the
        # precision of the currency.
        # The context key 'round' allows to force the standard behavior.
        round_tax = False if company.tax_calculation_rounding_method == 'round_globally' else True
        if 'round' in self.env.context:
            round_tax = bool(self.env.context['round'])

        if not round_tax:
            prec *= 1e-5

        # 3) Iterate the taxes in the reversed sequence order to retrieve the initial base of the computation.
        #     tax  |  base  |  amount  |
        # /\ ----------------------------
        # || tax_1 |  XXXX  |          | <- we are looking for that, it's the total_excluded
        # || tax_2 |   ..   |          |
        # || tax_3 |   ..   |          |
        # ||  ...  |   ..   |    ..    |
        #    ----------------------------
        def recompute_base(base_amount, fixed_amount, percent_amount, division_amount):
            # Recompute the new base amount based on included fixed/percent amounts and the current base amount.
            # Example:
            #  tax  |  amount  |   type   |  price_include  |
            # -----------------------------------------------
            # tax_1 |   10%    | percent  |  t
            # tax_2 |   15     |   fix    |  t
            # tax_3 |   20%    | percent  |  t
            # tax_4 |   10%    | division |  t
            # -----------------------------------------------

            # if base_amount = 145, the new base is computed as:
            # (145 - 15) / (1.0 + 30%) * 90% = 130 / 1.3 * 90% = 90
            return (base_amount - fixed_amount) / (1.0 + percent_amount / 100.0) * (100 - division_amount) / 100

        # The first/last base must absolutely be rounded to work in round globally.
        # Indeed, the sum of all taxes ('taxes' key in the result dictionary) must be strictly equals to
        # 'price_included' - 'price_excluded' whatever the rounding method.
        #
        # Example using the global rounding without any decimals:
        # Suppose two invoice lines: 27000 and 10920, both having a 19% price included tax.
        #
        #                   Line 1                      Line 2
        # -----------------------------------------------------------------------
        # total_included:   27000                       10920
        # tax:              27000 / 1.19 = 4310.924     10920 / 1.19 = 1743.529
        # total_excluded:   22689.076                   9176.471
        #
        # If the rounding of the total_excluded isn't made at the end, it could lead to some rounding issues
        # when summing the tax amounts, e.g. on invoices.
        # In that case:
        #  - amount_untaxed will be 22689 + 9176 = 31865
        #  - amount_tax will be 4310.924 + 1743.529 = 6054.453 ~ 6054
        #  - amount_total will be 31865 + 6054 = 37919 != 37920 = 27000 + 10920
        #
        # By performing a rounding at the end to compute the price_excluded amount, the amount_tax will be strictly
        # equals to 'price_included' - 'price_excluded' after rounding and then:
        #   Line 1: sum(taxes) = 27000 - 22689 = 4311
        #   Line 2: sum(taxes) = 10920 - 2176 = 8744
        #   amount_tax = 4311 + 8744 = 13055
        #   amount_total = 31865 + 13055 = 37920
        if prec == 1e-5:
            base = float_round_custom(price_unit * quantity, precision_digits=2)
            base = float_round_custom(base, precision_digits=0)
            if discount:
                disc =  float_round_custom((base * ((discount or 0.0) /100.0)),
                                           precision_digits=0)
                base -= disc
        else:
            if discount:
                price_unit *= (1 - (discount / 100.0))
            base = currency.round(price_unit * quantity)


        # For the computation of move lines, we could have a negative base value.
        # In this case, compute all with positive values and negate them at the end.
        sign = 1
        if currency.is_zero(base):
            sign = -1 if fixed_multiplicator < 0 else 1
        elif base < 0:
            sign = -1
            base = -base

        # Store the totals to reach when using price_include taxes (only the last price included in row)
        total_included_checkpoints = {}
        i = len(taxes) - 1
        store_included_tax_total = True
        # Keep track of the accumulated included fixed/percent amount.
        incl_fixed_amount = incl_percent_amount = incl_division_amount = 0
        # Store the tax amounts we compute while searching for the total_excluded
        cached_tax_amounts = {}
        if handle_price_include:
            for tax in reversed(taxes):
                tax_repartition_lines = (
                    is_refund
                    and tax.refund_repartition_line_ids
                    or tax.invoice_repartition_line_ids
                ).filtered(lambda x: x.repartition_type == "tax")
                sum_repartition_factor = sum(tax_repartition_lines.mapped("factor"))
                if tax.include_base_amount and not tax.include_base_amount_cl:
                    base = recompute_base(base, incl_fixed_amount, incl_percent_amount, incl_division_amount)
                    incl_fixed_amount = incl_percent_amount = incl_division_amount = 0
                    store_included_tax_total = True
                if tax.include_base_amount:
                    base = recompute_base(base, incl_fixed_amount, incl_percent_amount, incl_division_amount)
                    incl_fixed_amount = incl_percent_amount = incl_division_amount = 0
                    store_included_tax_total = True
                if tax.price_include or self._context.get('force_price_include'):
                    if tax.amount_type == 'percent':
                        incl_percent_amount += tax.amount * sum_repartition_factor
                    elif tax.amount_type == 'division':
                        incl_division_amount += tax.amount * sum_repartition_factor
                    elif tax.amount_type == 'fixed':
                        incl_fixed_amount += abs(quantity) * tax.amount * sum_repartition_factor * abs(fixed_multiplicator)
                    else:
                        # tax.amount_type == other (python)
                        tax_amount = tax._compute_amount(base, sign * price_unit, quantity, product, partner, fixed_multiplicator, uom_id=uom_id) * sum_repartition_factor
                        incl_fixed_amount += tax_amount
                        # Avoid unecessary re-computation
                        cached_tax_amounts[i] = tax_amount
                    # In case of a zero tax, do not store the base amount since the tax amount will
                    # be zero anyway. Group and Python taxes have an amount of zero, so do not take
                    # them into account.
                    if store_included_tax_total and (
                        tax.amount or tax.amount_type not in ("percent", "division", "fixed")
                    ):
                        total_included_checkpoints[i] = base
                        store_included_tax_total = False
                i -= 1

        total_excluded = currency.round(recompute_base(base, incl_fixed_amount, incl_percent_amount, incl_division_amount))

        # 4) Iterate the taxes in the sequence order to compute missing tax amounts.
        # Start the computation of accumulated amounts at the total_excluded value.
        base = total_included = total_void = total_excluded

        # Flag indicating the checkpoint used in price_include to avoid rounding issue must be skipped since the base
        # amount has changed because we are currently mixing price-included and price-excluded include_base_amount
        # taxes.
        skip_checkpoint = False

        # Get product tags, account.account.tag objects that need to be injected in all
        # the tax_tag_ids of all the move lines created by the compute all for this product.
        product_tag_ids = product.account_tag_ids.ids if product else []

        taxes_vals = []
        i = 0
        cumulated_tax_included_amount = 0
        for tax in taxes:
            price_include = self._context.get('force_price_include', tax.price_include)

            if price_include or tax.is_base_affected:
                tax_base_amount = base
            else:
                tax_base_amount = total_excluded

            tax_repartition_lines = (is_refund and tax.refund_repartition_line_ids or tax.invoice_repartition_line_ids).filtered(lambda x: x.repartition_type == 'tax')
            sum_repartition_factor = sum(tax_repartition_lines.mapped('factor'))

            #compute the tax_amount
            if price_include and tax.include_base_amount_cl:
                tax_amount = tax.with_context(force_price_include=False)._compute_amount(
                    total_excluded, sign * price_unit, quantity, product, partner, uom_id=uom_id)
            if not skip_checkpoint and price_include and total_included_checkpoints.get(i) is not None and sum_repartition_factor != 0:
                # We know the total to reach for that tax, so we make a substraction to avoid any rounding issues
                tax_amount = total_included_checkpoints[i] - (base + cumulated_tax_included_amount)
                cumulated_tax_included_amount = 0
            else:
                tax_amount = tax.with_context(force_price_include=False)._compute_amount(
                    tax_base_amount, sign * price_unit, quantity, product, partner, fixed_multiplicator, uom_id=uom_id)

            # Round the tax_amount multiplied by the computed repartition lines factor.
            tax_amount = round(tax_amount, precision_rounding=prec)
            factorized_tax_amount = round(tax_amount * sum_repartition_factor, precision_rounding=prec)

            if not tax.include_base_amount_cl and price_include and total_included_checkpoints.get(i) is None:
                cumulated_tax_included_amount += factorized_tax_amount

            # If the tax affects the base of subsequent taxes, its tax move lines must
            # receive the base tags and tag_ids of these taxes, so that the tax report computes
            # the right total
            subsequent_taxes = self.env['account.tax']
            subsequent_tags = self.env['account.account.tag']
            if tax.include_base_amount:
                subsequent_taxes = taxes[i+1:].filtered('is_base_affected')

                taxes_for_subsequent_tags = subsequent_taxes

                if not include_caba_tags:
                    taxes_for_subsequent_tags = subsequent_taxes.filtered(lambda x: x.tax_exigibility != 'on_payment')

                subsequent_tags = taxes_for_subsequent_tags.get_tax_tags(is_refund, 'base')

            # Compute the tax line amounts by multiplying each factor with the tax amount.
            # Then, spread the tax rounding to ensure the consistency of each line independently with the factorized
            # amount. E.g:
            #
            # Suppose a tax having 4 x 50% repartition line applied on a tax amount of 0.03 with 2 decimal places.
            # The factorized_tax_amount will be 0.06 (200% x 0.03). However, each line taken independently will compute
            # 50% * 0.03 = 0.01 with rounding. It means there is 0.06 - 0.04 = 0.02 as total_rounding_error to dispatch
            # in lines as 2 x 0.01.
            repartition_line_amounts = [round(tax_amount * line.factor, precision_rounding=prec) for line in tax_repartition_lines]
            total_rounding_error = round(factorized_tax_amount - sum(repartition_line_amounts), precision_rounding=prec)
            nber_rounding_steps = int(abs(total_rounding_error / currency.rounding))
            rounding_error = round(nber_rounding_steps and total_rounding_error / nber_rounding_steps or 0.0, precision_rounding=prec)
            line_retencion = 0
            for repartition_line, line_amount in zip(tax_repartition_lines, repartition_line_amounts):

                if nber_rounding_steps:
                    line_amount += rounding_error
                    nber_rounding_steps -= 1
                if repartition_line.sii_type in ['R', 'A']:
                    line_retencion += line_amount

                if not include_caba_tags and tax.tax_exigibility == 'on_payment':
                    repartition_line_tags = self.env['account.account.tag']
                else:
                    repartition_line_tags = repartition_line.tag_ids

                taxes_vals.append({
                    'id': tax.id,
                    'name': partner and tax.with_context(lang=partner.lang).name or tax.name,
                    'amount': sign * line_amount,
                    'amount_retencion': sign * line_retencion,
                    'base': round(sign * tax_base_amount, precision_rounding=prec),
                    'sequence': tax.sequence,
                    'account_id': tax.cash_basis_transition_account_id.id if tax.tax_exigibility == 'on_payment' else repartition_line.account_id.id,
                    'analytic': tax.analytic,
                    'use_in_tax_closing': repartition_line.use_in_tax_closing,
                    'price_include': price_include,
                    'tax_exigibility': tax.tax_exigibility,
                    'tax_repartition_line_id': repartition_line.id,
                    'group': groups_map.get(tax),
                    'tag_ids': (repartition_line_tags + subsequent_tags).ids + product_tag_ids,
                    'tax_ids': subsequent_taxes.ids,
                })

                if not repartition_line.account_id:
                    total_void += line_amount

            # Affect subsequent taxes
            if tax.include_base_amount or tax.include_base_amount_cl:
                base += factorized_tax_amount
                if not price_include:
                    skip_checkpoint = True
            total_included += factorized_tax_amount - line_retencion
            i += 1

        base_taxes_for_tags = taxes
        if not include_caba_tags:
            base_taxes_for_tags = base_taxes_for_tags.filtered(lambda x: x.tax_exigibility != 'on_payment')

        base_rep_lines = base_taxes_for_tags.mapped(is_refund and 'refund_repartition_line_ids' or 'invoice_repartition_line_ids').filtered(lambda x: x.repartition_type == 'base')
        return {
            'base_tags': base_rep_lines.tag_ids.ids + product_tag_ids,
            'taxes': taxes_vals,
            'total_excluded': sign * total_excluded,
            'total_included': sign * currency.round(total_included),
            'total_void': sign * currency.round(total_void),
        }

    @api.model
    def _convert_to_tax_line_dict(
            self, tax_line,
            partner=None, currency=None, taxes=None, tax_tags=None, tax_repartition_line=None,
            group_tax=None, account=None, analytic_distribution=None, tax_amount=None,
    ):
        vals = super(SIITax, self)._convert_to_tax_line_dict(
            tax_line,
            partner, currency, taxes, tax_tags, tax_repartition_line,
            group_tax, account, analytic_distribution, tax_amount,
        )
        vals['tax_amount_retencion'] = 0
        if vals['tax_repartition_line'].sii_type in ['R', 'A']:
            vals['tax_amount_retencion'] = tax_amount
        return vals

    @api.model
    def _compute_taxes_for_single_line(self, base_line, handle_price_include=True, include_caba_tags=False, early_pay_discount_computation=None, early_pay_discount_percentage=None):
        orig_price_unit_after_discount = base_line['price_unit'] * (1 - (base_line['discount'] / 100.0))
        price_unit_after_discount = orig_price_unit_after_discount
        taxes = base_line['taxes']._origin
        currency = base_line['currency'] or self.env.company.currency_id
        rate = base_line['rate']

        if early_pay_discount_computation in ('included', 'excluded'):
            remaining_part_to_consider = (100 - early_pay_discount_percentage) / 100.0
            price_unit_after_discount = remaining_part_to_consider * price_unit_after_discount

        if taxes:

            if handle_price_include is None:
                manage_price_include = bool(base_line['handle_price_include'])
            else:
                manage_price_include = handle_price_include

            taxes_res = taxes.with_context(**base_line['extra_context']).compute_all(
                price_unit_after_discount,
                currency=currency,
                quantity=base_line['quantity'],
                product=base_line['product'],
                partner=base_line['partner'],
                is_refund=base_line['is_refund'],
                handle_price_include=manage_price_include,
                include_caba_tags=include_caba_tags,
            )

            to_update_vals = {
                'tax_tag_ids': [Command.set(taxes_res['base_tags'])],
                'price_subtotal': taxes_res['total_excluded'],
                'price_total': taxes_res['total_included'],
            }

            if early_pay_discount_computation == 'excluded':
                new_taxes_res = taxes.with_context(**base_line['extra_context']).compute_all(
                    orig_price_unit_after_discount,
                    currency=currency,
                    quantity=base_line['quantity'],
                    product=base_line['product'],
                    partner=base_line['partner'],
                    is_refund=base_line['is_refund'],
                    handle_price_include=manage_price_include,
                    include_caba_tags=include_caba_tags,
                )
                for tax_res, new_taxes_res in zip(taxes_res['taxes'], new_taxes_res['taxes']):
                    delta_tax = new_taxes_res['amount'] - tax_res['amount']
                    tax_res['amount'] += delta_tax
                    to_update_vals['price_total'] += delta_tax

            tax_values_list = []
            for tax_res in taxes_res['taxes']:
                tax_amount = tax_res['amount'] / rate
                tax_amount_retencion = tax_res['amount_retencion'] / rate
                if self.company_id.tax_calculation_rounding_method == 'round_per_line':
                    tax_amount = currency.round(tax_amount)
                    tax_amount_retencion = currency.round(tax_amount_retencion)
                tax_rep = self.env['account.tax.repartition.line'].browse(tax_res['tax_repartition_line_id'])
                tax_values_list.append({
                    **tax_res,
                    'tax_repartition_line': tax_rep,
                    'base_amount_currency': tax_res['base'],
                    'base_amount': currency.round(tax_res['base'] / rate),
                    'tax_amount_currency': tax_res['amount'],
                    'tax_amount_retencion_currency': tax_res['amount_retencion'],
                    'tax_amount': tax_amount,
                    'tax_amount_retencion': tax_amount_retencion,
                })

        else:
            price_subtotal = currency.round(price_unit_after_discount * base_line['quantity'])
            to_update_vals = {
                'tax_tag_ids': [Command.clear()],
                'price_subtotal': price_subtotal,
                'price_total': price_subtotal,
            }
            tax_values_list = []
        return to_update_vals, tax_values_list

    @api.model
    def _aggregate_taxes(self, to_process, filter_tax_values_to_apply=None, grouping_key_generator=None):

        def default_grouping_key_generator(base_line, tax_values):
            return {'tax': tax_values['tax_repartition_line'].tax_id}

        global_tax_details = {
            'base_amount_currency': 0.0,
            'base_amount': 0.0,
            'tax_amount_currency': 0.0,
            'tax_amount_retencion_currency': 0.0,
            'tax_amount': 0.0,
            'tax_amount_retencion': 0.0,
            'tax_details': defaultdict(lambda: {
                'base_amount_currency': 0.0,
                'base_amount': 0.0,
                'tax_amount_currency': 0.0,
                'tax_amount_retencion_currency': 0.0,
                'tax_amount': 0.0,
                'tax_amount_retencion': 0.0,
                'group_tax_details': [],
                'records': set(),
            }),
            'tax_details_per_record': defaultdict(lambda: {
                'base_amount_currency': 0.0,
                'base_amount': 0.0,
                'tax_amount_currency': 0.0,
                'tax_amount_retencion_currency': 0.0,
                'tax_amount': 0.0,
                'tax_amount_retencion': 0.0,
                'tax_details': defaultdict(lambda: {
                    'base_amount_currency': 0.0,
                    'base_amount': 0.0,
                    'tax_amount_currency': 0.0,
                    'tax_amount_retencion_currency': 0.0,
                    'tax_amount': 0.0,
                    'tax_amount_retencion': 0.0,
                    'group_tax_details': [],
                    'records': set(),
                }),
            }),
        }

        def add_tax_values(record, results, grouping_key, serialized_grouping_key, tax_values):
            # Add to global results.
            results['tax_amount_currency'] += tax_values['tax_amount_currency']
            results['tax_amount_retencion_currency'] += tax_values['tax_amount_retencion_currency']
            results['tax_amount'] += tax_values['tax_amount']
            results['tax_amount_retencion'] += tax_values['tax_amount_retencion']

            # Add to tax details.
            if serialized_grouping_key not in results['tax_details']:
                tax_details = results['tax_details'][serialized_grouping_key]
                tax_details.update(grouping_key)
                tax_details['base_amount_currency'] = tax_values['base_amount_currency']
                tax_details['base_amount'] = tax_values['base_amount']
                tax_details['records'].add(record)
            else:
                tax_details = results['tax_details'][serialized_grouping_key]
                if record not in tax_details['records']:
                    tax_details['base_amount_currency'] += tax_values['base_amount_currency']
                    tax_details['base_amount'] += tax_values['base_amount']
                    tax_details['records'].add(record)
            tax_details['tax_amount_currency'] += tax_values['tax_amount_currency']
            tax_details['tax_amount_retencion_currency'] += tax_values['tax_amount_retencion_currency']
            tax_details['tax_amount'] += tax_values['tax_amount']
            tax_details['tax_amount_retencion'] += tax_values['tax_amount_retencion']
            tax_details['group_tax_details'].append(tax_values)

        grouping_key_generator = grouping_key_generator or default_grouping_key_generator

        for base_line, to_update_vals, tax_values_list in to_process:
            record = base_line['record']

            # Add to global tax amounts.
            global_tax_details['base_amount_currency'] += to_update_vals['price_subtotal']

            currency = base_line['currency'] or self.env.company.currency_id
            base_amount = currency.round(to_update_vals['price_subtotal'] / base_line['rate'])
            global_tax_details['base_amount'] += base_amount

            for tax_values in tax_values_list:
                if filter_tax_values_to_apply and not filter_tax_values_to_apply(base_line, tax_values):
                    continue

                grouping_key = grouping_key_generator(base_line, tax_values)
                serialized_grouping_key = frozendict(grouping_key)

                # Add to invoice line global tax amounts.
                if serialized_grouping_key not in global_tax_details['tax_details_per_record'][record]:
                    record_global_tax_details = global_tax_details['tax_details_per_record'][record]
                    record_global_tax_details['base_amount_currency'] = to_update_vals['price_subtotal']
                    record_global_tax_details['base_amount'] = base_amount
                else:
                    record_global_tax_details = global_tax_details['tax_details_per_record'][record]

                add_tax_values(record, global_tax_details, grouping_key, serialized_grouping_key, tax_values)
                add_tax_values(record, record_global_tax_details, grouping_key, serialized_grouping_key, tax_values)

        return global_tax_details

    @api.model
    def _compute_taxes(self, base_lines, tax_lines=None, handle_price_include=True, include_caba_tags=False):
        """ Generic method to compute the taxes for different business models.

        :param base_lines: A list of python dictionaries created using the '_convert_to_tax_base_line_dict' method.
        :param tax_lines: A list of python dictionaries created using the '_convert_to_tax_line_dict' method.
        :param handle_price_include:    Manage the price-included taxes. If None, use the 'handle_price_include' key
                                        set on base lines.
        :param include_caba_tags: Manage tags for taxes being exigible on_payment.
        :return: A python dictionary containing:

            The complete diff on tax lines if 'tax_lines' is passed as parameter:
            * tax_lines_to_add:     To create new tax lines.
            * tax_lines_to_delete:  To track the tax lines that are no longer used.
            * tax_lines_to_update:  The values to update the existing tax lines.

            * base_lines_to_update: The values to update the existing base lines:
                * tax_tag_ids:          The tags related to taxes.
                * price_subtotal:       The amount without tax.
                * price_total:          The amount with taxes.

            * totals:               A mapping for each involved currency to:
                * amount_untaxed:       The base amount without tax.
                * amount_tax:           The total tax amount.
        """
        res = {
            'tax_lines_to_add': [],
            'tax_lines_to_delete': [],
            'tax_lines_to_update': [],
            'base_lines_to_update': [],
            'totals': defaultdict(lambda: {
                'amount_untaxed': 0.0,
                'amount_tax': 0.0,
            }),
        }

        # =========================================================================================
        # BASE LINES
        # For each base line, populate 'base_lines_to_update'.
        # Compute 'tax_base_amount'/'tax_amount' for each pair <base line, tax repartition line>
        # using the grouping key generated by the '_get_generation_dict_from_base_line' method.
        # =========================================================================================

        to_process = []
        for base_line in base_lines:
            to_update_vals, tax_values_list = self._compute_taxes_for_single_line(
                base_line,
                handle_price_include=handle_price_include,
                include_caba_tags=include_caba_tags,
            )
            to_process.append((base_line, to_update_vals, tax_values_list))
            res['base_lines_to_update'].append((base_line, to_update_vals))
            currency = base_line['currency'] or self.env.company.currency_id
            res['totals'][currency]['amount_untaxed'] += to_update_vals['price_subtotal']

        # =========================================================================================
        # TAX LINES
        # Map each existing tax lines using the grouping key generated by the
        # '_get_generation_dict_from_tax_line' method.
        # Since everything is indexed using the grouping key, we are now able to decide if
        # (1) we can reuse an existing tax line and update its amounts
        # (2) some tax lines are no longer used and can be dropped
        # (3) we need to create new tax lines
        # =========================================================================================

        # Track the existing tax lines using the grouping key.
        existing_tax_line_map = {}
        for line_vals in tax_lines or []:
            grouping_key = frozendict(self._get_generation_dict_from_tax_line(line_vals))

            # After a modification (e.g. changing the analytic account of the tax line), if two tax lines are sharing
            # the same key, keep only one.
            if grouping_key in existing_tax_line_map:
                res['tax_lines_to_delete'].append(line_vals)
            else:
                existing_tax_line_map[grouping_key] = line_vals

        def grouping_key_generator(base_line, tax_values):
            return self._get_generation_dict_from_base_line(base_line, tax_values)

        # Update/create the tax lines.
        global_tax_details = self._aggregate_taxes(to_process, grouping_key_generator=grouping_key_generator)

        for grouping_key, tax_values in global_tax_details['tax_details'].items():
            if tax_values['currency_id']:
                currency = self.env['res.currency'].browse(tax_values['currency_id'])
                res['totals'][currency]['amount_tax'] += currency.round(tax_values['tax_amount'])

            if grouping_key in existing_tax_line_map:
                # Update an existing tax line.
                line_vals = existing_tax_line_map.pop(grouping_key)
                res['tax_lines_to_update'].append((line_vals, tax_values))
            else:
                # Create a new tax line.
                res['tax_lines_to_add'].append(tax_values)

        for line_vals in existing_tax_line_map.values():
            res['tax_lines_to_delete'].append(line_vals)

        return res

    @api.model
    def _prepare_tax_totals(self, base_lines, currency, tax_lines=None):
        """ Compute the tax totals details for the business documents.
        :param base_lines:  A list of python dictionaries created using the '_convert_to_tax_base_line_dict' method.
        :param currency:    The currency set on the business document.
        :param tax_lines:   Optional list of python dictionaries created using the '_convert_to_tax_line_dict' method.
                            If specified, the taxes will be recomputed using them instead of recomputing the taxes on
                            the provided base lines.
        :return: A dictionary in the following form:
            {
                'amount_total':                 The total amount to be displayed on the document, including every total
                                                types.
                'amount_untaxed':               The untaxed amount to be displayed on the document.
                'formatted_amount_total':       Same as amount_total, but as a string formatted accordingly with
                                                partner's locale.
                'formatted_amount_untaxed':     Same as amount_untaxed, but as a string formatted accordingly with
                                                partner's locale.
                'groups_by_subtotals':          A dictionary formed liked {'subtotal': groups_data}
                                                Where total_type is a subtotal name defined on a tax group, or the
                                                default one: 'Untaxed Amount'.
                                                And groups_data is a list of dict in the following form:
                    {
                        'tax_group_name':                   The name of the tax groups this total is made for.
                        'tax_group_amount':                 The total tax amount in this tax group.
                        'tax_group_base_amount':            The base amount for this tax group.
                        'formatted_tax_group_amount':       Same as tax_group_amount, but as a string formatted accordingly
                                                            with partner's locale.
                        'formatted_tax_group_base_amount':  Same as tax_group_base_amount, but as a string formatted
                                                            accordingly with partner's locale.
                        'tax_group_id':                     The id of the tax group corresponding to this dict.
                    }
                'subtotals':                    A list of dictionaries in the following form, one for each subtotal in
                                                'groups_by_subtotals' keys.
                    {
                        'name':                             The name of the subtotal
                        'amount':                           The total amount for this subtotal, summing all the tax groups
                                                            belonging to preceding subtotals and the base amount
                        'formatted_amount':                 Same as amount, but as a string formatted accordingly with
                                                            partner's locale.
                    }
                'subtotals_order':              A list of keys of `groups_by_subtotals` defining the order in which it needs
                                                to be displayed
            }
        """

        # ==== Compute the taxes ====

        to_process = []
        for base_line in base_lines:
            to_update_vals, tax_values_list = self._compute_taxes_for_single_line(base_line)
            to_process.append((base_line, to_update_vals, tax_values_list))

        def grouping_key_generator(base_line, tax_values):
            source_tax = tax_values['tax_repartition_line'].tax_id
            return {'tax_group': source_tax.tax_group_id}

        global_tax_details = self._aggregate_taxes(to_process, grouping_key_generator=grouping_key_generator)

        tax_group_vals_list = []
        for tax_detail in global_tax_details['tax_details'].values():
            tax_group_vals = {
                'tax_group': tax_detail['tax_group'],
                'base_amount': tax_detail['base_amount_currency'],
                'tax_amount': tax_detail['tax_amount_currency'],
                'tax_amount_retencion': tax_detail['tax_amount_retencion_currency'],
            }

            # Handle a manual edition of tax lines.
            if tax_lines is not None:
                matched_tax_lines = [
                    x
                    for x in tax_lines
                    if (x['group_tax'] or x['tax_repartition_line'].tax_id).tax_group_id == tax_detail['tax_group']
                ]
                if matched_tax_lines:
                    tax_group_vals['tax_amount'] = sum(x['tax_amount'] for x in matched_tax_lines)
                    tax_group_vals['tax_amount_retencion'] = sum(x['tax_amount_retencion'] for x in matched_tax_lines)

            tax_group_vals_list.append(tax_group_vals)

        tax_group_vals_list = sorted(tax_group_vals_list, key=lambda x: (x['tax_group'].sequence, x['tax_group'].id))

        # ==== Partition the tax group values by subtotals ====

        amount_untaxed = global_tax_details['base_amount_currency']
        amount_tax = 0.0
        amount_tax_retencion = 0.0

        subtotal_order = {}
        groups_by_subtotal = defaultdict(list)
        for tax_group_vals in tax_group_vals_list:
            tax_group = tax_group_vals['tax_group']

            subtotal_title = tax_group.preceding_subtotal or _("Untaxed Amount")
            sequence = tax_group.sequence

            subtotal_order[subtotal_title] = min(subtotal_order.get(subtotal_title, float('inf')), sequence)
            groups_by_subtotal[subtotal_title].append({
                'group_key': tax_group.id,
                'tax_group_id': tax_group.id,
                'tax_group_name': tax_group.name,
                'tax_group_amount': tax_group_vals['tax_amount'],
                'tax_group_amount_retencion': tax_group_vals['tax_amount_retencion'],
                'tax_group_base_amount': tax_group_vals['base_amount'],
                'formatted_tax_group_amount': formatLang(self.env, tax_group_vals['tax_amount'], currency_obj=currency),
                'formatted_tax_group_base_amount': formatLang(self.env, tax_group_vals['base_amount'], currency_obj=currency),
            })

        # ==== Build the final result ====

        subtotals = []
        for subtotal_title in sorted(subtotal_order.keys(), key=lambda k: subtotal_order[k]):
            amount_total = amount_untaxed + amount_tax - amount_tax_retencion
            subtotals.append({
                'name': subtotal_title,
                'amount': amount_total,
                'formatted_amount': formatLang(self.env, amount_total, currency_obj=currency),
            })
            amount_tax += sum(x['tax_group_amount'] for x in groups_by_subtotal[subtotal_title])
            amount_tax_retencion += sum(x['tax_group_amount_retencion'] for x in groups_by_subtotal[subtotal_title])

        amount_total = amount_untaxed + amount_tax - amount_tax_retencion

        display_tax_base = (len(global_tax_details['tax_details']) == 1 and tax_group_vals_list[0]['base_amount'] != amount_untaxed) \
            or len(global_tax_details['tax_details']) > 1
        return {
            'amount_untaxed': currency.round(amount_untaxed) if currency else amount_untaxed,
            'amount_total': currency.round(amount_total) if currency else amount_total,
            'formatted_amount_total': formatLang(self.env, amount_total, currency_obj=currency),
            'formatted_amount_untaxed': formatLang(self.env, amount_untaxed, currency_obj=currency),
            'formatted_amount_retencion': formatLang(self.env, amount_tax_retencion, currency_obj=currency),
            'groups_by_subtotal': groups_by_subtotal,
            'subtotals': subtotals,
            'subtotals_order': sorted(subtotal_order.keys(), key=lambda k: subtotal_order[k]),
            'display_tax_base': display_tax_base
        }

    def _compute_amount_ret(self, base_amount, price_unit, quantity=1.0, product=None, partner=None, fixed_multiplicator=1, uom_id=None):
        if self.amount_type == "percent" and self.price_include:
            neto = base_amount / (1 + self.retencion / 100)
            tax = base_amount - neto
            return tax
        if (self.amount_type == "percent" and not self.price_include) or (
            self.amount_type == "division" and self.price_include
        ):
            return base_amount * self.retencion / 100

    def _list_from_diario(self, day, year, month, i=1):
        if i == 4:
            return {}
        date = datetime.strptime("{}-{}-{}".format(day, month, year), "%d-%m-%Y").astimezone(pytz.UTC)
        t = date - relativedelta.relativedelta(days=i)
        t_date = "date={}-{}-{}".format(t.strftime("%d"), t.strftime("%m"), t.strftime("%Y"))
        url = "https://www.diariooficial.interior.gob.cl/edicionelectronica/"
        data = _cache_list_page.get(t_date)
        if not data:
            resp = pool.request("GET", "{}select_edition.php?{}".format(url, t_date))
            data = _cache_list_page[t_date] = resp.data.decode("utf-8")
        target = 'a href="index.php[?]%s&edition=([0-9]*)&v=1"' % t_date
        url2 = re.findall(target, data)
        if not url2:
            return self._list_from_diario(day, year, month, (i+1))
        data2 = _cache_page_2.get(url2[0])
        if not data2:
            resp2 = pool.request("GET", "{}index.php?{}&edition={}".format(url, t_date, url2[0]))
            data2 = _cache_page_2[url2[0]] = resp2.data.decode("utf-8")
        # target = 'Determina el componente variable para el cálculo del impuesto específico establecido en la ley N° 18.502 [a-zA-Z \r\n</>="_0-9]* href="([a-zA-Z 0-9/.:]*)"'
        target = '18.502[\\W]* [a-zA-Z \r\n<\\/>="_0-9]* href="([a-zA-Z 0-9\\/.:]*)"'
        url3 = re.findall(target, data2)
        if not url3:
            _logger.warning("iter "+str(i))
            return self._list_from_diario(day, year, month, (i+1))
        return {date: url3[0].replace("http:", "https:")}

    def _get_from_diario(self, url):
        self._verificar_dependencias_python()
        data = _cache_page.get(url)
        if not data:
            resp = pool.request("GET", url)
            data = _cache_page[url] = resp.data
        doc = fitz.open(stream=data, filetype="pdf")
        imagenes = doc.load_page(1).get_images()
        if len(imagenes) > 2:
            imagen = imagenes[2]
            # Extrae la imagen y conviértela a texto utilizando pytesseract
            pix = fitz.Pixmap(doc, imagen[0])
            imagen_bytes = pix.tobytes("png")
            # Convierte la imagen a otro formato compatible con pytesseract
            imagen_pil = Image.open(BytesIO(imagen_bytes))
            imagen_pil = imagen_pil.convert('RGB')
            imagen_bytesio = BytesIO()
            imagen_pil.save(imagen_bytesio, format='PNG')
            imagen_bytes = imagen_bytesio.getvalue()

            # Extrae el texto de la imagen usando pytesseract
            texto = pytesseract.image_to_string(Image.open(BytesIO(imagen_bytes)))
            i = 0
            target_i = 0
            if self.mepco == "gasolina_97":
                target_i = 1
            elif self.mepco == "diesel":
                target_i = 2
            elif self.mepco == "gas_licuado":
                target_i = 3
            elif self.mepco == "gas_natural":
                target_i = 4
            val = False
            for l in texto.splitlines():
                if not l or l.isspace():
                    continue
                val = l.split(' ')[-1]
                try:
                    val = val.replace(',', '.')
                    float(val)
                    if i == target_i:
                        return val
                    i += 1
                except:
                    val = False
        else:
            target = "Gasolina Automotriz de[\n ]93 octanos[\n ]\\(*en UTM\\/m[\\w]\\)"
            if self.mepco == "gasolina_97":
                target = "Gasolina Automotriz de[\n ]97 octanos[\n ]\\(en UTM\\/m[\\w]\\)"
            elif self.mepco == "diesel":
                target = "Petr[\\w]leo [dD]i[\\w]sel[\n ]\\(en UTM\\/m[\\w]\\)"
            elif self.mepco == "gas_licuado":
                target = "Gas Licuado del Petróleo de Consumo[\n ]Vehicular[\n ]\\(en UTM\\/m[\\w]\\)"
            elif self.mepco == "gas_natural":
                target = "Gas Natural Comprimido de Consumo Vehicular"
            val = re.findall("%s\n[0-9.,-]*\n[0-9.,-]*\n([0-9.,-]*)" % target, doc.loadPage(1).getText())
        return val[0].replace(".", "").replace(",", ".")

    def _connect_sii(self, year, month):
        month = meses[int(month)].lower()
        url = "https://www.sii.cl/valores_y_fechas/mepco/mepco%s.htm" % year
        resp = pool.request("GET", url)
        sii = html.fromstring(resp.data)
        return sii.findall('.//div[@id="pp_%s"]/div/table' % (month))

    def _list_from_sii(self, year, month):
        tables = self._connect_sii(year, month)
        rangos = {}
        i = 0
        for r in tables:
            sub = r.find("tr/th")
            res = re.search(r"\d{1,2}\-\d{1,2}\-\d{4}", sub.text.lower())
            rangos[datetime.strptime(res[0], "%d-%m-%Y").astimezone(pytz.UTC)] = i
            i += 1
        return rangos

    def _get_from_sii(self, year, month, target):
        tables = self._connect_sii(year, month)
        line = 1
        if self.mepco == "gasolina_97":
            line = 3
        elif self.mepco == "diesel":
            line = 5
        val = tables[target].findall("tr")[line].findall("td")[4].text.replace(".", "").replace(",", ".")
        return val

    def prepare_mepco(self, date, currency_id=False):
        tz = pytz.timezone("America/Santiago")
        year = date.strftime("%Y")
        month = date.strftime("%m")
        day = date.strftime("%d")
        try:
            if self.mepco_origen in ['diario', 'pdf']:
                rangos = self._list_from_diario(day, year, month)
            elif self.mepco_origen == 'sii':
                rangos = self._list_from_sii(year, month)
        except Exception as e:
            _logger.warning("Error obteniendo mepco: ", exc_info=True)
            return {'found': self._target_mepco((date - relativedelta.relativedelta(days=1)), currency_id)}
        ant = datetime.now(tz)
        target = (ant, 0)
        for k, v in rangos.items():
            if k <= date < ant:
                target = (k, v)
                break
            ant = k
        if not rangos or target[0] > date:
            return {'found': self._target_mepco((date - relativedelta.relativedelta(days=1)), currency_id)}
        if self.mepco_origen in ['diario', 'pdf']:
            val = self._get_from_diario(target[1])
        elif self.origen == 'sii':
            val = self._get_from_sii(year, month, target[1])
        utm = self.env["res.currency"].sudo().search([("name", "=", "UTM")])
        amount = utm._convert(float(val), currency_id, self.company_id, date)
        return {
            "amount": amount,
            "date": target[0].strftime("%Y-%m-%d"),
            "name": target[0].strftime("%Y-%m-%d"),
            "type": self.mepco,
            "sequence": len(rangos),
            "company_id": self.company_id.id,
            "currency_id": currency_id.id,
            "factor": float(val),
        }

    def actualizar_mepco(self):
        self.verify_mepco(date_target=False, currency_id=False, force=True)

    def _target_mepco(self, date_target=False, currency_id=False, force=False):
        if not currency_id:
            currency_id = self.env["res.currency"].sudo().search([("name", "=", self.env.get("currency", "CLP"))])
        tz = pytz.timezone("America/Santiago")
        if date_target:
            user_zone = pytz.timezone(self._context.get("tz") or "UTC")
            date = date_target
            if not hasattr(date, "tzinfo"):
                date = datetime.combine(date, time.min)
            if tz != user_zone:
                date = date.astimezone(tz)
        else:
            date = datetime.now(tz)
        query = [
            ("date", "<=", date.strftime("%Y-%m-%d")),
            ("company_id", "=", self.company_id.id),
            ("type", "=", self.mepco),
        ]
        mepco = self.env["account.tax.mepco"].sudo().search(query, limit=1)
        if mepco:
            diff = date.date() - mepco.date
            if diff.days > 6:
                mepco = False
        if not mepco:
            mepco_data = self.prepare_mepco(date, currency_id)
            query = [
                ("date", "=", mepco_data["date"]),
                ("company_id", "=", mepco_data["company_id"]),
                ("type", "=", mepco_data["type"]),
            ]
            mepco = self.env["account.tax.mepco"].sudo().search(query, limit=1)
            if not mepco:
                mepco = self.env["account.tax.mepco"].sudo().create(mepco_data)
        elif force:
            mepco_data = self.prepare_mepco(date, currency_id)
            mepco.sudo().write(mepco_data)
        return mepco

    def verify_mepco(self, date_target=False, currency_id=False, force=False):
        mepco = self._target_mepco(date_target, currency_id, force)
        self.amount = mepco.amount

    def documentos_dte_admitidos(self):
        facturas = [30, 33]
        boleta = [35, 39]
        exportacion = [110]
        factura_compra = [45, 46]
        liquidacion = [43]
        factura_exenta = [32, 34]
        boleta_exenta = [38, 41]
        if self.es_adicional() or self.es_especifico() or self.sii_code in [14, 17, 18, 19, 23, 44, 45, 46, 50, 52, 53]:
            return facturas + boleta + liquidacion
        if self.sii_code in [15, 30, 31, 32, 33, 34, 36, 37, 38, 39, 41, 47, 48, 49]:
            return factura_compra
        return exportacion + factura_exenta + boleta_exenta + facturas + boleta + liquidacion
