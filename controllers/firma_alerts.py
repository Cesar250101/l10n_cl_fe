import dateutil.relativedelta as relativedelta

from odoo import SUPERUSER_ID, fields
from odoo.http import Controller, request, route


class FirmaAlertController(Controller):

    @route('/l10n_cl_fe/firma_alerts', type='json', auth='user')
    def get_firma_alerts(self):
        user = request.env.user
        user_id = user.id
        if user_id == SUPERUSER_ID:
            user_id = request.env.ref("base.user_admin").id

        today = fields.Date.today()
        warning_date = today + relativedelta.relativedelta(days=30)

        firmas = request.env['sii.firma'].sudo().with_context(active_test=False).search([
            ('user_ids', 'in', [user_id]),
            ('expire_date', '!=', False),
            ('expire_date', '<=', warning_date),
            ('state', 'not in', ['incomplete', 'unverified']),
        ])

        alerts = []
        for firma in firmas:
            is_expired = firma.expire_date < today
            if is_expired:
                alerts.append({
                    'title': '⚠️ Certificado Digital VENCIDO',
                    'message': "El certificado '%s' (RUT: %s) venció el %s. "
                               "Por favor, suba un nuevo certificado para continuar emitiendo DTEs."
                               % (firma.name, firma.subject_serial_number or '', firma.expire_date),
                    'type': 'danger',
                })
            else:
                days_left = (firma.expire_date - today).days
                alerts.append({
                    'title': '🔔 Certificado Digital próximo a vencer',
                    'message': "El certificado '%s' (RUT: %s) vencerá en %d día(s) el %s. "
                               "Le recomendamos renovarlo a la brevedad."
                               % (firma.name, firma.subject_serial_number or '', days_left, firma.expire_date),
                    'type': 'warning',
                })
        return alerts
