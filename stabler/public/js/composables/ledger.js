// Compute running balance for GL entries returned by `stabler.api.money.gl_entries`.
//
// Entries are sorted DESC by posting_date. The closing balance corresponds to the
// state AFTER the newest entry. We walk backwards (oldest first) to derive the
// running balance per row, then return rows in original (DESC) order.
//
// Mirrors stable_app `lib/ledger-utils.ts` so the two apps stay consistent.

function num(v) {
	const n = Number(v);
	return Number.isFinite(n) ? n : 0;
}

export function computeRunning(entries, closingAcc, closingBase) {
	if (!Array.isArray(entries) || !entries.length) return [];

	let movAcc = 0;
	let movBase = 0;
	for (const e of entries) {
		movAcc += num(e.debit_in_account_currency) - num(e.credit_in_account_currency);
		movBase += num(e.debit) - num(e.credit);
	}

	let runAcc = num(closingAcc) - movAcc;
	let runBase = num(closingBase) - movBase;

	const oldestFirst = [...entries].reverse();
	const enriched = oldestFirst.map((e) => {
		runAcc += num(e.debit_in_account_currency) - num(e.credit_in_account_currency);
		runBase += num(e.debit) - num(e.credit);
		return {
			...e,
			running_balance: runAcc,
			running_balance_base: runBase,
		};
	});
	return enriched.reverse();
}
