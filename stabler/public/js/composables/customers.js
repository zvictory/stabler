import { call } from "../api/client.js";

/**
 * Central customer-search factory for every customer picker.
 *
 * Counterpart of `itemSearcher` in `items.js`, and it exists for the same reason:
 * one place decides which endpoint a typeahead talks to. `list_customers` returns
 * a bare array; the list-page endpoint `list_customers_with_balances` returns a
 * `{rows, totals, …}` envelope. Typeahead.vue turns anything that is not an array
 * into `[]` without a word, so a picker pointed at the wrong endpoint stays empty
 * forever and looks like a data or permission problem. The array guard below makes
 * that failure impossible rather than merely unlikely.
 *
 * `company` may be a value OR a getter (`() => activeCompany.value`) so the active
 * company is resolved at call time, not frozen when the searcher is built.
 *
 * @param {string|(() => string)} company
 * @param {{ limit?: number }} [opts]
 * @returns {(q: string) => Promise<Array>}
 */
export function customerSearcher(company, opts = {}) {
	const resolveCompany = typeof company === "function" ? company : () => company;
	return async (q) => {
		try {
			const rows = await call("stabler.api.sales.list_customers", {
				company: resolveCompany(),
				search: q || "",
				limit: opts.limit || 15,
			});
			return Array.isArray(rows) ? rows : [];
		} catch {
			return [];
		}
	};
}
