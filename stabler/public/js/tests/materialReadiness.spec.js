import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
const { materialReadiness, materialsForUnits, stockKey } = await import(
	"../composables/materialReadiness.js"
);

const stock = (pairs) => {
	const m = {};
	for (const [wh, item, qty] of pairs) m[stockKey(wh, item)] = qty;
	return m;
};

describe("materialReadiness", () => {
	it("reports how many more units the store can cover", () => {
		const row = {
			qty: 100,
			required_items: [
				{ item_code: "MILK", required_qty: 200, transferred_qty: 0, source_warehouse: "Store" },
				{ item_code: "BOX", required_qty: 100, transferred_qty: 0, source_warehouse: "Store" },
			],
		};

		const r = materialReadiness(row, stock([["Store", "MILK", 600], ["Store", "BOX", 900]]));

		expect(r.state).toBe("ready");
		// MILK covers 300 units, BOX covers 900. The line stops at 300.
		expect(r.unitsCovered).toBe(300);
	});

	// One missing ingredient stops the line, so the answer is the minimum, never
	// an average and never the most plentiful item. Reporting 900 here because
	// there are plenty of boxes would send a supervisor to start an order that
	// runs dry after 5 units.
	it("takes the binding constraint, not the comfortable one", () => {
		const row = {
			qty: 100,
			required_items: [
				{ item_code: "MILK", required_qty: 200, transferred_qty: 0, source_warehouse: "Store" },
				{ item_code: "BOX", required_qty: 100, transferred_qty: 0, source_warehouse: "Store" },
			],
		};

		const r = materialReadiness(row, stock([["Store", "MILK", 10], ["Store", "BOX", 900]]));

		expect(r.unitsCovered).toBe(5);
		expect(r.state).toBe("short");
		expect(r.shortCount).toBe(1);
	});

	// A supervisor needs to know whether it is one line to chase or twelve.
	it("counts the short lines rather than only flagging them", () => {
		const row = {
			qty: 10,
			required_items: [
				{ item_code: "A", required_qty: 10, transferred_qty: 0, source_warehouse: "Store" },
				{ item_code: "B", required_qty: 10, transferred_qty: 0, source_warehouse: "Store" },
				{ item_code: "C", required_qty: 10, transferred_qty: 0, source_warehouse: "Store" },
			],
		};

		const r = materialReadiness(row, stock([["Store", "A", 0], ["Store", "B", 0], ["Store", "C", 99]]));

		expect(r.shortCount).toBe(2);
	});

	// An order whose material is already in WIP asks the store for nothing.
	// Calling it "short" because the store shelf is empty would put a red chip on
	// the one order that is actually ready to run.
	it("does not call a fully issued order short", () => {
		const row = {
			qty: 100,
			required_items: [
				{ item_code: "MILK", required_qty: 200, transferred_qty: 200, source_warehouse: "Store" },
			],
		};

		const r = materialReadiness(row, stock([["Store", "MILK", 0]]));

		expect(r.state).toBe("in_place");
		expect(r.shortCount).toBe(0);
	});

	it("only asks the store for what is still to be issued", () => {
		const row = {
			qty: 100,
			required_items: [
				{ item_code: "MILK", required_qty: 200, transferred_qty: 150, source_warehouse: "Store" },
			],
		};

		const r = materialReadiness(row, stock([["Store", "MILK", 50]]));

		expect(r.state).toBe("ready");
		expect(r.shortCount).toBe(0);
	});

	// The chip is read at a glance and acted on. Claiming availability that was
	// never measured is worse than saying nothing — the supervisor walks to a
	// store that cannot fill the order.
	it("says unknown rather than ready when the stock figure never arrived", () => {
		const row = {
			qty: 100,
			required_items: [
				{ item_code: "MILK", required_qty: 200, transferred_qty: 0, source_warehouse: "Store" },
			],
		};

		const r = materialReadiness(row, {});

		expect(r.state).toBe("unknown");
	});

	it("survives an order with no materials and an order with no quantity", () => {
		expect(materialReadiness({ qty: 10, required_items: [] }, {}).state).toBe("unknown");
		expect(
			materialReadiness(
				{ qty: 0, required_items: [{ item_code: "A", required_qty: 5, transferred_qty: 0, source_warehouse: "S" }] },
				stock([["S", "A", 5]]),
			).unitsCovered,
		).toBe(null);
	});
});

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");

describe("the materials column", () => {
	it("exists in the list header", () => {
		const head = src.slice(src.indexOf("<thead>"), src.indexOf("</thead>"));

		expect(head).toMatch(/t\("Materials"\)/);
	});

	it("renders every state the function can return", () => {
		for (const state of ["in_place", "ready", "short"]) {
			expect(src, `no branch for ${state}`).toContain(`'${state}'`);
		}
	});

	// The whole point of the `unknown` state is that it must not look like good
	// news. A green chip on an unmeasured row is the failure this guards.
	it("shows a dash for unknown, never a chip", () => {
		const cell = src.slice(src.indexOf("readiness(r).state === 'in_place'"));
		const fallback = cell.slice(0, cell.indexOf("</td>"));

		expect(fallback).toMatch(/v-else class="text-secondary small">—/);
		expect(fallback).not.toMatch(/v-else class="badge/);
	});

	it("loads shelf stock once per warehouse, not once per row", () => {
		expect(src).toMatch(/byWarehouse/);
		expect(src).toMatch(/get_items_stock/);
	});
});

describe("materialsForUnits", () => {
	const row = {
		qty: 1000,
		produced_qty: 0,
		required_items: [
			{ item_code: "MILK", item_name: "Milk", required_qty: 2000, transferred_qty: 0, source_warehouse: "Store" },
			{ item_code: "BOX", item_name: "Box", required_qty: 1000, transferred_qty: 0, source_warehouse: "Store" },
		],
	};

	// The dialog replaces a bare browser prompt that asked for a number and
	// showed nothing. Typing 500 has to show what 500 costs, or the list is
	// decoration and the operator is still guessing.
	it("scales the requirement to the quantity being transferred", () => {
		const rows = materialsForUnits(row, stock([["Store", "MILK", 9999], ["Store", "BOX", 9999]]), 500);

		expect(rows.map((r) => r.needed)).toEqual([1000, 500]);
	});

	it("marks the lines the store cannot cover at that quantity", () => {
		const rows = materialsForUnits(row, stock([["Store", "MILK", 800], ["Store", "BOX", 9999]]), 500);

		expect(rows.find((r) => r.item_code === "MILK").short).toBe(true);
		expect(rows.find((r) => r.item_code === "BOX").short).toBe(false);
	});

	// Same rule as the list chip: an unmeasured shelf is not a full one and not
	// an empty one. Marking it short would send someone chasing a shortage that
	// may not exist; marking it fine would hide one that does.
	it("calls an unmeasured shelf unknown, not short and not fine", () => {
		const rows = materialsForUnits(row, stock([["Store", "BOX", 9999]]), 500);
		const milk = rows.find((r) => r.item_code === "MILK");

		expect(milk.available).toBe(null);
		expect(milk.short).toBe(false);
	});

	it("asks for nothing at zero units", () => {
		const rows = materialsForUnits(row, stock([["Store", "MILK", 0], ["Store", "BOX", 0]]), 0);

		expect(rows.every((r) => r.needed === 0)).toBe(true);
		expect(rows.some((r) => r.short)).toBe(false);
	});

	it("survives an order with no quantity to scale against", () => {
		const rows = materialsForUnits({ qty: 0, required_items: row.required_items }, {}, 10);

		expect(rows.every((r) => r.needed === 0)).toBe(true);
	});
});
