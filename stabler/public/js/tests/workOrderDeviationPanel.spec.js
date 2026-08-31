import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

vi.mock("../composables/i18n.js", () => ({ t: (s) => s }));
const { roleLabel } = await import("../composables/workOrderRoles.js");

const here = dirname(fileURLToPath(import.meta.url));
const list = readFileSync(resolve(here, "../pages/manufacturing/WorkOrderDetail.vue"), "utf8");

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

	// The kiosk dropped out of this loop on 2026-08-31: it imported `roleLabel`
	// for the write-off dialog's role badge, and the write-off left the operator
	// screen entirely. The manager's list still names roles and still must not
	// restate the helper.
	for (const [label, src] of [["work order list", list]]) {
		it(`${label} imports roleLabel instead of restating it`, () => {
			expect(src).toContain("roleLabel");
			expect(src).not.toMatch(/const roleLabel\s*=/);
		});
	}
});

/**
 * The materials list's WIP Stock line. No backend endpoint — not
 * `list_work_orders`, not `work_order_detail` — has ever set `wip_stock`, so
 * `it.wip_stock >= it.required_qty` was always `undefined >= n` (false) and
 * `it.wip_stock || 0` always printed 0: every line read red and empty the
 * instant the panel had any rows to show at all, which is worse than the blank
 * panel it replaced. `transferred_qty` is real, is already on the payload, and
 * answers what the operator actually wants to know standing at the machine —
 * "has this been moved to me yet".
 */
// The "kiosk required-materials WIP line" block lived here until 2026-08-31. It
// pinned the panel that showed an operator each required item with its code, its
// name and how much of it had been transferred — including the fix that made that
// line read `transferred_qty` instead of the never-populated `wip_stock`. Anjan's
// requirement is that an operator sees no item and no quantity at all, so the
// panel is gone rather than corrected, and the tests that described it went with
// it. What replaced them is `operatorMaterialSecrecy.spec.js`, which asserts the
// absence — including the route this suite never covered, `wo_transfer_preview`,
// measured that day handing a Manufacturing User all 15 lines with quantities.
