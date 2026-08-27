// One column's worth of answers about a work order's progress.
//
// The list used to carry three numeric columns — Plan, Transferred, Produced —
// and left the reader to do the arithmetic. "18 416 / 4 000 / 2 640" is three
// figures in a row that only mean something once you divide, and a shift
// supervisor scanning twenty rows for the one that has stalled is doing twenty
// divisions in their head.
//
// Two of the three collapse naturally into "2 640 / 4 000". The third does not,
// because it answers a different question: not how far along the order is, but
// whether it can be worked at all. An order with nothing in WIP is not 0% done
// — it is not started, and nobody is standing at a machine waiting. That
// distinction is why `transferredPct` and `nothingTransferred` survive the
// collapse instead of being folded into the percentage.

/**
 * @param {{qty: number, produced_qty: number, transferred_qty: number}} row a
 *        `list_work_orders` row
 * @returns {{donePct: number, barPct: number, transferredPct: number, nothingTransferred: boolean}}
 *          `donePct` is the true figure and may exceed 100 — ERPNext permits
 *          over-production and the deviation panel exists because it happens.
 *          `barPct` is the same number clamped for rendering, because a bar
 *          wider than its track is a rendering bug, not information.
 */
export function workOrderProgress(row) {
	const total = Number(row?.qty) || 0;
	const done = Number(row?.produced_qty) || 0;
	const moved = Number(row?.transferred_qty) || 0;

	const pct = (n) => (total > 0 ? Math.round((n / total) * 100) : 0);
	const donePct = pct(done);

	return {
		donePct,
		barPct: Math.min(100, Math.max(0, donePct)),
		transferredPct: pct(moved),
		nothingTransferred: moved <= 0,
	};
}
