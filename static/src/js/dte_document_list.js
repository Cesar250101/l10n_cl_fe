/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class DteDocumentListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    async onFetchDteEmails() {
        await this.orm.call("mail.message.dte.document", "fetch_dte_supabase", []);
        await this.model.load();
        this.model.notify();
        this.notification.add(
            _t("Búsqueda en Supabase finalizada. Se procesaron los XML disponibles."),
            { type: "success" }
        );
    }
}

registry.category("views").add("dte_document_list", {
    ...listView,
    Controller: DteDocumentListController,
    buttonTemplate: "l10n_cl_fe.DteDocumentListView.Buttons",
});
