import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { halfAssigned } from "../composables/workOrderRoles.js";

const here = dirname(fileURLToPath(import.meta.url));
const kiosk = readFileSync(
	resolve(here, "../pages/manufacturing/ManufacturingOperatorBoard.vue"),
	"utf8"
);
const list = readFileSync(resolve(here, "../pages/manufacturing/WorkOrders.vue"), "utf8");

/**
 * A Work Order with one operator role named and the other empty.
 *
 * The backend refuses to move material in that state, and the reason is not
 * tidiness: `list_work_orders` filters an operator's list by the assignee columns,
 * so the person nobody named cannot open the order at all. They never write off
 * their own materials, ERPNext's Manufacture entry sweeps every unconsumed line
 * onto whoever presses finish, and the packer's kilograms end up on the pourer's
 * document — the exact number the two-operator split exists to keep apart.
 *
 * The asymmetry these tests pin down is the load-bearing part. *Neither* role
 * filled is a legitimate state — a site not using the split — and treating it as
 * broken would grey out every legacy order and dead-button every shop floor on the
 * day this ships. So the rule is "exactly one", not "not both".
 */
describe("halfAssigned", () => {
	it("is true when only the pourer is named", () => {
		expect(halfAssigned({ operator: "a@x.uz", packaging_operator: "" })).toBe(true);
	});

	it("is true when only the packer is named", () => {
		// Symmetric on purpose: the packer is not the optional half of the pair.
		expect(halfAssigned({ operator: null, packaging_operator: "b@x.uz" })).toBe(true);
	});

	it("is false when both are named", () => {
		expect(halfAssigned({ operator: "a@x.uz", packaging_operator: "b@x.uz" })).toBe(false);
	});

	it("is false when neither is named", () => {
		// The whole reason this is a predicate rather than `!both`.
		expect(halfAssigned({ operator: null, packaging_operator: null })).toBe(false);
	});

	it("reads an empty string and a null as the same emptiness", () => {
		// assign_work_order_operator clears a role by writing "", a never-touched
		// column is null, and both mean nobody is holding the role.
		expect(halfAssigned({ operator: "a@x.uz", packaging_operator: null })).toBe(
			halfAssigned({ operator: "a@x.uz", packaging_operator: "" })
		);
	});

	it("does not throw on a row that has not loaded yet", () => {
		expect(halfAssigned(undefined)).toBe(false);
	});
});

/**
 * Both screens must ask the shared question rather than re-deriving it. The
 * backend guard is already a second expression of the same rule; a third and
 * fourth copy inside two components is how the rule starts answering differently
 * in the list and in the kiosk.
 */
describe("both manufacturing screens use the shared rule", () => {
	for (const [label, src] of [
		["kiosk", kiosk],
		["work order list", list],
	]) {
		it(`${label} imports halfAssigned instead of re-deriving it`, () => {
			expect(src).toContain('from "../../composables/workOrderRoles.js"');
			expect(src).not.toMatch(/const halfAssigned\s*=/);
		});
	}
});

/**
 * The kiosk Start button. Executing the real `:disabled` expression, not matching
 * on its text — a guard wired backwards contains the same identifiers.
 */
function startDisabled({ busy = "", row }) {
	const click = kiosk.indexOf('@click="start(r)"');
	expect(click, "no button bound to start(r)").toBeGreaterThan(-1);
	const marker = ':disabled="';
	const start = kiosk.lastIndexOf(marker, click);
	const bodyStart = start + marker.length;
	const expr = kiosk.slice(bodyStart, kiosk.indexOf('"', bodyStart));
	const fn = new Function("isBusy", "halfAssigned", "r", `return (${expr});`);
	return !!fn((name) => busy === name, halfAssigned, row);
}

