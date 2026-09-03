/**
 * The landed-charge type list, read from the server (ADR-606).
 *
 * There is ONE list and it is defined in `api/_landed_charge_types.py`. Until
 * 2026-09-03 there were two, hard-coded in the two editors that write landed
 * charges — `LandedChargesEditor.vue` (the Supplier Quotation estimate) and
 * `PoControlBoard.vue` (the Purchase Order plan) — and they did not overlap on a
 * single string: "Freight" there, "transport" here, for the same money at two
 * moments of the same purchase. Nothing could compare the estimate with the plan.
 *
 * So neither component may hold a list again; both call `loadChargeTypes()` and
 * render `chargeTypes`. Labels arrive in English and are translated here with
 * `t()`, so one payload serves every language.
 *
 * The fetch is cached for the session: the list is a constant, and the two
 * editors open repeatedly.
 */
import { ref } from "vue";
import { call } from "../api/client.js";
import { t } from "./i18n.js";

/** [{ key, label }] in the order both <select>s render. */
export const chargeTypes = ref([]);

let pending = null;

export async function loadChargeTypes() {
	if (chargeTypes.value.length) return chargeTypes.value;
	if (!pending) {
		// A failure must not be cached: the caller shows it (both editors load
		// this inside the same try that loads the charges themselves), and the
		// next open has to be able to try again.
		pending = call("stabler.api.tender.landed_charge_types")
			.then((r) => {
				chargeTypes.value = r?.charge_types || [];
				return chargeTypes.value;
			})
			.catch((err) => {
				pending = null;
				throw err;
			});
	}
	return pending;
}

/** The translated label for a canonical key; the key itself if it is unknown. */
export function chargeTypeLabel(key) {
	const hit = chargeTypes.value.find((c) => c.key === key);
	return hit ? t(hit.label) : String(key || "");
}
