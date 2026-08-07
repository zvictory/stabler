// The double cap behind Smart Fill's step 2. A compensated PI line is booked as
// one category but shipped as its individual cuts, so the picker offers the
// cuts while the server guard still enforces the category total. Two ceilings
// therefore apply at once:
//
//   1. a line may not take more than its own contracted boxes, and
//   2. the lines of one category may not take more than that category's
//      remaining pool — which is the only number the backend checks.
//
// Nothing here knows about proformas, categories or match keys: callers pass an
// opaque `groupKey` / `rowKey`. Keeping the key format out of this module is
// what stops a second, item-level match key from growing here by accident.

function toBoxes(value) {
	const n = Number(value);
	return Number.isFinite(n) && n > 0 ? n : 0;
}

// Walks one group's rows in contract order, handing each what is left of the
// pool after the rows above it. Order matters and is the PI's own line order —
// the same order the user reads on the screen, so the cut that gets truncated
// is the one at the bottom of the list, not an arbitrary one.
function walk(group, stopAtRowKey) {
	const pool = toBoxes(group?.pool);
	const byRow = {};
	let taken = 0;
	for (const row of group?.rows || []) {
		if (stopAtRowKey !== undefined && row.rowKey === stopAtRowKey) break;
		// An unpicked row is not going to be pushed, so it must not reserve
		// boxes the rows below it could still use.
		const wanted = row.picked === false ? 0 : toBoxes(row.requested);
		const boxes = Math.min(wanted, toBoxes(row.ownRemaining), pool - taken);
		byRow[row.rowKey] = boxes > 0 ? boxes : 0;
		taken += byRow[row.rowKey];
	}
	return { pool, byRow, taken };
}

/**
 * Resolve every group's requested boxes into what may actually be allocated.
 *
 * `groups` is `[{ groupKey, pool, rows: [{ rowKey, ownRemaining, requested, picked }] }]`.
 * Returns `{ byRow: {rowKey: boxes}, byGroup: {groupKey: {pool, allocated}} }`.
 * By construction `Σ byRow(group) === byGroup.allocated <= pool`.
 *
 * Pure: the input is never mutated, so the group header, the summary bar and
 * the Apply loop can all read the same plan and cannot disagree.
 */
export function buildAllocationPlan(groups = []) {
	const byRow = {};
	const byGroup = {};
	for (const group of groups) {
		const { pool, byRow: rows, taken } = walk(group);
		Object.assign(byRow, rows);
		byGroup[group.groupKey] = { pool, allocated: taken };
	}
	return { byRow, byGroup };
}

/**
 * The `<input max>` for one row: its own contract, capped by what the rows
 * above it have left in the pool. The row itself is excluded from that sum —
 * otherwise a line sitting at its maximum would report a ceiling of 0 and could
 * never be retyped.
 */
export function rowCeiling(group, rowKey) {
	const target = (group?.rows || []).find((r) => r.rowKey === rowKey);
	if (!target) return 0;
	const { pool, taken } = walk(group, rowKey);
	return Math.max(0, Math.min(toBoxes(target.ownRemaining), pool - taken));
}
