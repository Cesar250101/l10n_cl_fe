/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListController } from "@web/views/list/list_controller";
import { useService } from "@web/core/utils/hooks";

export class DteDocumentListController extends ListController {
    setup() {
        super.setup();
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    async onFetchDteEmails() {
        const stats = await this.orm.call("mail.message.dte.document", "fetch_dte_supabase", []);
        await this.model.load();
        this.model.notify();
        const hasErrors = stats && stats.errors;
        this.notification.add(
            hasErrors
                ? `Supabase: ${stats.imported || 0} importados, ${stats.errors} con error.`
                : `Supabase: ${stats.imported || 0} XML importados.`,
            { type: hasErrors ? "warning" : "success" }
        );
    }
}

registry.category("views").add("dte_document_list", {
    ...listView,
    Controller: DteDocumentListController,
    buttonTemplate: "l10n_cl_fe.DteDocumentListView.Buttons",
});
