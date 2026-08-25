import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));
const { roleLabel } = await import("../composables/workOrderRoles.js");

const here = dirname(fileURLToPath(import.meta.url));
const list = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");
const kiosk = readFileSync(
	resolve(here, "../pages/manufacturing/ManufacturingOperatorBoard.vue"),
	"utf8"
);

/**
 * The per-role deviation panel under the materials table.
 *
 * Its whole reason to exist is answering "did this person run over plan", so the
 * two things that can quietly ruin it are both about arithmetic nobody sees:
 * adding litres to pieces, and totalling an order that is only half written off.
 * Both are decided in `stabler.api.manufacturing._role_deviation`, which is unit
 * tested directly. What these tests pin is that the component reads that answer
 * rather than growing a second one — a `reduce` over `required_items` in the
 * template would look right and would be wrong the first time an order mixed kg
 * with pieces.
 */
describe("deviation panel", () => {
	it("renders the backend's buckets", () => {
		expect(list).toContain("detail.role_deviation");
	});

	it("does not re-derive the buckets in the component", () => {
		// No client-side grouping of material rows by role. If this ever needs to
		// change, the rule moves to one place — it does not get a second home.
		expect(list).not.toMatch(/required_items[\s\S]{0,120}(reduce|groupBy)/);
	});

	it("says which lines were left out instead of totalling them silently", () => {
		// A total built from half an order looks exactly like a total built from all
		// of it. The count is the only thing that distinguishes them on screen.
		expect(list).toContain("pending_lines");
	});
});

/**
 * `Item.custom_operator_role` stores "Production" because that is the value the
 * API compares against. The floor calls it pouring. One translation of that pair,
 * in one place — the kiosk badge and the material table must not disagree about
 * what a stored value is called.
 */
describe("roleLabel", () => {
	it("gives the floor's word for each stored value", () => {
		expect(roleLabel("Production")).toBe("Pouring");
		expect(roleLabel("Packaging")).toBe("Packaging");
	});

	it("returns nothing for an undecided line, leaving the wording to the caller", () => {
		// An undecided *item* and an unassigned *operator* are different sentences,
		// and a shared fallback would put one of them in the wrong place.
		expect(roleLabel(null)).toBe("");
		expect(roleLabel("")).toBe("");
	});

	for (const [label, src] of [["work order list", list], ["kiosk", kiosk]]) {
		it(`${label} imports roleLabel instead of restating it`, () => {
			expect(src).toContain("roleLabel");
			expect(src).not.toMatch(/const roleLabel\s*=/);
		});
	}
});
