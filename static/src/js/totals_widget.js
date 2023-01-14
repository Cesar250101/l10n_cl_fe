/** @odoo-module */
import { TaxTotalsComponent } from "@account/components/tax_totals/tax_totals";
import { patch } from '@web/core/utils/patch';


patch(TaxTotalsComponent.prototype, 'l10n_cl_fe.TaxTotalsComponent', {
    _computeTotalsFormat() {
        if (!this.totals) {
            return;
        }
        let amount_untaxed = this.totals.amount_untaxed;
        let amount_tax = 0;
        let amount_tax_retencion = 0;
        let subtotals = [];
        for (let subtotal_title of this.totals.subtotals_order) {
            let amount_total = amount_untaxed + amount_tax;
            subtotals.push({
                'name': subtotal_title,
                'amount': amount_total,
                'formatted_amount': this._format(amount_total),
            });
            let group = this.totals.groups_by_subtotal[subtotal_title];
            for (let i in group) {
                amount_tax = amount_tax + group[i].tax_group_amount;
                amount_tax_retencion  = amount_tax_retencion + group[i].tax_group_amount_retencion;
            }
        }
        this.totals.subtotals = subtotals;
        let amount_total = amount_untaxed + amount_tax - amount_tax_retencion;
        this.totals.amount_total = amount_total;
        this.totals.formatted_amount_total = this._format(amount_total);
        for (let group_name of Object.keys(this.totals.groups_by_subtotal)) {
            let group = this.totals.groups_by_subtotal[group_name];
            for (let i in group) {
                group[i].formatted_tax_group_amount = this._format(group[i].tax_group_amount);
                group[i].formatted_tax_group_base_amount = this._format(group[i].tax_group_base_amount);
            }
        }
    }
})