/**
 * Journal entry balancing helpers.
 *
 * Pure logic only — `make test-js` reaches the composables layer and nothing
 * inside an SFC, and the rule below is the kind that has to be pinned by test
 * rather than by eye.
 */

/**
 * The line a journal entry can fill in for itself.
 *
 * Entering an opening balance used to mean typing the same figure twice, once
 * on each side, for every account. The first amount is a judgement call; the
 * one that squares it is arithmetic.
 *
 * Two rules keep this safe to run on every keystroke:
 *   - a value the user typed is never touched, so the form never fights its
 *     own operator;
 *   - a value THIS function wrote (`_auto`) is a derivation, not data, so it
 *     stays live and is recomputed in place as the other lines change.
 *
 * The residual is measured in the company's base currency (each line weighed
 * by its own rate) and handed back in the target line's currency, rounded to
 * that line's own precision, because that is the field the user is looking at.
 *
 * Returns `{ index, field, value }`, or null when there is nothing to fill.
 */
export function computeBalancePlug(rows, { editedIdx, rateOf, fractionDigitsOf = () => 2 } = {}) {
	if (!Array.isArray(rows) || rows.length < 2) return null;
	const index = pickTarget(rows, editedIdx);
	if (index === null) return null;

	// Deliberately excludes the target: including its own current value is what
	// would turn "recompute in place" into a feedback loop.
	let residual = 0;
	rows.forEach((r, i) => {
		if (i === index) return;
		residual += ((Number(r.debit) || 0) - (Number(r.credit) || 0)) * (rateOf(r) || 1);
	});
	if (!residual) return null;

	// Precision is the TARGET line's, not the company's: a UZS-base entry can
	// still plug a USD line, and rounding that one to whole dollars is wrong.
	const value = round(Math.abs(residual) / (rateOf(rows[index]) || 1), fractionDigitsOf(rows[index]));
	if (!value) return null;
	const field = residual > 0 ? "credit" : "debit";
	const other = field === "credit" ? "debit" : "credit";
	// Already says what we were going to write. Returning it anyway would emit
	// on every keystroke and leave the caller with no proof the loop settles.
	if (Number(rows[index][field]) === value && !Number(rows[index][other])) return null;
	return { index, field, value };
}

function pickTarget(rows, editedIdx) {
	const usable = (r, i) => i !== editedIdx && !!r.account;
	// An existing auto-plug keeps its place, so the number updates where the
	// user already saw it instead of hopping to another line.
	const auto = rows.findIndex((r, i) => usable(r, i) && r._auto);
	if (auto !== -1) return auto;
	const empty = rows.findIndex((r, i) => usable(r, i) && !Number(r.debit) && !Number(r.credit));
	return empty === -1 ? null : empty;
}

function round(n, digits) {
	const f = 10 ** digits;
	return Math.round(n * f) / f;
}
