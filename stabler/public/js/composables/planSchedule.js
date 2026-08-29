// The planned hours of a Work Order: into the boxes that edit them, and back
// onto the block that shows them.
//
// Both halves exist because design 1c's grid needs a position and a width, and
// measured on anjan 2026-08-29 it has neither — 3 464 of 3 799 orders carry a
// `planned_start_date` within 60 seconds of `creation` (ERPNext's default, the
// moment somebody opened the form) and 0 carry a `planned_end_date`. The server
// side of this is `schedule_window` in `api/_wo_plan.py`.

/**
 * Split a stored datetime into the day and minute an editor works in.
 *
 * Seconds are dropped because `<input type="time">` will not accept them, and
 * every row this site has written carries them — with microseconds.
 *
 * @returns {{day: string, time: string}} both empty when there is no stamp,
 *          which is the ordinary case for the end: no order carries one yet.
 */
export function splitStamp(value) {
	const text = String(value ?? "");
	// Guard on the shape, not on truthiness: `String(null)` is "null", and a box
	// pre-filled with `null` is the kind of thing a planner saves without seeing.
	if (text.length < 10 || !/^\d{4}-\d{2}-\d{2}/.test(text)) return { day: "", time: "" };
	return { day: text.slice(0, 10), time: text.slice(11, 16) };
}

/**
 * What the block on the grid says about its hours.
 *
 * @returns {string} `08:00–14:30`, or `08:00` when only a start is known, or
 *          `22:00–06:00+1` when the end lands on another day — without that
 *          marker an overnight window reads as ending before it starts. Empty
 *          when there is no start at all: the badge already carries the item and
 *          the quantity, and a dash under every one of 3 799 rows is furniture.
 */
export function scheduleLabel(order) {
	const start = splitStamp(order?.planned_start_date);
	if (!start.time) return "";
	const end = splitStamp(order?.planned_end_date);
	if (!end.time) return start.time;
	return `${start.time}–${end.time}${end.day !== start.day ? "+1" : ""}`;
}
