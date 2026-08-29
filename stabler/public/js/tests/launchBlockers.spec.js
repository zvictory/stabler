// Design 1c's right-hand panel — «ЧТО МЕШАЕТ ЗАПУСКУ».
//
// The panel asks a different question from the card chip beside it, and the
// difference is the reason this module exists. `materialReadiness` asks "can
// THIS order run" — one order against the shelf. The panel asks "what is
// missing across the orders waiting to start", which is a SUM against the same
// shelf. Two orders that each need 200 kg of a material the store holds 240 of
// both read "ready" on their own cards and cannot both run.
//
// Only orders waiting to start count. A shortage on a running order is not
// blocking a launch — the material it still needs is a different problem, and
// mixing the two makes the headline count answer neither question.
//
// What is deliberately NOT modelled, because nothing records it: the design's
// third card («Плёнка упаковочная · ожидается 13:00 · PO-2026-0431 в пути»)
// needs an incoming purchase order linked to the material and an ETA. Measured
// on anjan 2026-08-29 there is no such link on the Work Order side, and an
// invented arrival time on a blocker panel is the worst possible lie.

import { describe, it, expect } from "vitest";
import { launchBlockers } from "../composables/launchBlockers.js";
import { stockKey } from "../composables/materialReadiness.js";

function wo(name, items, over = {}) {
	return {
		name,
		docstatus: 1,
		status: "Not Started",
		qty: 1000,
		produced_qty: 0,
		transferred_qty: 0,
		required_items: items,
		...over,
	};
}

const line = (item, required, over = {}) => ({
	item_code: item,
	item_name: item,
	required_qty: required,
	transferred_qty: 0,
	source_warehouse: "Stores - A",
	...over,
});

const shelf = (item, qty, warehouse = "Stores - A") => ({ [stockKey(warehouse, item)]: qty });

describe("what a shortage is, once orders are counted together", () => {
	it("finds nothing when the store covers everything", () => {
		const out = launchBlockers([wo("W1", [line("CREAM", 200)])], shelf("CREAM", 240));
		expect(out.blockers).toEqual([]);
	});

	it("adds up what the waiting orders need from one shelf", () => {
		// Neither order is short on its own. Together they are, and this is the
		// only screen that can say so — the cards cannot, because each is right.
		const rows = [wo("W1", [line("CREAM", 200)]), wo("W2", [line("CREAM", 200)])];
		const out = launchBlockers(rows, shelf("CREAM", 240));
		expect(out.blockers).toHaveLength(1);
		expect(out.blockers[0]).toMatchObject({
			item_code: "CREAM",
			warehouse: "Stores - A",
			needed: 400,
			available: 240,
			shortfall: 160,
		});
		expect(out.blockers[0].blocks).toEqual(["W1", "W2"]);
	});

	it("counts only what is still to be issued", () => {
		// Material already transferred into WIP is off the shelf and off this
		// panel. Counting the full requirement would report a shortage of stock
		// that has already moved.
		const rows = [wo("W1", [line("CREAM", 300, { transferred_qty: 300 })])];
		expect(launchBlockers(rows, shelf("CREAM", 10)).blockers).toEqual([]);
	});

	it("keeps the same item on two shelves apart", () => {
		// A shortage is a fact about a shelf, not about an item: 40 kg in the
		// wrong store does not start the line, and merging the two would hide it.
		const rows = [
			wo("W1", [line("CREAM", 100)]),
			wo("W2", [line("CREAM", 100, { source_warehouse: "Stores - B" })]),
		];
		const stock = { ...shelf("CREAM", 40), ...shelf("CREAM", 100, "Stores - B") };
		const out = launchBlockers(rows, stock);
		expect(out.blockers).toHaveLength(1);
		expect(out.blockers[0].warehouse).toBe("Stores - A");
	});
});

describe("which orders count", () => {
	it("ignores an order that is already running", () => {
		// Its material problem is real and is not a launch problem. Mixing them
		// makes the headline count answer neither question.
		const rows = [wo("W1", [line("CREAM", 500)], { status: "In Process" })];
		expect(launchBlockers(rows, shelf("CREAM", 1)).blockers).toEqual([]);
	});

	it("ignores a draft, which cannot be launched at all", () => {
		expect(launchBlockers([wo("W1", [line("CREAM", 500)], { docstatus: 0 })], shelf("CREAM", 1)).blockers).toEqual([]);
	});

	it("ignores a finished order", () => {
		const rows = [wo("W1", [line("CREAM", 500)], { status: "Completed", produced_qty: 1000 })];
		expect(launchBlockers(rows, shelf("CREAM", 1)).blockers).toEqual([]);
	});
});

describe("the order the panel reads in", () => {
	it("puts the shortage that stops the most orders first", () => {
		// A supervisor works this list top down, and the material that unblocks
		// three orders is worth chasing before the one that unblocks one — even
		// when the second shortfall is larger.
		const rows = [
			wo("W1", [line("CREAM", 100), line("BOX", 900)]),
			wo("W2", [line("CREAM", 100)]),
			wo("W3", [line("CREAM", 100)]),
		];
		const stock = { ...shelf("CREAM", 10), ...shelf("BOX", 10) };
		const out = launchBlockers(rows, stock);
		expect(out.blockers.map((b) => b.item_code)).toEqual(["CREAM", "BOX"]);
	});

	it("settles a tie the same way every time", () => {
		// Two shortages blocking one order each must not swap places between
		// loads; the panel is read at a glance and movement reads as change.
		const rows = [wo("W1", [line("ZINC", 100), line("ALPHA", 100)])];
		const stock = { ...shelf("ZINC", 0), ...shelf("ALPHA", 0) };
		const first = launchBlockers(rows, stock).blockers.map((b) => b.item_code);
		expect(first).toEqual(["ALPHA", "ZINC"]);
	});
});

describe("a shelf nobody measured is not a shelf that is full", () => {
	it("is reported rather than skipped in silence", () => {
		// `loadStock` leaves a warehouse out when its call failed. Dropping those
		// lines would let the panel print "nothing is blocking" over materials it
		// never looked at — on this screen the worst possible answer.
		const rows = [wo("W1", [line("CREAM", 100), line("FILM", 100)])];
		const out = launchBlockers(rows, shelf("CREAM", 500));
		expect(out.blockers).toEqual([]);
		expect(out.unmeasured).toBe(1);
	});

	it("counts one unmeasured shelf once, however many orders want it", () => {
		const rows = [wo("W1", [line("FILM", 100)]), wo("W2", [line("FILM", 100)])];
		expect(launchBlockers(rows, {}).unmeasured).toBe(1);
	});
});

describe("nothing to say", () => {
	it("survives an empty or absent row list", () => {
		expect(launchBlockers([], {})).toEqual({ blockers: [], unmeasured: 0 });
		expect(launchBlockers(null, null)).toEqual({ blockers: [], unmeasured: 0 });
	});
});
