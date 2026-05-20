/**
 * Locale-aware money formatting.
 * Mirrors the grouping rules from ~/.claude/rules/money-input.md:
 *   en -> "20,820.00"
 *   ru -> "20 820,00"
 *   uz / uzc -> "20 820,00"
 *
 * MoneyInput component (per rule) lives separately for editable fields.
 * This helper is for read-only display in tables and cards.
 */
const LOCALE_MAP = {
	en: "en-US",
	ru: "ru-RU",
	uz: "ru-RU",
	uzc: "ru-RU",
};

export function formatMoney(value, currency = "USD", language = "en") {
	if (value === null || value === undefined || value === "") return "—";
	const n = Number(value);
	if (!Number.isFinite(n)) return "—";
	const locale = LOCALE_MAP[language] || "en-US";
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
