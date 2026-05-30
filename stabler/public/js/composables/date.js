/**
 * Locale-independent date formatting for the Stabler SPA.
 *
 * Global rule: every date displays as dd.mm.yyyy and every datetime
 * displays as dd.mm.yyyy HH:mm — the same across all four app languages
 * (en, ru, uz, uzc).
 *
 * Implementation deliberately avoids `new Date()` — parsing ISO strings via
 * the Date constructor uses UTC midnight, which rolls dates back a day in
 * negative-offset timezones. String splitting is simpler and correct.
 *
 * DateInput component (per rule) lives separately for editable fields.
 * This helper is for read-only display in tables, cards, and print views.
 */

/**
 * Format an ISO date string or Date-like value as dd.mm.yyyy.
 * @param {string|null|undefined} value - ISO date "yyyy-mm-dd" (extra time part is ignored)
 * @returns {string} "dd.mm.yyyy" or "—" if value is empty/invalid
 */
export function formatDate(value) {
	if (value === null || value === undefined || value === "") return "—";
	const s = String(value).trim();
	// Accept "yyyy-mm-dd" or "yyyy-mm-dd HH:mm:ss[.ms]"
	const datePart = s.slice(0, 10);
	const parts = datePart.split("-");
	if (parts.length !== 3) return "—";
	const [yyyy, mm, dd] = parts;
	if (!yyyy || !mm || !dd) return "—";
	return `${dd}.${mm}.${yyyy}`;
}

/**
 * Format an ISO datetime string as dd.mm.yyyy HH:mm.
 * @param {string|null|undefined} value - ISO datetime "yyyy-mm-dd HH:mm:ss" or Unix timestamp string
 * @returns {string} "dd.mm.yyyy HH:mm" or "—" if value is empty/invalid
 */
export function formatDateTime(value) {
	if (value === null || value === undefined || value === "") return "—";
	const s = String(value).trim();

	// Handle Unix timestamps (numbers as strings, e.g. from Users.vue last_active)
	if (/^\d{10,13}$/.test(s)) {
		const ms = s.length === 13 ? Number(s) : Number(s) * 1000;
		const d = new Date(ms);
		if (isNaN(d.getTime())) return "—";
		const dd = String(d.getDate()).padStart(2, "0");
		const mm = String(d.getMonth() + 1).padStart(2, "0");
		const yyyy = d.getFullYear();
		const HH = String(d.getHours()).padStart(2, "0");
		const min = String(d.getMinutes()).padStart(2, "0");
		return `${dd}.${mm}.${yyyy} ${HH}:${min}`;
	}

	// ISO "yyyy-mm-dd HH:mm:ss[.ms]" or "yyyy-mm-ddTHH:mm:ss"
	const normalized = s.replace("T", " ");
	const [datePart, timePart = ""] = normalized.split(" ");
	const dateParts = datePart.split("-");
	if (dateParts.length !== 3) return "—";
	const [yyyy, mm, dd] = dateParts;
	if (!yyyy || !mm || !dd) return "—";
	const [HH = "00", min = "00"] = timePart.split(":");
	return `${dd}.${mm}.${yyyy} ${HH.padStart(2, "0")}:${min.padStart(2, "0")}`;
}

/**
 * Parse a user-typed dd.mm.yyyy string into an ISO yyyy-mm-dd string.
 * Returns "" if the input is incomplete or invalid.
 * @param {string} displayValue
 * @returns {string} "yyyy-mm-dd" or ""
 */
export function parseDateInput(displayValue) {
	if (!displayValue) return "";
	const s = String(displayValue).trim();
	// Accept dd.mm.yyyy (fully typed)
	if (!/^\d{2}\.\d{2}\.\d{4}$/.test(s)) return "";
	const [dd, mm, yyyy] = s.split(".");
	// Basic sanity — not a full calendar validator, backend/Frappe validates on submit
	if (Number(mm) < 1 || Number(mm) > 12) return "";
	if (Number(dd) < 1 || Number(dd) > 31) return "";
	return `${yyyy}-${mm}-${dd}`;
}
