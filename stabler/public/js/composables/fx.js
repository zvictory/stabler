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

// A price list is quoted in its own currency, and that currency is not
// necessarily the one the order is written in. Both Sales Order forms read
// `price_list_rate` off `stabler.api.sales.get_item_price` / `item_sales_meta`
// and put it in the line's rate field; the Classic form never read the
// `currency` that came back with it, so a price list quoted in so'm, used on
// an order denominated in dollars, wrote the so'm figure into the dollar rate
// field — a ~12 000× error, in the customer's favour, on every foreign-currency
// order that takes a price-list rate. Classic is the form six of eight tenants
// use; `enable_modern_sales_order` is off for every company on production.
//
// It lives here, whole, for the reason the two forms drifted apart in the first
// place: two copies of a currency conversion is how one of them ends up wrong
// and nobody notices. `make test-js` runs it — money math must not live only in
// a component, where nothing can assert it without a browser.
//
// Two refusals are deliberate, and both return the caller's fallback with
// `unconverted: true` rather than a number:
//
//   * No rate for the pair. There is no honest conversion, so none is made.
//     Writing the unconverted figure is the defect above; writing a figure
//     converted at a guessed rate is the same defect wearing a hat.
//   * No price-list currency. The earlier implementation defaulted it to
//     "UZS" — a hardcoded currency in money code, the class of thing that put
//     675 purchase invoices on msa at a rate that was not their own date's
//     rate. On a USD-base tenant that default divides a correct dollar price
//     by ~12 000. If we do not know what currency the number is quoted in, we
//     do not know what the number means.
//
// The caller decides what a refusal looks like on screen; both forms keep the
// line's existing rate and raise the "rate unavailable, prices not converted"
// banner, so the user enters the number themselves.

const round4 = (n) => Number(n.toFixed(4));
const ccy = (c) => (c ? String(c).trim().toUpperCase() : "");

/**
 * The rate to put in a sales order line, given what the price-list lookup
 * returned and what currency the order is written in.
 *
 * @param {?{price_list_rate: number, currency: ?string, unresolved: ?boolean}} priced
 *        the lookup response; `currency` describes `price_list_rate` and nothing else
 * @param {string} txnCurrency the order's own currency
 * @param {?{rate: ?number, from: string, to: string}} pairQuote
 *        the live rate the form holds, read as "1 `from` = `rate` × `to`" — the
 *        same direction ERPNext stores `conversion_rate` in
 * @param {number} fallback what to keep when no price applies or none can be converted
 * @returns {{rate: number, unconverted?: true}}
 */
export function priceListRateForOrder(priced, txnCurrency, pairQuote, fallback = 0) {
	const back = Number(fallback) || 0;
	const listed = Number(priced?.price_list_rate) || 0;
	// No price found is not a currency problem: fall back silently, as before.
	if (!priced || priced.unresolved || listed <= 0) return { rate: back };

	const from = ccy(priced.currency);
	const to = ccy(txnCurrency);
	if (!from || !to) return { rate: back, unconverted: true };
	if (from === to) return { rate: round4(listed) };

	const rate = Number(pairQuote?.rate) || 0;
	if (rate <= 0) return { rate: back, unconverted: true };

	// Direction comes from the pair's own labels, never from which number looks
	// bigger — a RUB-document/USD-book rate is ≈ 0.011 and reads backwards.
	const pairFrom = ccy(pairQuote.from);
	const pairTo = ccy(pairQuote.to);
	if (from === pairTo && to === pairFrom) return { rate: round4(listed / rate) };
	if (from === pairFrom && to === pairTo) return { rate: round4(listed * rate) };

	// A third currency: reaching it would mean chaining two rates through an
	// implied cross and inventing precision nobody quoted.
	return { rate: back, unconverted: true };
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
