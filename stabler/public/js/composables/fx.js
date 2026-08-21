// Human-readable exchange-rate quoting.
//
// ERPNext stores a per-line rate as account_currency → company(base) currency,
// i.e. base amount = account amount × rate. For a UZS account in a USD-base book
// that rate is ~0.0000831, which is unreadable. Accountants quote the *strong*
// currency: "1 USD = 12 034 сўм". This helper always presents the rate in the
// direction whose multiplier is ≥ 1, regardless of which side is the base.

// Given the ERPNext rate (base per 1 account) + the two currency codes, return
// the readable quote { strong, weak, value } where value = N in "1 strong = N weak".
export function readableRate(rate, accountCcy, baseCcy) {
	const r = Number(rate) || 0;
	if (!accountCcy || !baseCcy || accountCcy === baseCcy) return null;
	if (r <= 0) return { strong: accountCcy, weak: baseCcy, value: 0 };
	// r = base per 1 account.
	if (r >= 1) return { strong: accountCcy, weak: baseCcy, value: r };
	return { strong: baseCcy, weak: accountCcy, value: 1 / r };
}

// Inverse: the user edits the readable value N (in "1 strong = N weak"); convert
// back to the ERPNext per-line rate (base per 1 account_currency).
export function toLineRate(value, strongCcy, accountCcy) {
	const v = Number(value) || 0;
	if (v <= 0) return 0;
	// If the account currency is the strong side: 1 account = v base → rate = v.
	// Otherwise base is strong: 1 base = v account → rate (base per account) = 1/v.
	return strongCcy === accountCcy ? v : 1 / v;
}

// One number in, both numbers out: what a foreign-currency payment leg shows on
// screen and what it puts on the wire. `quoted` is the value sitting in the rate
// input, read in the direction the LABEL states — "1 strongCcy = quoted weakCcy"
// — and `accountCcy` is the currency the leg is actually paid in.
//
// Returns the ERPNext per-line rate (base per 1 account unit, which is what
// `submit_expense_entry` multiplies the payment total by) and the base-currency
// amount to preview beside it. Both come from the same direction decision on
// purpose: the Expense form derived them separately, posting `1/quoted` while
// previewing `amount/quoted` under a label that asked for neither, so an
// operator who typed the rate the label requested posted a $100 expense as
// 0.0077 сўм — and the preview printed that as "0".
export function quotedLeg(quoted, strongCcy, accountCcy, amount = 0) {
	const lineRate = toLineRate(quoted, strongCcy, accountCcy);
	return { lineRate, baseAmount: (Number(amount) || 0) * lineRate };
}

// Pretty number for a rate value (no currency symbol). Big values get grouped,
// sub-1 values keep precision.
export function formatRate(value, language = "en") {
	const v = Number(value) || 0;
	const opts =
		v >= 100
			? { maximumFractionDigits: 2, useGrouping: true }
			: { maximumFractionDigits: 6, useGrouping: true };
	try {
		return new Intl.NumberFormat(language === "en" ? "en-US" : "ru-RU", opts).format(v);
	} catch {
		return String(v);
	}
}
