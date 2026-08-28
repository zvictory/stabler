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

	// The guard that decides whether a card exists has two halves, and every
	// other test here exercises only one of them: it drops a role that has
	// neither work nor an operator. Remove the `!own.length` half and this is
	// the case that breaks — packaging work is on the BOM, nobody was assigned
	// to it, and the whole card vanishes. The unassigned-operator warning the
	// detail page renders is then never drawn on the one order it exists for,
	// so the accountability gap the split was built to expose disappears
	// silently at exactly the moment it is real.
	it("still draws a stage that has work on it but nobody assigned", () => {
		const stages = workOrderStages({
			operator: "Ali",
			packaging_operator: "",
			required_items: [item("MILK", "Production", 2000), item("BOX", "Packaging", 1000)],
		});

		expect(stages.map((s) => s.role)).toEqual(["Production", "Packaging"]);
		expect(stages[1].operator).toBe("");
		expect(stages[1].lines).toBe(1);
	});

	// `work_order_detail` hands a manager or a warehouse user the whole bill of
	// materials, but an operator gets only the lines their own role writes off —
	// hand a pourer the label rows and that loss lands on the wrong person's KPI.
	// The operator names are not filtered with them, so from this composable's
	// side the other role looks like a stage that somebody is assigned to and
	// that has no work on it: exactly the mis-set-BOM shape the warning exists
	// to shout about. It then shouts on every order every operator opens, which
	// is the fastest way to teach people that the one high-signal warning on the
	// page means nothing.
	it("does not call a stage empty when the server only hid its items", () => {
		const stages = workOrderStages({
			items_scoped_to_role: "Production",
			operator: "Ali",
			packaging_operator: "Vera",
			required_items: [item("MILK", "Production", 2000)],
		});

		const packaging = stages.find((s) => s.role === "Packaging");
		expect(packaging, "the other role should still be visible").toBeTruthy();
		expect(packaging.itemsHidden).toBe(true);
		expect(packaging.operator).toBe("Vera");
	});

	it("still calls a genuinely empty stage empty for whoever can see everything", () => {
		// The manager's payload carries no scope flag, so the warning has to keep
		// firing for them — they are the one who can actually fix the BOM.
		const stages = workOrderStages({
			operator: "Ali",
			packaging_operator: "Vera",
			required_items: [item("MILK", "Production", 2000)],
		});

		const packaging = stages.find((s) => s.role === "Packaging");
		expect(packaging.itemsHidden).toBe(false);
		expect(packaging.lines).toBe(0);
	});

	it("does not hide the viewer's own stage from them", () => {
		const stages = workOrderStages({
			items_scoped_to_role: "Packaging",
			operator: "Ali",
			packaging_operator: "Vera",
			required_items: [item("BOX", "Packaging", 1000)],
		});

		expect(stages.find((s) => s.role === "Packaging").itemsHidden).toBe(false);
	});
});
