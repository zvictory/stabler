import { describe, expect, it } from "vitest";
import { unitCostAnalysis } from "../composables/landedCostPerKg.js";

/**
 * The per-kg card sits directly above the Submit button that posts a Landed Cost
 * Voucher to the General Ledger, so these figures are read as a decision, not as
 * decoration.
 *
 * Every case below turns on ONE invariant: the money and the weight must come
 * from the same receipts. A Purchase Receipt only ever books Good-condition
 * weight, so dividing by the GRN's physically-received weight — damaged kilos
 * included — charges the damaged goods' weight against the good goods' money and
 * silently understates the cost per kg.
 */

/** 900 kg Good at 5.00, on a truck that also delivered 100 kg Damaged. */
function damagedDelivery(overrides = {}) {
	return {
		grn: { received_total_kg: 1000 },
		purchase_receipts: [{ name: "PR-001", base_grand_total: 4500, costed_qty_kg: 900 }],
		existing_lcvs: [],
		preview: { total: 0 },
		...overrides,
	};
}

describe("cost per kg when part of the delivery arrived damaged", () => {
	it("divides by the weight the receipt paid for, not the weight the truck carried", () => {
		// The defect this module exists for: 4,500 / 1,000 = 4.50 was printed as a
		// cost per kg that nothing was ever bought at. Nobody paid 4.50 for anything
		// — the damaged 100 kg's money is not in the numerator at all, because
		// receipt_math.good_qty returns 0 kg for a non-Good condition and the
		// zero-qty line is then dropped before the receipt is written.
		const analysis = unitCostAnalysis(damagedDelivery());
		expect(analysis.basePerKg).toBeCloseTo(5.0, 10);
		expect(analysis.costedKg).toBe(900);
	});

	it("reports the received weight nobody paid for instead of quietly dropping it", () => {
		// An accountant comparing the card against the GRN would otherwise see 900
		// where the goods receipt says 1,000 and suspect the card of losing kilos.
		// Naming the 100 kg is what makes the smaller divisor readable as correct.
		const analysis = unitCostAnalysis(damagedDelivery());
		expect(analysis.receivedKg).toBe(1000);
		expect(analysis.uncostedKg).toBe(100);
	});

	it("reports that weight as uncosted and not as damaged, which it cannot know", () => {
		// Same arithmetic, no damage anywhere: a truck whose supplier could not be
		// resolved never gets a Purchase Receipt written, and the GRN still counts
		// its kilos. The figure is identical to the damaged case, so the module must
		// not name a cause — a fabricated "100 kg damaged" above a Submit button is
		// what starts a supplier claim. The label lives in the Vue and says
		// "not on a purchase receipt"; here the point is that only `uncostedKg`
		// exists, with no field claiming to be damaged weight.
		const analysis = unitCostAnalysis({
			grn: { received_total_kg: 1000 },
			purchase_receipts: [{ name: "PR-001", base_grand_total: 4500, costed_qty_kg: 900 }],
			existing_lcvs: [],
			preview: { total: 0 },
		});
		expect(analysis.uncostedKg).toBe(100);
		expect(Object.keys(analysis)).not.toContain("damagedKg");
	});

	it("does not raise a sub-line over a rounding residue", () => {
		// The GRN rounds its weight to 2 dp and the receipt side keeps 3, so the two
		// can disagree by a fraction of a gram on a delivery where nothing is
		// missing. "0.005 kg received, not on a purchase receipt" is noise that
		// reads as a discrepancy.
		const analysis = unitCostAnalysis({
			grn: { received_total_kg: 900.0 },
			purchase_receipts: [{ name: "PR-001", base_grand_total: 4500, costed_qty_kg: 899.995 }],
			existing_lcvs: [],
			preview: { total: 0 },
		});
		expect(analysis.uncostedKg).toBe(0);
	});

	it("carries the same divisor through to the landed figure, which is the one that posts", () => {
		// The voucher spreads its charges over the Landed Cost Items, and those come
		// from the receipts — the Good weight. A landed cost per kg computed on a
		// wider denominator does not describe the valuation the submit actually writes.
		const analysis = unitCostAnalysis(damagedDelivery({ preview: { total: 450 } }));
		expect(analysis.grandLandedTotal).toBe(4950);
		expect(analysis.landedPerKg).toBeCloseTo(5.5, 10);
	});

	it("aggregates the damaged case that is actually reachable: a later truck", () => {
		// One Truck Receipt line carries one condition, so the damaged kilos arrive
		// as a separate receipt — or as a second item on the same truck. Either way
		// a receipt exists whose costed weight is below what the GRN counted, and
		// summing per receipt is what keeps each total paired with its own weight.
		const analysis = unitCostAnalysis({
			grn: { received_total_kg: 1500 },
			purchase_receipts: [
				{ name: "PR-001", base_grand_total: 4500, costed_qty_kg: 900 },
				{ name: "PR-002", base_grand_total: 2000, costed_qty_kg: 400 },
			],
			existing_lcvs: [],
			preview: { total: 0 },
		});
		expect(analysis.costedKg).toBe(1300);
		expect(analysis.uncostedKg).toBe(200);
		expect(analysis.basePerKg).toBeCloseTo(5.0, 10);
	});

	it("leaves the increase percentage where it was, because the divisor cancels", () => {
		// Stated so a future reader does not "fix" this number too: it was the one
		// figure on the card that survived the wrong denominator, and the fix must
		// not move it. 10% on either divisor.
		const analysis = unitCostAnalysis(damagedDelivery({ preview: { total: 450 } }));
		expect(analysis.landedIncreasePct).toBeCloseTo(10.0, 10);
	});
});

describe("what the card refuses to print", () => {
	it("shows nothing when every kilo arrived damaged, rather than dividing by zero", () => {
		// No receipt was written, so there is no costed weight and no cost per kg
		// exists. Infinity above a Submit button is worse than an absent panel.
		const analysis = unitCostAnalysis({
			grn: { received_total_kg: 1000 },
			purchase_receipts: [{ name: "PR-001", base_grand_total: 4500, costed_qty_kg: 0 }],
			existing_lcvs: [],
			preview: { total: 0 },
		});
		expect(analysis).toBeNull();
	});

	it("shows nothing before any receipt has booked money", () => {
		expect(unitCostAnalysis({ grn: { received_total_kg: 1000 }, purchase_receipts: [] })).toBeNull();
	});
});

describe("which vouchers count toward the landed total", () => {
	it("counts a draft, because a draft has already emptied the preview it came from", () => {
		// Creating a draft stamps its cost lines consumed, so they leave
		// `preview.total`. Excluding the draft would collapse the landed figure in
		// the window between Create and Submit — exactly when it is being read to
		// decide whether to submit.
		const analysis = unitCostAnalysis(
			damagedDelivery({ existing_lcvs: [{ docstatus: 0, total: 900 }], preview: { total: 0 } })
		);
		expect(analysis.landedPerKg).toBeCloseTo(6.0, 10);
	});

	it("ignores a cancelled voucher, whose lines have gone back to the preview", () => {
		// Counting it would bill the same charge twice: once as the cancelled
		// voucher and once as the preview line it released.
		const analysis = unitCostAnalysis(
			damagedDelivery({ existing_lcvs: [{ docstatus: 2, total: 900 }], preview: { total: 900 } })
		);
		expect(analysis.grandLandedTotal).toBe(5400);
	});
});
