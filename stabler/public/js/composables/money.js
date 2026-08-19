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
export const LOCALE_MAP = {
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

export function moneySeparators(language = "en") {
	const locale = LOCALE_MAP[language] || "en-US";
	const parts = new Intl.NumberFormat(locale, { useGrouping: true, minimumFractionDigits: 1 }).formatToParts(12345.6);
	const group = parts.find((p) => p.type === "group")?.value || ",";
	const decimal = parts.find((p) => p.type === "decimal")?.value || ".";
	return { group, decimal };
}

/**
 * Read a number out of what a human typed into a money field.
 *
 * The rule this replaced keyed the decimal separator off the UI language alone:
 * anything but `en` meant "a dot is a thousands separator", so it deleted every
 * dot unconditionally. A Mikas user on the Russian UI typing an opening balance
 * of 1500000.50 had 150000050 posted to the ledger. The numeric keypad's decimal
 * key emits ".", so on ru/uz/uzc/tr that was not an edge case — it was the only
 * way most people tried to type a decimal at all.
 *
 * So the separator is decided by the SHAPE of the input first, and only falls
 * back to the locale for the one shape that is genuinely ambiguous:
 *   - both separators present  -> the LAST one is the decimal (1.500.000,50)
 *   - one separator, repeated  -> grouping (1.500.000)
 *   - one separator + exactly 3 trailing digits -> ambiguous, ask the locale
 *     ("1.500" is 1500 to a Russian and 1.5 to an American; nothing but the
 *     locale can break that tie, and pretending otherwise is a coin flip)
 *   - anything else            -> the decimal point, whatever the language
 *
 * Returns a Number, or null when the field is blank or unreadable.
 */
export function parseMoneyInput(text, language = "en") {
	if (text === null || text === undefined) return null;
	const raw = String(text).trim();
	if (raw === "") return null;
	// \u00a0 and \u202f are what Intl.NumberFormat emits as the ru/uz/uzc
	// thousands separator (ICU has shipped both), so stripping them is how a
	// value this module just rendered survives a round trip back through the
	// input. Spelled as escapes, not literals: you cannot tell them apart from
	// a plain space by eye, and ESLint rightly refuses raw ones in source.
	const s = raw.replace(/[\s\u00a0\u202f']/g, "");

	const dots = (s.match(/\./g) || []).length;
	const commas = (s.match(/,/g) || []).length;
	let decimalSep = null;

	if (dots && commas) {
		decimalSep = s.lastIndexOf(".") > s.lastIndexOf(",") ? "." : ",";
	} else if (dots || commas) {
		const sep = dots ? "." : ",";
		const count = dots || commas;
		const idx = s.lastIndexOf(sep);
		const trailing = s.length - idx - 1;
		if (count > 1) {
			decimalSep = null; // repeated -> grouping; 1.500.000 is never 1.5
		} else if (trailing === 3 && /\d/.test(s.slice(0, idx))) {
			decimalSep = moneySeparators(language).decimal === sep ? sep : null;
		} else {
			decimalSep = sep;
		}
	}

	let cleaned;
	if (decimalSep === null) {
		cleaned = s.replace(/[.,]/g, "");
	} else {
		const grouping = decimalSep === "." ? "," : ".";
		cleaned = s.split(grouping).join("").replace(decimalSep, ".");
	}
	const n = Number(cleaned);
	return Number.isFinite(n) ? n : null;
}

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
