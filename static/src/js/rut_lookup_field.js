/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { CharField } from "@web/views/fields/char/char_field";

import { Component, xml } from "@odoo/owl";

/**
 * Campo «Document number» del contacto. Si se ingresa en un contacto NUEVO un RUT que ya
 * pertenece a otro contacto de la compañía, en vez de avisar que está usado se abre ese
 * contacto en el formulario para que el usuario lo edite o simplemente lo guarde.
 * En diálogos o en contactos ya guardados se mantiene el comportamiento normal (onchange).
 */
export class RutLookupField extends Component {
    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
    }

    get charProps() {
        return { ...this.props, update: this.update.bind(this) };
    }

    async update(value) {
        const record = this.props.record;
        if (value && !record.resId && !this.env.inDialog) {
            const tipo = record.data.document_type_id;
            const tipoId = Array.isArray(tipo) ? tipo[0] : tipo;
            let partnerId = false;
            try {
                partnerId = await this.orm.call("res.partner", "find_partner_by_rut", [
                    value,
                    tipoId || false,
                ]);
            } catch (_e) {
                partnerId = false; // si falla la búsqueda, seguir el flujo normal
            }
            if (partnerId) {
                return this.action.doAction(
                    {
                        type: "ir.actions.act_window",
                        res_model: "res.partner",
                        res_id: partnerId,
                        views: [[false, "form"]],
                        target: "current",
                    }
                );
            }
        }
        return this.props.update(value);
    }
}

RutLookupField.template = xml`<CharField t-props="charProps"/>`;
RutLookupField.components = { CharField };
RutLookupField.props = CharField.props;
RutLookupField.displayName = CharField.displayName;
RutLookupField.supportedTypes = CharField.supportedTypes;
RutLookupField.extractProps = CharField.extractProps;

registry.category("fields").add("rut_lookup", RutLookupField);