describe("kiosk Start button", () => {
	it("is live on a fully assigned order", () => {
		expect(
			startDisabled({ row: { name: "WO-9", operator: "a@x.uz", packaging_operator: "b@x.uz" } })
		).toBe(false);
	});

	it("is live on an order that names neither operator", () => {
		// The legacy shape. Blocking it would stop work that was never half-anything.
		expect(startDisabled({ row: { name: "WO-9" } })).toBe(false);
	});

	it("is dead on a half-assigned order", () => {
		// The operator cannot fix this — the missing name is a manager's to fill in —
		// so the button goes quiet rather than sending them into a server error.
		expect(startDisabled({ row: { name: "WO-9", operator: "a@x.uz" } })).toBe(true);
	});

	it("is dead while a post for this order is in flight", () => {
		expect(
			startDisabled({
				busy: "WO-9",
				row: { name: "WO-9", operator: "a@x.uz", packaging_operator: "b@x.uz" },
			})
		).toBe(true);
	});
});

/**
 * D1 (P0), part 2. The Finish button used to carry no halfAssigned gate at all,
 * and `canFinish` counted "Not Started" as finishable — so a half-assigned order
 * that could never be legitimately Started (the Start button already refuses it)
 * could still be Finished directly, straight into the sweep Part 1's backend
 * guard now refuses server-side. Gating the button here is the difference between
 * that refusal being a dead end an operator hits by clicking around, versus one
 * they never see because the button was never live.
 */
function finishDisabled({ busy = "", row }) {
	const click = kiosk.indexOf('@click="openFinish(r)"');
	expect(click, "no button bound to openFinish(r)").toBeGreaterThan(-1);
	const marker = ':disabled="';
	const start = kiosk.lastIndexOf(marker, click);
	const bodyStart = start + marker.length;
	const expr = kiosk.slice(bodyStart, kiosk.indexOf('"', bodyStart));
	const fn = new Function("isBusy", "halfAssigned", "r", `return (${expr});`);
	return !!fn((name) => busy === name, halfAssigned, row);
}

describe("kiosk Finish button", () => {
	it("is live on a fully assigned order", () => {
		expect(
			finishDisabled({ row: { name: "WO-9", operator: "a@x.uz", packaging_operator: "b@x.uz" } })
		).toBe(false);
	});

	it("is live on an order that names neither operator", () => {
		expect(finishDisabled({ row: { name: "WO-9" } })).toBe(false);
	});

	it("is dead on a half-assigned order", () => {
		// The never-named role never wrote anything off. Finishing now would let
		// ERPNext sweep their material onto the document of whoever is clicking.
		expect(finishDisabled({ row: { name: "WO-9", operator: "a@x.uz" } })).toBe(true);
	});

	it("is dead while a post for this order is in flight", () => {
		expect(
			finishDisabled({
				busy: "WO-9",
				row: { name: "WO-9", operator: "a@x.uz", packaging_operator: "b@x.uz" },
			})
		).toBe(true);
	});
});

/**
 * `canFinish` decides whether the button is offered at all (`v-if`), separately
 * from whether it is clickable (`:disabled`, above). A Not-Started order has had
 * nothing transferred into WIP by either role — there is nothing yet to finish —
 * and it was also the status a half-assigned order was stuck in, since the Start
 * button already refuses it. Offering Finish there was a second, v-if-level route
 * to the same premature-finish gap the :disabled change above closes.
 */
function canFinishFor(row) {
	const m = kiosk.match(/const canFinish = \(r\) => ([^;]+);/);
	expect(m, "no canFinish definition found").toBeTruthy();
	const fn = new Function("r", `return (${m[1]});`);
	return !!fn(row);
}

describe("kiosk canFinish", () => {
	it("no longer offers Finish on a Not Started order", () => {
		expect(canFinishFor({ docstatus: 1, status: "Not Started" })).toBe(false);
	});

	it("still offers Finish once the order has actually progressed", () => {
		for (const status of [
			"In Process",
			"Stock Partially Reserved",
			"Material Transferred",
			"Submitted",
		]) {
			expect(canFinishFor({ docstatus: 1, status })).toBe(true);
		}
	});

	it("never offers Finish on an unsubmitted document regardless of status", () => {
		expect(canFinishFor({ docstatus: 0, status: "In Process" })).toBe(false);
	});
});
