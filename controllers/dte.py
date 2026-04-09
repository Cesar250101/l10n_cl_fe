# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import json



class Dte(http.Controller):

    @http.route('/l10n_cl_fe/dte', methods=['POST'], auth='public', csrf=False)
    def process_dte(self, data=None, **kw):
        try:
            data = json.loads(request.httprequest.data)
        except json.JSONDecodeError:
            return {'error': 'JSON inválido'}

        if data:
            def _find_documento(node):
                if isinstance(node, dict):
                    if 'Documento' in node:
                        return node['Documento']
                    for value in node.values():
                        result = _find_documento(value)
                        if result is not None:
                            return result
                elif isinstance(node, list):
                    for item in node:
                        result = _find_documento(item)
                        if result is not None:
                            return result
                return None

            documento_payload = _find_documento(data)
            encabezado = documento_payload.get('Encabezado', {})
            detalle = documento_payload.get('Detalle', [])
            descuentos = documento_payload.get('DscRcgGlobal', {})
            referencias = documento_payload.get('Referencia', [])   
            totales = encabezado.get('Totales', {})
            emisor = encabezado.get('Emisor', {})
            receptor = encabezado.get('Receptor', {})
            IdDoc = encabezado.get('IdDoc', {})

            self._proc_document(IdDoc, emisor, receptor, totales, detalle, descuentos, referencias)


        return {'error': 'No se proporcionaron datos de DTE'}   
    
    def format_rut(self, RUTEmisor=None):
        if RUTEmisor is None:
            return False
        rut = RUTEmisor.replace("-", "")
        rut = "CL" + rut
        return rut

    def _find_company_from_vat(self, vat_number):
        vat_number_formatted = self.format_rut(vat_number)
        company_id = request.env["res.company"].sudo().search([("vat", "=", vat_number_formatted)], limit=1)
        # company_id = request.env["res.company"].sudo().search([])
        if not company_id:
            company_id = request.env["res.company"].sudo().search([("vat", "=", vat_number)], limit=1)
        if not company_id:
            company_id = request.env["res.company"].sudo().search(
                [("document_number", "=", vat_number)], limit=1
            )
        return company_id if company_id else False
    
    def _find_giro_by_name(self, name):
        giro_id = request.env["sii.activity.description"].search([("name", "=", name)])
        if not giro_id:
            giro_id = request.env["sii.activity.description"].create({
                "name": name
            })
        return giro_id
    
    def _find_acteco_by_code(self, code):
        acteco_id = request.env["partner.activities"].search([("code", "=", code)])
        if not acteco_id:
            acteco_id = request.env["partner.activities"].create({
                "code": code,
                "name": f"Actividad {code}"
            })  
        return acteco_id if acteco_id else False

    def _find_comuna_by_name(self, name):
        comuna_id = request.env["res.city"].search([("name", "=", name)], limit=1)
        return comuna_id if comuna_id else False

    def _find_partner_by_vat(self, vat_number,emisor=False, company_id=False):
        partner_id = request.env["res.partner"].search([("parent_id", "=", False),
                                                     ("company_id", "=", company_id.id if company_id else False),
                                                     ("vat", "=", self.format_rut(vat_number))])
        if not partner_id:
            partner_id = request.env["res.partner"].sudo().create({
                "name": emisor.get('RznSoc', 'Unknown Partner') ,
                "vat": self.format_rut(vat_number),
                "document_number": emisor.get('RUTEmisor', ''),
                "activity_description": self._find_giro_by_name(emisor.get('GiroEmis', '')).id if emisor.get('GiroEmis') else False,
                "acteco_ids": [(4, self._find_acteco_by_code(emisor.get('Acteco', '')).id)] if emisor.get('Acteco') else False,
                "street": emisor.get('DirOrigen', ''),
                "city_id": self._find_comuna_by_name(emisor.get('CmnaOrigen', '')).id if emisor.get('CmnaOrigen') else False,
                "company_id": company_id.id if company_id else False,
            })
        return partner_id
    
    def _proc_document(self, IdDoc, emisor, receptor, totales, detalle, descuentos, referencias):
        model_account_move = request.env['account.move'].sudo()
        model_account_move_line = request.env['account.move.line'].sudo()
        model_product_product = request.env['product.product'].sudo()
        model_product_template = request.env['product.template'].sudo()
        model_sii_document_class= request.env['sii.document_class'].sudo()
        model_mail_message_dte_document = request.env['mail.message.dte.document'].sudo()
        model_mail_message_dte_document_line = request.env['mail.message.dte.document.line'].sudo()
        model_mail_message_dte=document_tax = request.env['mail.message.dte'].sudo()
        
        
        company_id = self._find_company_from_vat(receptor.get('RUTRecep'))
        if not company_id:
            return      
        partner_emisor_id = self._find_partner_by_vat(emisor.get('RUTEmisor'),emisor, company_id=company_id)

        document_class = model_sii_document_class.search([('sii_code', '=', IdDoc.get('TipoDTE'))], limit=1)
        if not document_class:
            return  
        # Determinar el tipo de movimiento basado en el código SII del documento
        sii_code = int(IdDoc.get('TipoDTE'))
        if sii_code in [33, 34]:  # Factura electrónica, Factura exenta
            move_type = 'in_invoice'
        elif sii_code in [56, 61]:  # Nota de débito
            move_type = 'in_invoice'
        elif sii_code in [60, 61]:  # Nota de crédito
            move_type = 'in_refund'
        else:
            move_type = 'in_invoice'  # Por defecto
        
        move_vals = {
            'move_type': move_type,
            'document_class_id': document_class.id,
            'company_id': company_id.id,
            'partner_id': partner_emisor_id.id,
            'sii_document_number': IdDoc.get('Folio'),
            'sii_document_date': IdDoc.get('FchEmis'),
        }
        account_move = model_mail_message_dte_document.create(move_vals) 
        for item in detalle:
            product_code = item.get('CdgItem', {}).get('VlrCodigo', 'DTE_Product')
            product = model_product_product.search([('default_code', '=', product_code), ('company_id', '=', company_id.id)], limit=1)
            if not product:
                product_template = model_product_template.create({
                    'name': item.get('NmbItem', 'DTE Product'),
                    'default_code': product_code,
                    'type': 'service',
                    'company_id': company_id.id,
                })
                product = model_product_product.create({
                    'product_tmpl_id': product_template.id,
                    'company_id': company_id.id,
                })
            line_vals = {
                'move_id': account_move.id,
                'product_id': product.id,
                'quantity': item.get('QtyItem', 1),
                'price_unit': item.get('PrcItem', 0.0),
                'name': item.get('NmbItem', ''),
            }
            model_account_move_line.create(line_vals)
        account_move._compute_tax_totals()
        account_move.action_post()  