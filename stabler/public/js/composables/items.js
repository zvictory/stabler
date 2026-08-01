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
 * `warehouse` and `priceList` may each be a value OR a getter
 * (`() => form.value.set_warehouse`) so a reactive value is resolved at call time,
 * not frozen when the searcher is built.
 *
 * `priceList` is opt-in: pass it and every row also carries `price_list_rate`, so a
 * picker can quote a price without a second round trip per item. Pickers that don't
 * ask for it pay nothing.
 *
 * @param {"sales"|"purchase"|"stock"|"all"} context
 * @param {{ warehouse?: string|(() => string), priceList?: string|(() => string), limit?: number, itemGroup?: string }} [opts]
 * @returns {(q: string) => Promise<Array>}
 */
export function itemSearcher(context, opts = {}) {
	const getter = (v) => (typeof v === "function" ? v : () => v);
	const resolveWarehouse = getter(opts.warehouse);
	const resolvePriceList = getter(opts.priceList);
	return (q) =>
		call("stabler.api.inventory.list_items", {
			search: q,
			context,
			warehouse: resolveWarehouse() || undefined,
			price_list: resolvePriceList() || undefined,
			item_group: opts.itemGroup || undefined,
			limit: opts.limit || 30,
		});
}
