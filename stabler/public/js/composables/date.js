/**
 * Locale-independent date formatting for the Stabler SPA.
 *
 * Global rule: every date displays as dd.mm.yyyy and every datetime
 * displays as dd.mm.yyyy HH:mm — the same across all four app languages
 * (en, ru, uz, uzc, tr).
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
	const [HH = "0", min = "0", sec = "0"] = timePart.split(":");
	// Suppress time when absent or all-zero — date-only fields in Frappe store no time.
	if (!timePart || (parseInt(HH) === 0 && parseInt(min) === 0 && parseInt(sec) === 0)) {
		return `${dd}.${mm}.${yyyy}`;
	}
	return `${dd}.${mm}.${yyyy} ${HH.padStart(2, "0")}:${min.padStart(2, "0")}`;
}

/**
 * Format an ISO datetime string or time string as HH:mm.
 * @param {string|null|undefined} value - ISO datetime "yyyy-mm-dd HH:mm:ss" or time "HH:mm:ss"
 * @returns {string} "HH:mm" or "" if empty/invalid
 */
export function formatTime(value) {
	if (value === null || value === undefined || value === "") return "";
	const s = String(value).trim();
	if (s.includes(" ") || s.includes("T")) {
		const parts = s.split(/[ T]/);
		if (parts[1]) {
			const timeParts = parts[1].split(":");
			if (timeParts.length >= 2) {
				const [HH, min] = timeParts;
				return `${HH.padStart(2, "0")}:${min.padStart(2, "0")}`;
			}
		}
	} else if (s.includes(":")) {
		const timeParts = s.split(":");
		if (timeParts.length >= 2) {
			const [HH, min] = timeParts;
			return `${HH.padStart(2, "0")}:${min.padStart(2, "0")}`;
		}
	}
	return "";
}

// ---------------------------------------------------------------------------
// Date-range helpers for period presets (Month-to-date, Last month, etc.)
//
// All helpers use local-calendar methods (getFullYear/getMonth/getDate) to
// avoid the UTC-midnight shift that toISOString() can produce in UTC+N zones
// (e.g. Uzbekistan UTC+5). String splitting, not Date parsing, per the rule above.
// ---------------------------------------------------------------------------

/** Today as ISO yyyy-mm-dd in the local timezone. */
export function todayIso() {
	const d = new Date();
	const yyyy = d.getFullYear();
	const mm = String(d.getMonth() + 1).padStart(2, "0");
	const dd = String(d.getDate()).padStart(2, "0");
	return `${yyyy}-${mm}-${dd}`;
}

/** Any Date → local ISO yyyy-mm-dd (no UTC shift). Use instead of
 *  `date.toISOString().slice(0,10)`, which is a day behind in UTC+N zones. */
export function toLocalIso(date) {
	const d = date instanceof Date ? date : new Date(date);
	const yyyy = d.getFullYear();
	const mm = String(d.getMonth() + 1).padStart(2, "0");
	const dd = String(d.getDate()).padStart(2, "0");
	return `${yyyy}-${mm}-${dd}`;
}

/** N days ago as local ISO yyyy-mm-dd (no UTC shift). */
export function daysAgoIso(n) {
	const d = new Date(Date.now() - n * 86400000);
	const yyyy = d.getFullYear();
	const mm = String(d.getMonth() + 1).padStart(2, "0");
	const dd = String(d.getDate()).padStart(2, "0");
	return `${yyyy}-${mm}-${dd}`;
}

/** First day of the current calendar year, ISO yyyy-mm-dd. */
export function startOfYearIso() {
	return `${new Date().getFullYear()}-01-01`;
}

/** First day of the current calendar month, ISO yyyy-mm-dd. */
export function startOfMonthIso() {
	const d = new Date();
	const yyyy = d.getFullYear();
	const mm = String(d.getMonth() + 1).padStart(2, "0");
	return `${yyyy}-${mm}-01`;
}

/**
 * Returns the last calendar day of the month that contains `isoDate` (yyyy-mm-dd).
 * String-based: uses Date only for getDate() after moving to the next month's day 0.
 * @param {string} isoDate  "yyyy-mm-dd"
 * @returns {string} "yyyy-mm-dd"
 */
function endOfMonthIso(isoDate) {
	const [yyyy, mm] = isoDate.split("-").map(Number);
	// Day 0 of the next month = last day of current month
	const last = new Date(yyyy, mm, 0); // month is 0-indexed in constructor, so mm = next month
	const y = last.getFullYear();
	const mo = String(last.getMonth() + 1).padStart(2, "0");
	const d = String(last.getDate()).padStart(2, "0");
	return `${y}-${mo}-${d}`;
}

/**
 * Preset period keys and their { from, to } ISO date pairs.
 * `from: ""` / `to: ""` means "no bound" (open-ended range).
 *
 * Keys:
 *   "today"      – today only
 *   "mtd"        – month-to-date (1st of month → today)
 *   "this_month" – full current month (1st → last day)
 *   "last_month" – previous calendar month (1st → last day)
 *   "ytd"        – year-to-date (Jan 1 → today)
 *   "this_year"  – full current year (Jan 1 → Dec 31)
 *   "last_year"  – previous calendar year
 *   "all"        – no date bounds
 *   "custom"     – user-typed; returns { from: "", to: "" } as a no-op placeholder
 *
 * @param {string} key
 * @returns {{ from: string, to: string }}
 */
export function presetRange(key) {
	const today = todayIso();
	const d = new Date();
	const year = d.getFullYear();
	const month = d.getMonth() + 1; // 1-12

	switch (key) {
		case "today":
			return { from: today, to: today };

		case "mtd": {
			const mm = String(month).padStart(2, "0");
			return { from: `${year}-${mm}-01`, to: today };
		}

		case "this_month": {
			const mm = String(month).padStart(2, "0");
			const from = `${year}-${mm}-01`;
			return { from, to: endOfMonthIso(from) };
		}

		case "last_month": {
			// Go back one month, handling January → previous December
			const prevYear = month === 1 ? year - 1 : year;
			const prevMonth = month === 1 ? 12 : month - 1;
			const mm = String(prevMonth).padStart(2, "0");
			const from = `${prevYear}-${mm}-01`;
			return { from, to: endOfMonthIso(from) };
		}

		case "ytd":
			return { from: `${year}-01-01`, to: today };

		case "this_year":
			return { from: `${year}-01-01`, to: `${year}-12-31` };

		case "last_year":
			return { from: `${year - 1}-01-01`, to: `${year - 1}-12-31` };

		case "all":
			return { from: "", to: "" };

		case "custom":
		default:
			return { from: "", to: "" };
	}
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
