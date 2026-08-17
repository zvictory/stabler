/**
 * The cost-per-kg arithmetic printed above the Submit button on the landed-cost
 * review, extracted so the one number an accountant reads before posting to the
 * GL can be tested without mounting a page.
 *
 * THE DENOMINATOR IS THE WHOLE POINT. The card used to divide receipt money by
 * `grn.received_total_kg`, the PHYSICAL weight received across every condition.
 * Only Good-condition weight ever reaches a Purchase Receipt — `receipt_math`
 * returns 0 kg for anything else and the zero-qty line is then dropped — so the
 * numerator never contained the damaged kilos' money. 900 kg Good at USD 5.00
 * plus 100 kg Damaged booked 4,500 against a reported 1,000 kg and printed 4.50
 * as a "cost per kg" that nothing was ever bought at, understating the final
 * landed figure by the damaged fraction. The voucher itself spreads its charges
 * over the Good weight (the Landed Cost Items come from the receipts), so the
 * costed weight is also the weight the ledger uses.
 *
 * Numerator and denominator therefore both come off the SAME `purchase_receipts`
 * rows: `base_grand_total` and `costed_qty_kg` are shipped together per receipt
 * (stabler/api/imports.py) precisely so no caller can pair one receipt's money
 * with another weight.
 */

/** Sum a numeric field over receipt rows, treating anything unparseable as 0. */
function sumField(rows, field) {
	return (rows || []).reduce((acc, row) => acc + Number(row?.[field] || 0), 0);
}

/**
 * The per-kg card's figures, or `null` when there is nothing honest to print.
 *
 * `payload` is the `get_landed_cost_review` response. Returns `null` when no
 * receipt has booked money or weight yet: a card of zeroes and infinities is
 * worse than no card, and the caller hides the whole panel on `null`.
 *
 * `uncostedKg` is the received weight no receipt paid for — damaged or rejected.
 * It is reported rather than folded away so the reader can reconcile the divisor
 * against the GRN's own weight instead of suspecting the card of losing kilos.
 */
export function unitCostAnalysis(payload) {
	if (!payload) return null;

	const receipts = payload.purchase_receipts || [];

	// Company currency throughout. `grand_total` is the receipt's transaction
	// currency — USD for imports — while a voucher total is already a base amount,
	// so adding the raw pair would understate the receipt leg by the exchange rate.
	const prTotal = sumField(receipts, "base_grand_total");
	if (prTotal <= 0) return null;

	const costedKg = sumField(receipts, "costed_qty_kg");
	if (costedKg <= 0) return null;

	// Drafts count. The moment one is created its cost lines are stamped consumed,
	// so they leave `preview.total`; excluding the draft here would make the landed
	// figure collapse in the window between Create and Submit — exactly when someone
	// is reading it to decide whether to submit. Cancelled (2) is excluded:
	// cancelling releases the lines and they return to the preview.
	const existingLcvTotal = (payload.existing_lcvs || [])
		.filter((lc) => lc.docstatus === 0 || lc.docstatus === 1)
		.reduce((acc, lc) => acc + Number(lc.total || 0), 0);
	const nextLcvTotal = Number(payload.preview?.total || 0);
	const grandLandedTotal = prTotal + existingLcvTotal + nextLcvTotal;

	const receivedKg = Number(payload.grn?.received_total_kg || 0);
	const basePerKg = prTotal / costedKg;
	const landedPerKg = grandLandedTotal / costedKg;

	return {
		costedKg,
		receivedKg,
		uncostedKg: Math.max(receivedKg - costedKg, 0),
		prTotal,
		existingLcvTotal,
		nextLcvTotal,
		grandLandedTotal,
		basePerKg,
		landedPerKg,
		// Scale-invariant: the divisor cancels, so this stayed correct even while
		// the two figures above were wrong.
		landedIncreasePct: basePerKg > 0 ? ((landedPerKg - basePerKg) / basePerKg) * 100 : 0,
	};
}
