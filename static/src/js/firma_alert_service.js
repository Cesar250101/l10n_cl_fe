/** @odoo-module **/

import { registry } from "@web/core/registry";

export const firmaAlertService = {
    dependencies: ["notification", "rpc"],
    async start(env, { notification, rpc }) {
        const alerts = await rpc("/l10n_cl_fe/firma_alerts", {});
        if (alerts && alerts.length) {
            for (const alert of alerts) {
                notification.add(alert.message, {
                    title: alert.title,
                    sticky: true,
                    type: alert.type,
                });
            }
        }
    },
};

registry.category("services").add("firma_alert", firmaAlertService);
