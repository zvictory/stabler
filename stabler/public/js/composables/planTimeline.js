// Design 1c's grid: line × time, one day.
//
// The grid needs a position and a width per block, and this site records
// neither — measured on anjan 2026-08-29, 3 464 of 3 799 orders carry a
// `planned_start_date` within 60 seconds of `creation` (ERPNext writes it when
// the form opens; it is not a plan) and 0 carry a `planned_end_date`. That is
// why the grid was left unbuilt at first, and it is why the single rule below
// runs through every function here:
//
//     A BLOCK GETS A WIDTH ONLY WHEN AN END WAS TYPED.
//
// An order with a start and no end is drawn as a mark at its hour — visible,
// clickable, and honest that nobody has said how long it runs. No default
// duration, no average, no shift length. The grid therefore starts nearly empty
// and fills as the hours form beside it is used, which is the point: it is the
// tool that creates the data it draws.
//
// What is NOT here, each because the input does not exist: a load percentage
// per line (0 Workstations, 0 BOMs with an operating cost), a rate in units per
// hour (nothing records one), and shift bands (this factory runs one shift).

const DEFAULT_FROM = 6;
const DEFAULT_TO = 22;

// A six-minute job on a sixteen-hour ruler is 0.6% wide: a sliver nobody can
// see or click. This is a drawing floor and nothing else — `hours` on the same
// block carries the real duration for the label, so the number a planner reads
// is never the number this widened.
const MIN_WIDTH_PCT = 1.5;

function parse(value) {
	const text = String(value ?? "");
	if (!/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(text)) return null;
	return { day: text.slice(0, 10), hours: Number(text.slice(11, 13)) + Number(text.slice(14, 16)) / 60 };
}

/**
 * The hours the ruler has to cover for these orders.
 *
 * @returns {{from: number, to: number}} whole hours. Defaults to a working day
 *          so an empty grid still has columns — a grid with no ruler reads as a
 *          screen that failed to load, and gives the planner nothing to aim at.
 */
export function dayWindow(orders) {
	let from = DEFAULT_FROM;
	let to = DEFAULT_TO;
	for (const order of Array.isArray(orders) ? orders : []) {
		const start = parse(order?.planned_start_date);
		if (!start) continue;
		from = Math.min(from, Math.floor(start.hours));
		to = Math.max(to, Math.ceil(start.hours));
		const end = parse(order?.planned_end_date);
		if (!end) continue;
		// A row is one day wide. An order that runs past midnight is drawn to the
		// edge and marked; wrapping it round to the left would draw a second job
		// on a line that is running one.
		to = end.day === start.day ? Math.max(to, Math.ceil(end.hours)) : 24;
	}
	return { from: Math.max(0, from), to: Math.min(24, to) };
}

/**
 * Where one order sits on the ruler.
 *
 * @returns {{left: number, width: ?number, hours: ?number, overnight: boolean}|null}
 *          null when the order has no hour to place. `width` is null — never 0,
 *          never a default — when no end was typed: the caller draws a mark
 *          instead of a bar, and the difference between "runs until 14:30" and
 *          "nobody has said" stays visible on the screen.
 */
export function blockGeometry(order, window) {
	const start = parse(order?.planned_start_date);
	if (!start) return null;
	const span = (window?.to ?? DEFAULT_TO) - (window?.from ?? DEFAULT_FROM);
	if (span <= 0) return null;
	const left = ((start.hours - window.from) / span) * 100;

	const end = parse(order?.planned_end_date);
	if (!end) return { left, width: null, hours: null, overnight: false };

	const overnight = end.day !== start.day;
	const endHours = overnight ? window.to : end.hours;
	const hours = endHours - start.hours;
	// Data written before the server-side guard existed — or by the Desk, which
	// has no such guard — can still end before it starts. It must not draw
	// backwards; it reads as "no end typed", which is what it is worth.
	if (hours <= 0) return { left, width: null, hours: null, overnight };

	return {
		left,
		width: Math.max(MIN_WIDTH_PCT, (hours / span) * 100),
		hours,
		overnight,
	};
}

/**
 * The grid's rows, and everything that could not go on one.
 *
 * @returns {{rows: Array<{line, blocks}>, offGrid: Array}}
 *          Every requested line is a row, including the idle ones: a row that
 *          disappears when its line has nothing on it hides the idleness, which
 *          is the thing a planner opened this screen to find.
 *          `offGrid` carries orders with no hour or a line this grid is not
 *          showing — work somebody scheduled, so it is named rather than
 *          swallowed. Same contract as `build_plan_grid`.
 */
export function timelineRows(orders, lines) {
	const window = dayWindow(orders);
	const byLine = new Map((lines || []).map((line) => [line, []]));
	const offGrid = [];

	for (const order of Array.isArray(orders) ? orders : []) {
		const bucket = byLine.get(order?.wip_warehouse || "");
		const geometry = bucket ? blockGeometry(order, window) : null;
		if (!bucket || !geometry) {
			offGrid.push(order);
			continue;
		}
		bucket.push({ order, ...geometry });
	}

	return {
		window,
		rows: [...byLine].map(([line, blocks]) => ({
			line,
			blocks: blocks.sort((a, b) => a.left - b.left),
		})),
		offGrid,
	};
}
