// Design 1c's right-hand panel — «ЧТО МЕШАЕТ ЗАПУСКУ».
//
// This is the half of 1c that is backed by data. The half that is not — the
// line × time grid — is documented at the bottom of this file, because the
// absence is the reason the panel exists on its own.
//
// The question here is deliberately not the one the cards answer.
// `materialReadiness` asks "can THIS order run", one order against the shelf,
// and it is right on every card. The panel asks what is missing across all the
// orders waiting to start, which is a SUM against the same shelf — and two
// orders that each need 200 kg of a material the store holds 240 of both read
// "ready" on their own cards and cannot both run.

import { stockKey } from "./materialReadiness.js";
import { boardColumn } from "./shopFloorBoard.js";

// Same tolerance as `materialReadiness`: quantities arrive as floats and a
// shelf that covers exactly must not read as short.
const EPSILON = 1e-6;
const settle = (n) => Math.round(n * 1e6) / 1e6;

/**
 * What is stopping the waiting orders from starting.
 *
 * @param rows `list_work_orders` rows, as the register already holds them
 * @param stock `stockKey()` → quantity on hand, as `loadStock` already builds it
 * @returns {{blockers: Array, unmeasured: number}}
 *   `blockers` is sorted the way the panel is read: the shortage that stops the
 *   most orders first — a supervisor works the list top down, and the material
 *   that unblocks three orders is worth chasing before the one that unblocks
 *   one, even when the second shortfall is larger. Ties settle on the item code
 *   so the panel does not reshuffle between loads.
 *   `unmeasured` counts the shelves `loadStock` could not read. They are not
 *   folded into the blockers — nothing is guessed here — but they are not
 *   dropped either: "nothing is blocking" printed over materials nobody looked
 *   at is the worst answer this screen can give.
 */
export function launchBlockers(rows, stock) {
	const shelves = stock || {};
	const byShelf = new Map();
	const unmeasured = new Set();

	for (const row of Array.isArray(rows) ? rows : []) {
		// Only orders waiting to start. A shortage on a running order is real and
		// is not a launch problem; a draft cannot be launched at all. Mixing
		// either in makes the headline count answer neither question.
		if (boardColumn(row) !== "ready") continue;

		for (const line of row?.required_items || []) {
			if (!line?.item_code || !line?.source_warehouse) continue;
			// Already in WIP: off the shelf and off this panel. Counting the full
			// requirement would report a shortage of stock that has already moved.
			const outstanding = (Number(line.required_qty) || 0) - (Number(line.transferred_qty) || 0);
			if (outstanding <= 0) continue;

			const key = stockKey(line.source_warehouse, line.item_code);
			if (!(key in shelves)) {
				unmeasured.add(key);
				continue;
			}
			let entry = byShelf.get(key);
			if (!entry) {
				entry = {
					item_code: line.item_code,
					item_name: line.item_name || line.item_code,
					// A shortage is a fact about a shelf, not about an item: 40 kg in
					// the wrong store does not start the line.
					warehouse: line.source_warehouse,
					needed: 0,
					available: Number(shelves[key]) || 0,
					blocks: [],
				};
				byShelf.set(key, entry);
			}
			entry.needed = settle(entry.needed + outstanding);
			if (!entry.blocks.includes(row.name)) entry.blocks.push(row.name);
		}
	}

	const blockers = [...byShelf.values()]
		.map((e) => ({ ...e, shortfall: settle(e.needed - e.available) }))
		.filter((e) => e.shortfall > EPSILON)
		.sort(
			(a, b) =>
				b.blocks.length - a.blocks.length ||
				b.shortfall - a.shortfall ||
				a.item_code.localeCompare(b.item_code),
		);

	return { blockers, unmeasured: unmeasured.size };
}

// Not built, and measured rather than assumed — anjan, 2026-08-29:
//
//     planned_start_date populated            3 799 / 3 799
//       ...but within 60s of `creation`       3 464   (91%)
//     planned_end_date populated                  0
//     actual_end == actual_start (last 30d)     354 / 434  (82%)
//     Workstation rows                            0
//     BOMs with an operating_cost                 0
//
// The design's grid needs a position, a width and a capacity. The position is
// `planned_start_date`, which is 91% the moment somebody opened the form rather
// than a plan; there is no width, because no order records an end; and there is
// no capacity, because nothing records a line's rate. A grid drawn from that
// renders perfectly and charts data entry — the dangerous kind of absence,
// because it looks like a schedule. It waits on a planner entering real times.
