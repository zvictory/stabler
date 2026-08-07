import { describe, expect, it } from "vitest";

import { buildAllocationPlan, rowCeiling } from "../composables/piAllocation.js";

// PI-AUG-26 as booked on msa, trimmed to the first three cuts: one category
// (BUFFALO COMPENSATED_5), 8 400 boxes in the pool, thirteen contract lines
// under it. The pool is what the server guard enforces; the lines are what the
// user picks from.
const group = (pool, rows) => ({ groupKey: "PI-AUG-26::BUFFALO COMPENSATED_5", pool, rows });
const row = (rowKey, ownRemaining, requested, picked = true) => ({ rowKey, ownRemaining, requested, picked });

describe("buildAllocationPlan", () => {
	it("gives every line its full request when the pool covers them all", () => {
		const plan = buildAllocationPlan([
			group(8400, [row("a", 1494, 1494), row("b", 1200, 1200), row("c", 216, 216)]),
		]);

		expect(plan.byRow).toEqual({ a: 1494, b: 1200, c: 216 });
		expect(plan.byGroup["PI-AUG-26::BUFFALO COMPENSATED_5"]).toEqual({ pool: 8400, allocated: 2910 });
	});

	it("never lets a group exceed its pool — later lines absorb the shortfall", () => {
		// 2 000 left in the pool, 2 910 requested. The first two lines fit, the
		// third gets what is left. Without this the picker would hand the user a
		// row set the server is going to refuse on save.
		const plan = buildAllocationPlan([group(2000, [row("a", 1494, 1494), row("b", 1200, 1200), row("c", 216, 216)])]);

		expect(plan.byRow).toEqual({ a: 1494, b: 506, c: 0 });
		expect(plan.byGroup["PI-AUG-26::BUFFALO COMPENSATED_5"].allocated).toBe(2000);
	});

	it("never lets a line exceed its own contract, even with pool to spare", () => {
		// 31 TENDERLOIN is contracted at 216 boxes. The pool has 8 400 free, but
		// this cut does not.
		const plan = buildAllocationPlan([group(8400, [row("c", 216, 9999)])]);

		expect(plan.byRow.c).toBe(216);
	});

	it("allocates nothing when the pool is already exhausted or over-shipped", () => {
		// remaining_boxes is signed and goes negative on over-shipped keys; the
		// caller floors it to 0 before handing it over, and 0 must allocate 0
		// rather than deepen the breach.
		expect(buildAllocationPlan([group(0, [row("a", 1494, 1494)])]).byRow).toEqual({ a: 0 });
	});

	it("does not let an unpicked line consume the pool", () => {
		// Unchecking a row must hand its boxes back to the rows below it, not
		// leave them reserved by a line that will never be pushed.
		const plan = buildAllocationPlan([group(2000, [row("a", 1494, 1494, false), row("b", 1200, 1200)])]);

		expect(plan.byRow).toEqual({ a: 0, b: 1200 });
		expect(plan.byGroup["PI-AUG-26::BUFFALO COMPENSATED_5"].allocated).toBe(1200);
	});

	it("floors a negative or unparseable request at zero without touching its neighbours", () => {
		const plan = buildAllocationPlan([group(8400, [row("a", 1494, -50), row("b", 1200, null), row("c", 216, 216)])]);

		expect(plan.byRow).toEqual({ a: 0, b: 0, c: 216 });
	});

	it("keeps each group inside its own pool", () => {
		// Two proformas in one picker: one bundle running out must not steal from
		// or be starved by the other.
		const plan = buildAllocationPlan([
			group(500, [row("a", 1494, 1494)]),
			{ groupKey: "PI-JUL-12::BUFFALO", pool: 300, rows: [row("z", 300, 300)] },
		]);

		expect(plan.byRow).toEqual({ a: 500, z: 300 });
		expect(plan.byGroup["PI-JUL-12::BUFFALO"].allocated).toBe(300);
	});

	it("is idempotent — planning the same input twice gives the same answer", () => {
		// The plan is read by the group header, the summary bar and the Apply
		// loop. If it drifted between reads the screen would promise one total
		// and push another.
		const groups = [group(2000, [row("a", 1494, 1494), row("b", 1200, 1200)])];

		expect(buildAllocationPlan(groups)).toEqual(buildAllocationPlan(groups));
		expect(groups[0].rows[1].requested).toBe(1200);
	});
});

describe("rowCeiling", () => {
	it("is the smaller of the line's own contract and what the other lines left in the pool", () => {
		const g = group(2000, [row("a", 1494, 1494), row("b", 1200, 1200)]);

		// a: contract 1494, pool 2000 with b holding nothing yet above it -> 1494
		expect(rowCeiling(g, "a")).toBe(1494);
		// b: contract 1200, but a already took 1494 of the 2000 -> 506
		expect(rowCeiling(g, "b")).toBe(506);
	});

	it("excludes the row's own current allocation, so a full box can still be retyped", () => {
		// If the ceiling counted the row itself, a line sitting at its maximum
		// would report a ceiling of 0 and the input could never be re-entered.
		const g = group(1494, [row("a", 1494, 1494)]);

		expect(rowCeiling(g, "a")).toBe(1494);
	});

	it("is zero for a line in an exhausted pool and for a line that is not in the group", () => {
		expect(rowCeiling(group(0, [row("a", 1494, 1494)]), "a")).toBe(0);
		expect(rowCeiling(group(8400, [row("a", 1494, 1494)]), "nope")).toBe(0);
	});
});
