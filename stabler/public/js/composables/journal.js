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
	const index = pickTarget(rows, editedIdx, rateOf);
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

function pickTarget(rows, editedIdx, rateOf = () => 1) {
	const usable = (r, i) => i !== editedIdx && !!r.account;
	// An existing auto-plug keeps its place, so the number updates where the
	// user already saw it instead of hopping to another line. (It keeps its
	// place even when it is foreign and a base line has since opened up:
	// moving it would leave the old amount standing on a line this function
	// no longer returns, which is a worse failure than the residual below.)
	const auto = rows.findIndex((r, i) => usable(r, i) && r._auto);
	if (auto !== -1) return auto;
	const empty = (r, i) => usable(r, i) && !Number(r.debit) && !Number(r.credit);
	// A base-currency line first. The residual is measured in base currency and
	// only a base line can hold it exactly: 1 234 567 so'm on a USD line at
	// 12 335 rounds to 100.09, which converts back to 1 234 610 — and the ~43
	// so'm left over cannot be typed away, because one US cent is 123 so'm.
	// That is a permanently disabled Save button on the most ordinary flow a
	// UZS-base company has.
	const base = rows.findIndex((r, i) => empty(r, i) && (rateOf(r) || 1) === 1);
	if (base !== -1) return base;
	const any = rows.findIndex(empty);
	return any === -1 ? null : any;
}

function round(n, digits) {
	const f = 10 ** digits;
	return Math.round(n * f) / f;
}

/**
 * Lines whose exchange rate should follow the posting date.
 *
 * The rate is asked for `as of` the posting date, but it was only ever asked
 * for when an account was picked — nothing watched the date. "New entry, pick
 * the USD account, then set the date to last month" booked last month's entry
 * at today's rate, and ERPNext keeps whatever rate the form sends, so the
 * mistake went to the ledger without a word.
 *
 * A rate the user corrected by hand is excluded: the bank's rate or the
 * contract's rate is a decision, and moving the date must not quietly undo it.
 */
export function ratesToRefresh(rows, isForeign) {
	return (Array.isArray(rows) ? rows : []).filter((r) => r && isForeign(r) && !r._rateTouched);
}

/**
 * The first posting date a journal entry may still use — or null for open.
 *
 * `get_backdating_status` reports two earliest-open dates, stock and
 * accounting, and the money-page banner takes the later of the two because it
 * speaks for every document type. A Journal Entry writes no stock ledger, and
 * the server's own `_assert_posting_date_open` checks `acc_frozen_upto` alone
 * for that reason.
 *
 * Taking the later date was merely imprecise while it only painted a banner.
 * It now shuts Save, and a tenant whose stock period is closed further forward
 * than their accounting period would be refused dates the ledger accepts
 * without complaint — the form saying no to what the server would have taken.
 *
 * `active` already folds in the exemption roles the server checks, so the
 * person whose job is correcting a closed period keeps their only tool.
 */
export function journalFreezeDate(backdating) {
	if (!backdating || !backdating.active) return null;
	return backdating.acc_earliest_date || null;
}

/**
 * Is this posting date inside the closed period?
 *
 * The warning band was computed and then ignored — Save never consulted it — so
 * the draft saved and the refusal turned up at Submit instead, in ERPNext's own
 * untranslated words, leaving a record that is in the list but not in the
 * ledger. Both ISO dates, and the band reads "frozen BEFORE {date}", so the
 * freeze date itself is an open day.
 */
export function isPostingFrozen(postingDate, freezeDate) {
	if (!postingDate || !freezeDate) return false;
	return postingDate < freezeDate;
}

/**
 * Cache key for the "Bal:" hint.
 *
 * The balance is asked for `as_of` the posting date but was cached under the
 * account name alone, so backdating an entry left the first date's figure on
 * screen labelled as the new one. A dated figure needs a dated key.
 */
export function balanceCacheKey(account, postingDate) {
	return `${account || ""}|${postingDate || ""}`;
}

/**
 * The largest base-currency imbalance that is still rounding rather than error.
 *
 * THE ONE SOURCE. Three gates used to decide "balanced" and none of them
 * agreed: this form said `Math.abs(diff) < 1` base unit, `_clean_je_rows` in
 * `api/money.py` said 1.0 for a multi-currency entry and 0.01 otherwise, and
 * the gate that actually decides whether the document saves is
 * `residual_tolerance()` in `stabler/api/_fx_residual.py` — the size of the
 * residual the `before_validate` FX hook will seal into Exchange Gain/Loss
 * before ERPNext gets to refuse it. The disagreement ran in both directions
 * depending on the tenant's base currency, so it produced false greens on one
 * and unreachable Save buttons on another.
 *
 * This is the JS mirror of `residual_tolerance()`. Each line can contribute one
 * smallest unit of rounding, plus a cushion; the smallest unit is the base
 * currency's, which is a whole so'm on UZS and a cent on USD.
 */
export function balanceTolerance(lineCount, baseFractionDigits = 2) {
	const unit = baseFractionDigits > 0 ? 10 ** -baseFractionDigits : 1;
	const n = Number.isInteger(lineCount) && lineCount > 0 ? lineCount : 0;
	const tol = unit * (n + 2);
	return baseFractionDigits > 0 ? round(tol, baseFractionDigits) : tol;
}

/**
 * Why an entry the form filled in for you still refuses to balance.
 *
 * When no base-currency line was open, the plug had to land on a foreign one,
 * and a foreign line cannot express a base residual exactly — it is rounded to
 * its own cents first. The leftover is arithmetic, not a mistake, but on screen
 * it is an unexplained red Δ over a number the user did not type and cannot
 * correct: one cent on a USD line at 12 335 moves 123 so'm, so no keystroke
 * lands on the figure.
 *
 * Returns `{ index, amount, currency, base, counterBase, residual }` — the raw
 * facts, for the caller to format in the user's language — or null when there
 * is nothing to explain.
 */
export function describePlugResidual(rows, { rateOf = () => 1, tolerance = 0 } = {}) {
	const posted = postableRows(rows);
	const residual = posted.reduce((s, r) => s + ((Number(r.debit) || 0) - (Number(r.credit) || 0)) * (rateOf(r) || 1), 0);
	if (Math.abs(residual) <= tolerance + 1e-9) return null;
	// Only a plug this form wrote, and only on a foreign line. An imbalance the
	// user typed is a different story and calling it rounding sends them
	// looking in the wrong place.
	const index = (Array.isArray(rows) ? rows : []).findIndex(
		(r) => r && r.account && r._auto && (Number(r.debit) || Number(r.credit)) && (rateOf(r) || 1) !== 1,
	);
	if (index === -1) return null;

	const row = rows[index];
	const amount = Number(row.debit) || Number(row.credit);
	let others = 0;
	rows.forEach((r, i) => {
		if (i === index || !r || !r.account) return;
		others += ((Number(r.debit) || 0) - (Number(r.credit) || 0)) * (rateOf(r) || 1);
	});
	return {
		index,
		amount,
		currency: row.account_currency || "",
		base: Math.abs(amount * (rateOf(row) || 1)),
		counterBase: Math.abs(others),
		residual,
	};
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
