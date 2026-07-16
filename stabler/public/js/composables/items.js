import { call } from "../api/client.js";

/**
 * Central item-search factory for every line-item picker.
 *
 * ONE place decides which item-type flag the backend filters by, via `context`:
 *   - "sales"    → is_sales_item   (Sales Order / Sales Invoice)
 *   - "purchase" → is_purchase_item (Purchase Order / Purchase Invoice)
 *   - "stock"    → is_stock_item    (Stock Entry / Transfer / Stock Ledger)
 *   - "all"      → no type filter
 *
 * This is the fix for pickers disagreeing about which items exist: a purchase
 * picker showing nothing for a purchase-only item, a transfer picker missing raw
 * materials, etc. Every form calls this instead of hand-rolling its own
 * list_items call.
 *
 * `warehouse` may be a value OR a getter (`() => form.value.set_warehouse`) so a
 * reactive warehouse is resolved at call time, not frozen when the searcher is built.
 *
 * @param {"sales"|"purchase"|"stock"|"all"} context
 * @param {{ warehouse?: string|(() => string), limit?: number, itemGroup?: string }} [opts]
 * @returns {(q: string) => Promise<Array>}
 */
export function itemSearcher(context, opts = {}) {
	const resolveWarehouse = typeof opts.warehouse === "function" ? opts.warehouse : () => opts.warehouse;
	return (q) =>
		call("stabler.api.inventory.list_items", {
			search: q,
			context,
			warehouse: resolveWarehouse() || undefined,
			item_group: opts.itemGroup || undefined,
			limit: opts.limit || 30,
		});
}
