/**
 * Journal entry balancing helpers.
 *
 * Pure logic only — `make test-js` reaches the composables layer and nothing
 * inside an SFC, and the rule below is the kind that has to be pinned by test
 * rather than by eye.
 */

/**
 * The lines that will actually reach the ledger.
 *
 * A line with no account is dropped twice on the way to the server — by the
 * form's own submit filter and again by `_clean_je_rows` in `api/money.py` —
 * so an amount sitting on one is not part of the entry, however loudly it is
 * displayed. Totals, the balance badge and the auto-balance residual all read
 * the entry through here, because a figure the user can see and the server
 * never receives is exactly the figure that made the badge lie.
 */
export function postableRows(rows) {
	return (Array.isArray(rows) ? rows : []).filter((r) => r && r.account);
}

/** An amount stranded on a line with no account — money the entry is ignoring. */
export function isRowOrphaned(row) {
	if (!row || row.account) return false;
	return !!(Number(row.debit) || Number(row.credit));
}

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
 * Returns `{ index, field, value }`, or null when there is nothing to do. A
 * `value` of null means the plug on that line is void and must be cleared.
 */
export function computeBalancePlug(rows, { editedIdx, rateOf, fractionDigitsOf = () => 2 } = {}) {
	if (!Array.isArray(rows) || rows.length < 2) return null;
	const index = pickTarget(rows, editedIdx);
	if (index === null) return null;

	// Deliberately excludes the target: including its own current value is what
	// would turn "recompute in place" into a feedback loop. Lines with no
	// account are excluded too — see postableRows(); plugging against a figure
	// the server never receives writes a wrong number into a real account.
	let residual = 0;
	rows.forEach((r, i) => {
		if (i === index || !r.account) return;
		residual += ((Number(r.debit) || 0) - (Number(r.credit) || 0)) * (rateOf(r) || 1);
	});
	// Nothing left to balance. A plug this function wrote is a derivation, and a
	// derivation of nothing is not a number — leaving it standing is how a
	// deleted line used to leave its counter-amount on screen, indistinguishable
	// from something the user typed. `value: null` means "clear this line".
	if (!residual) {
		const held = Number(rows[index].debit) ? "debit" : Number(rows[index].credit) ? "credit" : null;
		if (!rows[index]._auto || !held) return null;
		return { index, field: held, value: null };
	}

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

// Fields the user owns. Everything else on a row — `party_name`, which the
// server sent for display, `account_currency`, which follows the account, and
// `_auto`, which marks a value this form derived — is not their work and must
// never be what stands between them and the Escape key.
const DRAFT_HEAD = ["posting_date", "voucher_type", "user_remark", "cheque_no", "cheque_date"];
const DRAFT_ROW = ["account", "party_type", "party"];

/**
 * The draft as a comparable string, taken the moment the edit pane opens.
 *
 * Amounts are normalised through Number(): MoneyInput empties a field to null
 * and the server sends 0, and a form that called those two different would
 * prompt a user who typed nothing.
 */
export function snapshotDraft(form) {
	const head = DRAFT_HEAD.map((k) => String(form?.[k] ?? ""));
	const rows = (form?.accounts || []).map((r) => [
		...DRAFT_ROW.map((k) => String(r?.[k] ?? "")),
		Number(r?.exchange_rate) || 0,
		Number(r?.debit) || 0,
		Number(r?.credit) || 0,
	]);
	return JSON.stringify([head, rows]);
}

/**
 * Has the user put work into this draft?
 *
 * No snapshot means no edit pane was ever opened, so there is nothing to lose
 * and Escape stays plain "go back".
 */
export function isDraftDirty(form, pristine) {
	if (typeof pristine !== "string") return false;
	return snapshotDraft(form) !== pristine;
}
