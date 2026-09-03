/**
 * What ONE landed-charge line is worth in company currency, on the client.
 *
 * The mirror of `stabler/stabler/tender_landed_math.line_value`, which is the
 * server's single rule for the same question. This file exists so the client has
 * a single rule too: the quotation editor (`LandedChargesEditor.vue`) and the PO
 * landed editor (`PoControlBoard.vue`) each carried their own `convertedPreview`,
 * and they disagreed.
 *
 * ADR-605 second review, P2. The PO copy read only the rate:
 *
 *     if (!l.currency) return Number(l.amount) || 0;
 *     const rate = Number(l.fx_rate) || 0;
 *     if (rate <= 0) return null;
 *     return Math.round((Number(l.amount_original) || 0) * rate * 100) / 100;
 *
 * Pick USD on a line already holding 3 200 000 so'm, press the CBU button, and
 * `amount_original` is still empty while the rate is now good: that arithmetic
 * prints "= 0", the missing-rate warning stays hidden because the rate is not
 * missing, and the save stores a zero. A charge that reads as free makes a vendor
 * read as cheap, which is the failure the whole rule exists to prevent.
 *
 * `null` is the answer to "what is this worth" when the honest answer is "nobody
 * can say". Callers must count those, never add them as zero — a total that
 * silently shrinks is worse than one that admits it is short.
 */

/**
 * The company-currency value of a planned charge line, or `null` if it has none.
 *
 * Three cases, in the order they are decided:
 *   - no currency  → the figure is already company currency; a stray rate on such
 *                    a line is ignored rather than applied.
 *   - nothing on either side → an empty row the officer has only started, worth 0
 *                    and NOT flagged; flagging it parks a warning under every
 *                    half-typed line.
 *   - a named currency with no figure typed in it, or no usable rate → `null`.
 */
export function convertedPreview(line) {
	if (!line.currency) return Number(line.amount) || 0;
	const original = Number(line.amount_original) || 0;
	const stored = Number(line.amount) || 0;
	if (!original && !stored) return 0;
	// Nothing typed in the named currency while a company-currency figure sits in
	// `amount`: a half-finished currency switch. Valuing it at that figure would
	// relabel so'm as USD; valuing it at 0 is the first review's P0.
	const rate = Number(line.fx_rate) || 0;
	if (!original || rate <= 0) return null;
	return Math.round(original * rate * 100) / 100;
}

/**
 * Which of the two remedies an unvaluable line needs, so the message can name the
 * action rather than the fact. `""` when the line is fine. Both remedies end the
 * same way: or clear the currency.
 */
export function unvaluedReason(line) {
	if (convertedPreview(line) !== null) return "";
	return Number(line.amount_original) || 0 ? "rate" : "amount";
}

// Deliberately NOT shared: each editor's `priceLines`. They total the same way but
// disagree about what to exclude — the quotation editor skips recoverable VAT
// (IAS 2 §11), while a PO's VAT is handled by `customsCalc`/`vat_recoverable` on
// the customs line instead. Pulling them together would quietly change one of the
// two. What had to be one rule is what a line is WORTH, which is above.
