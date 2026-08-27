import { describe, expect, it, vi } from "vitest";

vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));
const { workOrderStages } = await import("../composables/workOrderStages.js");

const item = (code, role, req, moved = 0, used = 0) => ({
	item_code: code,
	item_name: code,
	operator_role: role,
	required_qty: req,
	transferred_qty: moved,
	consumed_qty: used,
});

describe("workOrderStages", () => {
	// This tenant's orders do not carry ERPNext routing — no BOM Operation rows,
	// no Workstations. What they do carry is two people with two different jobs
	// and a BOM split between them, so that is what a "stage" is here.
	it("splits the bill of materials by the role that owns it", () => {
		const stages = workOrderStages({
			operator: "Ali",
			packaging_operator: "Vera",
			required_items: [item("MILK", "Production", 2000), item("BOX", "Packaging", 1000)],
		});

		expect(stages.map((s) => s.role)).toEqual(["Production", "Packaging"]);
		expect(stages[0].operator).toBe("Ali");
		expect(stages[1].items.map((i) => i.item_code)).toEqual(["BOX"]);
	});

	// The whole point of the split is accountability. An item nobody owns is the
	// one that needs saying out loud; folding it into a stage would name the
	// wrong person, and dropping it makes a half-described order look complete.
	it("gives the items nobody owns a stage of their own", () => {
		const stages = workOrderStages({
			operator: "Ali",
			required_items: [item("MILK", "Production", 2000), item("DYE", null, 5)],
		});

		const orphan = stages.find((s) => !s.role);
		expect(orphan.items.map((i) => i.item_code)).toEqual(["DYE"]);
	});

	// A packer assigned to an order whose BOM gives packing nothing to do is a
	// mis-set BOM role, and it is invisible unless the empty stage still shows.
	it("shows a stage that has an operator but no materials", () => {
		const stages = workOrderStages({
			packaging_operator: "Vera",
			required_items: [item("MILK", "Production", 2000)],
		});

		const packing = stages.find((s) => s.role === "Packaging");
		expect(packing.operator).toBe("Vera");
		expect(packing.lines).toBe(0);
	});

	// ...but do not invent one. An order with no packing role and no packer has
	// one stage, and a permanently empty second card trains people to ignore it.
	it("omits a stage with neither materials nor an operator", () => {
		const stages = workOrderStages({
			operator: "Ali",
			required_items: [item("MILK", "Production", 2000)],
		});

		expect(stages.map((s) => s.role)).toEqual(["Production"]);
	});

	// The same reason the deviation footer refuses to add rows up: these lines
	// are litres, kilograms and pieces at once, and one total across them is
	// wrong without looking wrong. A stage counts lines, never quantities.
	it("counts lines, not quantities", () => {
		const stages = workOrderStages({
			operator: "Ali",
			required_items: [
				item("MILK", "Production", 2000, 2000, 2000),
				item("SUGAR", "Production", 300, 300, 0),
			],
		});

		expect(stages[0].lines).toBe(2);
		expect(stages[0].transferredLines).toBe(2);
		expect(stages[0].consumedLines).toBe(1);
	});

	// A line half-issued is not issued. Counting it as transferred is how an
	// order gets released to the floor with material still in the store.
	it("does not call a part-transferred line transferred", () => {
		const stages = workOrderStages({
			operator: "Ali",
			required_items: [item("MILK", "Production", 2000, 1999)],
		});

		expect(stages[0].transferredLines).toBe(0);
	});

	it("attaches each role's deviation bucket to its own stage", () => {
		const stages = workOrderStages({
			operator: "Ali",
			packaging_operator: "Vera",
			required_items: [item("MILK", "Production", 2000), item("BOX", "Packaging", 1000)],
			role_deviation: [
				{ role: "Packaging", cost: -12, counted_lines: 1, pending_lines: 0 },
				{ role: "Production", cost: 340, counted_lines: 1, pending_lines: 0 },
			],
		});

		expect(stages.find((s) => s.role === "Production").deviation.cost).toBe(340);
		expect(stages.find((s) => s.role === "Packaging").deviation.cost).toBe(-12);
	});

	it("says nothing about an order it was handed nothing for", () => {
		expect(workOrderStages(null)).toEqual([]);
	});
});
