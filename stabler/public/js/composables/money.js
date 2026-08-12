/**
 * Locale-aware money formatting.
 * Mirrors the grouping rules from ~/.claude/rules/money-input.md:
 *   en  -> "20,820.00"
 *   ru  -> "20 820,00"
 *   uz / uzc -> "20 820,00"
 *   tr  -> "20.820,00"   (dot thousands, comma decimal — distinct from all above)
 *
 * Per-currency overrides:
 *   UZS -> integer (no decimals) + native suffix `сўм`,
 *          e.g. "38 000 000 сўм" — matches how Uzbek users actually
 *          write the currency. The tiyin (1/100 сўм) hasn't been in
 *          circulation since 1994, so fractional UZS is meaningless.
 *
 * MoneyInput component (per rule) lives separately for editable fields.
 * This helper is for read-only display in tables and cards.
 */
const LOCALE_MAP = {
	en: "en-US",
	ru: "ru-RU",
	uz: "ru-RU",
	uzc: "ru-RU",
	tr: "tr-TR",
};

// Per-currency display overrides. Anything not listed falls through to the
// default `Intl.NumberFormat` `style: "currency"` path.
const CURRENCY_OVERRIDES = {
	UZS: { fractionDigits: 0, suffix: "сўм" },
	// USDT is not an ISO 4217 currency so Intl.NumberFormat throws on it.
	// Format manually: 2 decimal places + "USDT" suffix.
	USDT: { fractionDigits: 2, suffix: "USDT" },
};

export function formatMoney(value, currency = "USD", language = "en") {
	if (value === null || value === undefined || value === "") return "—";
	const n = Number(value);
	if (!Number.isFinite(n)) return "—";
	const locale = LOCALE_MAP[language] || "en-US";
	const override = CURRENCY_OVERRIDES[currency];
	if (override) {
		// Decimal formatting + explicit suffix so we control the symbol exactly.
		const number = new Intl.NumberFormat(locale, {
			style: "decimal",
			minimumFractionDigits: override.fractionDigits,
			maximumFractionDigits: override.fractionDigits,
		}).format(n);
		return `${number} ${override.suffix}`;
	}
	try {
		return new Intl.NumberFormat(locale, {
			style: "currency",
			currency,
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		}).format(n);
	} catch {
		return n.toFixed(2);
	}
}

export function formatCompactMoney(value, currency = "USD", language = "en") {
	if (value === null || value === undefined || value === "") return "—";
	const n = Number(value);
	if (!Number.isFinite(n)) return "—";
	const locale = LOCALE_MAP[language] || "en-US";
	const override = CURRENCY_OVERRIDES[currency];
	if (override) {
		const number = new Intl.NumberFormat(locale, {
			style: "decimal",
			notation: "compact",
			maximumFractionDigits: 1,
		}).format(n);
		return `${number} ${override.suffix}`;
	}
	try {
		return new Intl.NumberFormat(locale, {
			style: "currency",
			currency,
			notation: "compact",
			maximumFractionDigits: 1,
		}).format(n);
	} catch {
		return n.toFixed(0);
	}
}

/**
 * Half the smallest representable unit of `currency` — the threshold below
 * which a difference is rounding noise, not a real gap.
 *
 * Mirrors `money_epsilon()` in `stabler/api/_money.py` so the client-side
 * guard and the server-side guard agree. UZS has no fractional unit in
 * circulation, so its epsilon is half a so'm (0.5), not half a cent —
 * a hardcoded 0.01 would reject a legitimate whole-so'm payment.
 */
export function moneyEpsilon(currency = "USD") {
	const digits = CURRENCY_OVERRIDES[currency]?.fractionDigits ?? 2;
	if (digits <= 0) return 0.5;
	return 0.5 * 10 ** -digits;
}

export function balanceState(value) {
	const n = Number(value || 0);
	const abs = Math.abs(Number.isFinite(n) ? n : 0);
	if (abs < 0.005) return { state: "settled", abs: 0 };
	return n > 0 ? { state: "owes", abs } : { state: "prepaid", abs };
}
