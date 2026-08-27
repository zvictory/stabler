// "Can this order be started, and how far will the store carry it?"
//
// The list already answers what was planned and what was produced. It could not
// answer the question a shift supervisor actually opens it with — which of these
// twenty orders can I put on a machine right now — because that answer lives in
// two places the screen never joined: what each order still needs, and what is
// on the shelf it draws from.
//
// Both halves are already on the page. `list_work_orders` returns `required_items`
// per row from one bulk query, and the warehouse stock is one call per source
// warehouse. So this is arithmetic, not a new endpoint.

/** Stock is keyed by warehouse AND item — the same item lives on several shelves. */
export const stockKey = (warehouse, itemCode) => `${warehouse || ""}::${itemCode || ""}`;

/**
 * @param {{qty: number, required_items: Array}} row a `list_work_orders` row
 * @param {Record<string, number>} stock `stockKey()` → quantity on hand
 * @returns {{state: string, shortCount: number, unitsCovered: ?number}}
 *          `state` is `in_place` (nothing left to issue), `ready`, `short`, or
 *          `unknown`. `unitsCovered` is how many more finished units the store
 *          can support, or null when the order carries no quantity to divide by.
 */
export function materialReadiness(row, stock) {
	const lines = row?.required_items || [];
	if (!lines.length) return { state: "unknown", shortCount: 0, unitsCovered: null };

	const total = Number(row?.qty) || 0;
	const outstanding = lines.filter(
		(l) => (Number(l.required_qty) || 0) - (Number(l.transferred_qty) || 0) > 0,
	);

	// Everything this order needs is already in WIP. It is not competing for
	// shelf stock at all, and a red chip here would sit on the one order that is
	// genuinely ready to run.
	if (!outstanding.length) return { state: "in_place", shortCount: 0, unitsCovered: null };

	let shortCount = 0;
	let unitsCovered = null;
	for (const line of outstanding) {
		const key = stockKey(line.source_warehouse, line.item_code);
		// Never guess. A chip that claims availability nobody measured sends a
		// supervisor to a store that cannot fill the order — worse than silence.
		if (!(key in stock)) return { state: "unknown", shortCount: 0, unitsCovered: null };

		const available = Number(stock[key]) || 0;
		const stillNeeded = (Number(line.required_qty) || 0) - (Number(line.transferred_qty) || 0);
		if (available < stillNeeded) shortCount += 1;

		const perUnit = total > 0 ? (Number(line.required_qty) || 0) / total : 0;
		if (perUnit > 0) {
			// One missing ingredient stops the line, so the answer is the
			// minimum across materials — never an average, never the most
			// plentiful one.
			const covered = Math.floor(available / perUnit);
			unitsCovered = unitsCovered === null ? covered : Math.min(unitsCovered, covered);
		}
	}

	return { state: shortCount ? "short" : "ready", shortCount, unitsCovered };
}
