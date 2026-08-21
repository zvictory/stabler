/**
 * Locale-aware money formatting.
 * Mirrors the grouping rules from ~/.claude/rules/money-input.md:
 *   en  -> "20,820.00"
 *   ru  -> "20 820,00"
 *   uz / uzc -> "20 820,00"
 *   tr  -> "20.820,00"   (dot thousands, comma decimal — distinct from all above)
 *
 * Per-currency overrides:
 *   UZS -> native suffix `сўм`, e.g. "38 000 000,00 сўм". Two decimals,
 *          because that is what the LEDGER holds. This said 0 until
 *          2026-08-20, on the argument that the tiyin (1/100 сўм) left
 *          circulation in 1994 — true of the cash, false of the database.
 *          ERPNext takes precision from the site, not from ISO 4217
 *          (frappe/model/meta.py:905-917), and every tenant runs with
 *          `currency_precision` unset and the global format "#,###.##",
 *          so UZS money fields report precision 2. Measured on mikas and
 *          anjan; 197 721 of anjan's 209 434 GL rows carry a fraction.
 *          Displaying a whole number over a stored 1 500 000,50 was not a
 *          simplification, it was a second number.
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
	UZS: { fractionDigits: 2, suffix: "сўм" },
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
 *   - the locale's own grouping mark + MORE than 3 digits -> grouping. No
 *     locale groups in fours, and this is the shape `groupMoneyWhileTyping`
 *     hands back mid-entry ("1,1080")
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
		const { group, decimal } = moneySeparators(language);
		if (count > 1) {
			decimalSep = null; // repeated -> grouping; 1.500.000 is never 1.5
		} else if (trailing === 3 && /\d/.test(s.slice(0, idx))) {
			decimalSep = decimal === sep ? sep : null;
		} else if (trailing > 3 && sep === group) {
			// The locale's OWN grouping mark with more than three digits behind
			// it is a half-finished group, never a decimal point — no locale
			// groups in fours. This is precisely what `groupMoneyWhileTyping`
			// feeds back on every keystroke past the first group boundary, so
			// typing 1108000 in en arrived here as "1,1080", "11,0800",
			// "110,8000" and left as 110.8 while the field still displayed
			// "1,108,000".
			//
			// Narrow on purpose: a separator that is NOT this locale's grouping
			// mark still falls through to the rescue below, so the ru numpad dot
			// and four-decimal unit prices keep working.
			decimalSep = null;
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

/**
 * Regroup what the user is typing, live, without forcing a decimal part.
 *
 * Lived inside `MoneyInput.vue` until it had to be read from a test. It belongs
 * here for a second reason: it is the exact inverse of `parseMoneyInput`, and
 * the two only work if they agree about which mark groups and which mark
 * separates the fraction. Keeping them in one file is what makes a disagreement
 * visible.
 *
 * Never pads decimals — they appear only once the user types the separator, so
 * the caret is not trapped behind a forced ".00".
 */
export function groupMoneyWhileTyping(text, language = "en", maxFractionDigits = 2) {
	const { group: gs, decimal: ds } = moneySeparators(language);
	const s = ds === "."
		? String(text).replace(/[^0-9.]/g, "")
		: String(text).replace(/[^0-9,]/g, "");
	const parts = s.split(ds);
	const intp = (parts[0] || "").replace(/^0+(?=\d)/, "");
	const grouped = intp.replace(/\B(?=(\d{3})+(?!\d))/g, gs);
	if (maxFractionDigits === 0) return grouped; // whole-unit currency: integer only
	if (parts.length > 1) return grouped + ds + parts.slice(1).join("").slice(0, maxFractionDigits);
	return grouped;
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
 * guard and the server-side guard agree — which means this one number has to
 * move whenever `ZERO_DECIMAL_CURRENCIES` does. UZS was half a so'm (0.5) until
 * 2026-08-20 on the theory that it has no fractional unit; the ledger records
 * kopecks, so 0.5 called forty kopecks of real difference "noise".
 */
/**
 * Fraction digits `currency` actually holds — 2 everywhere, including UZS,
 * because the ledger stores kopecks (see CURRENCY_OVERRIDES above). The
 * comment here read "0 for UZS" until 2026-08-21, six lines below the table
 * that says 2 — and three separate screens had each written their own copy of
 * the wrong answer rather than call this.
 *
 * The single source of truth for precision. Nothing outside this file decides
 * it; `make guards` enforces that.
 */
export function moneyFractionDigits(currency = "USD") {
	return CURRENCY_OVERRIDES[currency]?.fractionDigits ?? 2;
}

export function moneyEpsilon(currency = "USD") {
	const digits = moneyFractionDigits(currency);
	if (digits <= 0) return 0.5;
	return 0.5 * 10 ** -digits;
}

export function balanceState(value) {
	const n = Number(value || 0);
	const abs = Math.abs(Number.isFinite(n) ? n : 0);
	if (abs < 0.005) return { state: "settled", abs: 0 };
	return n > 0 ? { state: "owes", abs } : { state: "prepaid", abs };
}
