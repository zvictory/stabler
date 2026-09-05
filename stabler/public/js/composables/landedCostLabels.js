import { t } from "./i18n.js";

/**
 * Labels for the landed-cost review's distribution basis and received-quantity
 * card, extracted out of LandedCostReview.vue so both can be unit-tested
 * without mounting the page.
 *
 * H.3 (docs/backlog.md walk, 2026-09-05): both labels used to hardcode "(kg)"
 * regardless of what the receipt actually carried. That was only ever true for
 * the GRN-Checklist/imports route, which pins stock UOM to Kg by construction
 * (receipt_math.STOCK_UOM). A plain Purchase Receipt landed-cost review
 * (document_type="Purchase Receipt", api/lcv.py) has no such guarantee and can
 * receive in any UOM.
 */

/**
 * "Qty" / "Amount" are ERPNext's raw `distribute_charges_based_on` field
 * values and are sent back untouched; only the label an accountant reads is
 * translated. ERPNext's Landed Cost Voucher distributes "Qty" purely
 * proportional to the raw qty field on each line
 * (landed_cost_voucher.py:set_applicable_charges_on_item,
 * based_on_field = frappe.scrub(self.distribute_charges_based_on)) -- it is
 * never weight-specific, so the label must not claim a unit. "By quantity"
 * already exists as this exact concept elsewhere in the app
 * (CommercialInvoiceForm.vue's own "By Quantity" distribution option).
 */
export function distributionLabel(method) {
	if (method === "Qty") return t("By quantity");
	if (method === "Amount") return t("By line value");
	return method;
}

/** "Received (Kg)" / "Received (Nos)" -- the unit is data, never assumed. */
export function receivedLabel(uom) {
	return t("Received ({0})", [uom || ""]);
}
