// One reader for "what is on the shelves for these orders".
//
// Extracted from `WorkOrders.vue` when the planning screen needed the same map
// for design 1c's «ЧТО МЕШАЕТ ЗАПУСКУ» panel. Two copies of this would drift
// exactly where it hurts most: the per-warehouse `catch` below is the reason a
// store that will not answer reports `unknown` instead of `0`, and a second
// copy written without it would quietly print "nothing is blocking" over
// materials nobody measured.

import { call } from "../api/client.js";
import { stockKey } from "./materialReadiness.js";

/**
 * @param rows `list_work_orders` rows, each with `required_items`
 * @returns {Promise<Record<string, number>>} `stockKey()` → quantity on hand.
 *          A warehouse whose call failed is simply absent from the map, and
 *          every consumer treats an absent key as "not measured" rather than as
 *          zero. Failing the whole map over one store would hide the rows that
 *          are fine.
 */
export async function loadStockLevels(rows) {
	const byWarehouse = new Map();
	for (const row of rows || []) {
		for (const line of row.required_items || []) {
			if (!line.source_warehouse || !line.item_code) continue;
			if (!byWarehouse.has(line.source_warehouse)) byWarehouse.set(line.source_warehouse, new Set());
			byWarehouse.get(line.source_warehouse).add(line.item_code);
		}
	}
	const next = {};
	await Promise.all(
		[...byWarehouse].map(async ([warehouse, codes]) => {
			try {
				const levels = await call("stabler.api.inventory.get_items_stock", {
					warehouse,
					item_codes: JSON.stringify([...codes]),
				});
				for (const [item, qty] of Object.entries(levels || {})) {
					next[stockKey(warehouse, item)] = qty;
				}
			} catch {
				// Deliberately swallowed per warehouse — see the note above.
			}
		}),
	);
	return next;
}
