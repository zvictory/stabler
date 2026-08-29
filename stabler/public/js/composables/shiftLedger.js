// "How is the shift going, and what needs me next?"
//
// The Work Order register answers what the orders are. Design 1a's header strip
// answers the question a supervisor actually walks up to the screen with, and it
// is the half that never got built: planned against produced, what is waiting on
// the store, and what has run out of time.
//
// Derived from the rows the table is showing rather than from a second query.
// A header computed over a wider set can disagree with the list beneath it, and
// a strip that says "2 short" above three orange chips is worse than no strip.
// The trade is real and deliberate: the numbers describe what is on screen, so a
// filter narrows them, and the caller is expected to say so where that matters.
//
// Nothing here splits by shift. Measured 2026-08-29: `Смена A/B/C` in the design
// has no backing field on Work Order and the factory runs one shift, so a shift
// axis would be a control with nothing behind it.

import { materialReadiness } from "./materialReadiness.js";

// Work that nobody is going to do. Its quantity is not part of the plan and its
// material lines are not a shortage anybody has to solve.
const ABANDONED = new Set(["Cancelled"]);

// Finished, or deliberately halted. Past its window is history, not a task.
const SETTLED = new Set(["Completed", "Closed", "Stopped", "Cancelled"]);

// Submitted and not begun. `Draft` is excluded on purpose: it has to be
// submitted before anything can be put on a machine, so listing it under
// "ready to start" sends a supervisor to an order that cannot be started.
const AWAITING_START = "Not Started";

/**
 * Frappe writes datetimes as `YYYY-MM-DD HH:MM:SS`. `new Date()` on that exact
 * shape is not specified and has differed historically between engines, so the space
 * is normalised to `T` and read as local time — the same clock the planner typed
 * it in. An unparseable or missing value is null, never epoch zero: a draft with
 * no window is incomplete, not fifty years late.
 */
function readDate(value) {
	if (!value) return null;
	const d = new Date(String(value).replace(" ", "T"));
	return Number.isNaN(d.getTime()) ? null : d;
}

const isAbandoned = (row) => ABANDONED.has(row?.status);

/** Open work whose planned window has already closed. */
export function isOverdue(row, now) {
	if (SETTLED.has(row?.status)) return false;
	const end = readDate(row?.planned_end_date);
	return !!end && end.getTime() < now.getTime();
}

/** Submitted, not begun, and the materials are there. */
export function isReadyToStart(row, stock) {
	if (row?.status !== AWAITING_START) return false;
	const state = materialReadiness(row, stock).state;
	// `in_place` counts: nothing is left to issue, which is the readiest an
	// order gets. Treating it as a separate, lesser state was the first version
	// of this rule and it hid exactly the orders that could run immediately.
	return state === "ready" || state === "in_place";
}

/**
 * @param {Array} rows `list_work_orders` rows, as the table is showing them
 * @param {Record<string, number>} stock `stockKey()` → quantity on hand
 * @param {Date} now
 * @returns {{orders, planQty, producedQty, donePct, ready, overdue, shortOrders, shortItems, unknown}}
 *          `donePct` is null when there is no plan to divide by — `0` would read
 *          as "nothing done" on a register where nothing was planned.
 */
export function shiftSummary(rows, stock, now) {
	const all = Array.isArray(rows) ? rows : [];
	const live = all.filter((r) => !isAbandoned(r));

	let planQty = 0;
	let producedQty = 0;
	let ready = 0;
	let overdue = 0;
	let shortOrders = 0;
	let shortItems = 0;
	let unknown = 0;

	for (const row of live) {
		planQty += Number(row?.qty) || 0;
		producedQty += Number(row?.produced_qty) || 0;
		if (isOverdue(row, now)) overdue += 1;
		if (isReadyToStart(row, stock)) ready += 1;

		const { state, shortCount } = materialReadiness(row, stock);
		if (state === "short") {
			shortOrders += 1;
			shortItems += shortCount;
		} else if (state === "unknown") {
			unknown += 1;
		}
	}

	return {
		orders: all.length,
		planQty,
		producedQty,
		// Never capped at 100: ERPNext allows finishing over the plan, and a
		// shift that ran 10% over is the thing a supervisor most wants to see.
		donePct: planQty > 0 ? Math.round((producedQty / planQty) * 100) : null,
		ready,
		overdue,
		shortOrders,
		shortItems,
		unknown,
	};
}

/**
 * The rows behind one tab. Filtered from the same list the strip counted, so a
 * tab's contents and its badge can never disagree.
 *
 * An unrecognised view returns everything. The name arrives from a route or a
 * stale bookmark, and an empty table reads as "no work today" on a shift that
 * has plenty.
 */
export function ledgerView(rows, view, stock, now) {
	const all = Array.isArray(rows) ? rows : [];
	if (view === "ready") return all.filter((r) => isReadyToStart(r, stock));
	if (view === "overdue") return all.filter((r) => isOverdue(r, now));
	return all;
}
