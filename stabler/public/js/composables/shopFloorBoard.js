// «Канбан: состояние цеха» — which column a Work Order card sits in.
//
// The columns are a DERIVED state, not ERPNext's `status` field. That
// distinction is the whole reason this board exists at all: `status` is
// read-only after submit and 99.1% of anjan's orders carry one value, which is
// what got this design recorded as dead on 2026-08-28. The design never used it
// — its columns are draft / waiting / partly issued / running / halted / done,
// and its cards carry buttons rather than drag handles.
//
// Material shortage is deliberately NOT a column. The design shows it as a badge
// inside «Готов к запуску» ("Дефицит блокирует старт"), which is the right
// shape: a short order is still waiting to start, and moving it to a bin of its
// own would hide it from the column a supervisor is working down. The badge
// comes from `materialReadiness`, which already answers it.

/** Left to right, as the design lays them out. */
export const BOARD_COLUMNS = ["draft", "ready", "partial", "running", "paused", "done"];

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

	// Nothing issued yet: the order is waiting for the store, which is the
	// column a shift lead works down.
	const transferred = Number(row?.transferred_qty) || 0;
	if (transferred <= 0) return "ready";

	// Something has been issued. `>=` and not `===` because ERPNext allows
	// transferring more than the order quantity, and an over-issued order must
	// not fall out of every branch. Fully issued still counts as "partly on its
	// way" rather than running: the material is at the machine and the machine
	// has not started, and calling that running would show two orders on a line
	// that is running one.
	return "partial";
}

/**
 * Group rows into the board's columns, in the board's order.
 *
 * @returns {Record<string, Array>} every column present, empty ones included —
 *          a column that disappears when it has no cards makes the board's
 *          shape change under the user, and hides the step they are skipping.
 */
export function boardGroups(rows) {
	const groups = Object.fromEntries(BOARD_COLUMNS.map((c) => [c, []]));
	for (const row of Array.isArray(rows) ? rows : []) {
		const column = boardColumn(row);
		if (column) groups[column].push(row);
	}
	return groups;
}
