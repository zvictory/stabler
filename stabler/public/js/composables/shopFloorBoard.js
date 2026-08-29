// «Канбан: состояние цеха» — which column a Work Order card sits in.
//
// The columns are a DERIVED state, not ERPNext's `status` field. That
// distinction is the whole reason this board exists at all: `status` is
// read-only after submit and 99.1% of anjan's orders carry one value, which is
// what got this design recorded as dead on 2026-08-28. The design never used it
// — its columns are draft / waiting / partly issued / running / halted / done,
// and its cards carry buttons rather than drag handles.
//
// Neither material shortage nor a half-finished transfer is a column. The design
// draws both inside «Готов к запуску» — shortage as a badge ("Дефицит блокирует
// старт"), a part-issued order as a card carrying a «Частично» BUTTON and a
// «передано 50%» line. That is the right shape: both orders are still waiting to
// start, and a bin of their own takes them out of the column a supervisor is
// working down. A sixth «Частично» column shipped on 2026-08-29 and is removed
// here: it was mine rather than the design's, it held 0 rows on anjan, and it
// pushed the five real columns off a laptop screen.

/** Left to right, as the design lays them out. */
export const BOARD_COLUMNS = ["draft", "ready", "running", "paused", "done"];

const DONE = new Set(["Completed", "Closed"]);

/**
 * @param {{docstatus, status, qty, produced_qty, transferred_qty}} row
 * @returns {string|null} one of `BOARD_COLUMNS`, or null for a cancelled order —
 *          which is not a state of the shop floor and gets no bin.
 *
 * Order matters, and every branch below is a precedence decision:
 *   - `docstatus` outranks `status`, because status is derived and an
 *     unsubmitted order cannot be anywhere but draft.
 *   - `paused` outranks `running`, because an order halted mid-run has both
 *     output and a halt, and it belongs where somebody has to act on it.
 *   - `done` outranks everything below it, so a completed order that produced
 *     does not read as still running.
 * The final branch is a catch-all on purpose: ERPNext ships statuses this app
 * never enumerated (anjan carries `Stock Reserved` today), and a card matching
 * no branch would vanish from the board rather than fail loudly.
 */
export function boardColumn(row) {
	const docstatus = Number(row?.docstatus ?? 1);
	if (docstatus === 2) return null;
	if (docstatus === 0) return "draft";

	const status = row?.status || "";
	if (DONE.has(status)) return "done";
	if (status === "Stopped") return "paused";
	if (status === "In Process" || (Number(row?.produced_qty) || 0) > 0) return "running";

	// Submitted, not halted, nothing off the line yet: the order is waiting to
	// start, whether or not its material has been issued. How much HAS been
	// issued is a fact about the card, not about the column — `transferredPct`
	// answers it and the card prints it.
	return "ready";
}

/**
 * How much of an order has been issued to the floor, as a whole percent.
 *
 * @returns {number|null} null when there is nothing to say — either nothing has
 *          been issued, or the order has no quantity to take a share of.
 *          Deliberately not 0: the card renders this line only when it exists,
 *          and «передано 0%» on every waiting order is furniture.
 */
export function transferredPct(row) {
	const qty = Number(row?.qty) || 0;
	const transferred = Number(row?.transferred_qty) || 0;
	if (qty <= 0 || transferred <= 0) return null;
	// Capped, because ERPNext allows an over-issue and «передано 120%» reads as
	// a bug in the card rather than as a fact about the store.
	return Math.min(100, Math.round((transferred / qty) * 100));
}

/**
 * The one action the card offers, or null when there is nothing left to do.
 *
 * One action, not the design's two: a card is 15rem wide and a second button
 * halves both. The action below is the one that moves the order to the next
 * column; everything else stays on the order's own page, which is one click away.
 *
 * `kind` is what the page dispatches on; `label` is a translation key, so this
 * module stays free of `t()` and can be unit-tested without a locale.
 */
export function cardAction(row) {
	switch (boardColumn(row)) {
		case "draft":
			return { kind: "submit", label: "Submit" };
		case "ready":
			return { kind: "transfer", label: "Transfer and start" };
		case "running":
			return { kind: "produce", label: "Finish" };
		case "paused":
			return { kind: "resume", label: "Resume" };
		case "done":
			// `done` holds Completed AND Closed. A Close button on an order that is
			// already closed is a button whose only outcome is an error from the
			// server, so the finished half of the column offers nothing.
			return row?.status === "Closed" ? null : { kind: "close", label: "Close order" };
		default:
			return null;
	}
}

/**
 * Did this order finish inside the shift the board is showing?
 *
 * One calendar day, because one shift runs here. A site running the design's
 * three shifts — С is 22:00–06:00 — would need a window with an hour on both
 * ends; this one does not, and inventing the general case would mean choosing
 * shift boundaries nothing records.
 */
function finishedInShift(row, shiftDay) {
	const at = row?.actual_end_date;
	// No recorded finish: a Work Order closed by hand never ran. It is finished,
	// but it is not this shift's output, and counting it would add a card with no
	// production to the shift's quantity total.
	if (!at) return false;
	return String(at).slice(0, 10) === shiftDay;
}

/**
 * Group rows into the board's columns, in the board's order.
 *
 * @param rows the orders on screen
 * @param shiftDay optional `YYYY-MM-DD`. When given, the `done` column holds
 *        only what finished that day — the design's «Завершён · смена». anjan
 *        carries 3 756 finished orders against 2 finished today (measured
 *        2026-08-29), so an unbounded column buries the cards somebody is
 *        actually working with and makes its quantity a figure about the year.
 *        Omitted, nothing is hidden: a caller that promises nothing in its
 *        header must not silently drop rows.
 *
 * @returns {Record<string, Array>} every column present, empty ones included —
 *          a column that disappears when it has no cards makes the board's
 *          shape change under the user, and hides the step they are skipping.
 */
export function boardGroups(rows, shiftDay = null) {
	const groups = Object.fromEntries(BOARD_COLUMNS.map((c) => [c, []]));
	for (const row of Array.isArray(rows) ? rows : []) {
		const column = boardColumn(row);
		if (!column) continue;
		if (column === "done" && shiftDay && !finishedInShift(row, shiftDay)) continue;
		groups[column].push(row);
	}
	return groups;
}

/**
 * How many finished orders the shift window is holding back.
 *
 * The cards are hidden; the fact is not. A header reading "2" over a factory
 * that has finished 3 756 orders is true and misleading — the difference is
 * what tells a supervisor the window is on, and roughly how much sits behind it.
 */
export function doneEarlier(rows, shiftDay = null) {
	if (!shiftDay) return 0;
	let n = 0;
	for (const row of Array.isArray(rows) ? rows : []) {
		if (boardColumn(row) === "done" && !finishedInShift(row, shiftDay)) n += 1;
	}
	return n;
}
