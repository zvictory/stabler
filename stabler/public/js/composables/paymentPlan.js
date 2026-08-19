// Pure logic behind the payment calendar. Everything here is deliberately free of
// Vue and of the API client so `make test-js` can hold it — the page itself is
// mostly wiring, and this is the part that is worth being wrong about.

import { t } from "./i18n.js";

// Must stay identical to DIRECTION_BY_KIND in the Payment Plan Entry controller.
// A kind the two layers disagree about lands on one side of the user's screen and
// the other side of the director's total; a test compares this list against the
// doctype JSON rather than trusting the two to be edited together.
export const KIND_OPTIONS = [
	{ value: "Customer Receipt", direction: "In", icon: "ti-arrow-down-left", label: () => t("Customer receipt") },
	{ value: "Vendor Payment", direction: "Out", icon: "ti-arrow-up-right", label: () => t("Vendor payment") },
	{ value: "Item Purchase", direction: "Out", icon: "ti-package", label: () => t("Item purchase") },
	{ value: "Expense", direction: "Out", icon: "ti-receipt-2", label: () => t("Expense") },
	{ value: "Salary", direction: "Out", icon: "ti-users", label: () => t("Salary") },
	{ value: "Tax", direction: "Out", icon: "ti-building-bank", label: () => t("Tax") },
	{ value: "Other Receipt", direction: "In", icon: "ti-plus", label: () => t("Other receipt") },
	{ value: "Other Payment", direction: "Out", icon: "ti-minus", label: () => t("Other payment") },
];

export const CONFIDENCE_OPTIONS = [
	{ value: "Committed", label: () => t("Committed — agreed, date is set") },
	{ value: "Expected", label: () => t("Expected — most likely") },
	{ value: "Tentative", label: () => t("Tentative — not discussed yet") },
];

export const REPEAT_OPTIONS = [
	{ value: "Once", count: 1, label: () => t("One time") },
	{ value: "Weekly", count: 4, label: () => t("Every week ×4") },
	{ value: "Monthly", count: 3, label: () => t("Every month ×3") },
	{ value: "Monthly", count: 6, label: () => t("Every month ×6") },
	{ value: "Monthly", count: 12, label: () => t("Every month ×12") },
];

// Which kinds show which extra field. Salary and Tax are deliberately blank:
// neither settles a commercial document, and offering a document picker there
// invites a link that means nothing.
export const KIND_EXTRA = {
	"Customer Receipt": "document",
	"Vendor Payment": "document",
	"Item Purchase": "item",
	Expense: "account",
	Salary: "",
	Tax: "",
	"Other Receipt": "",
	"Other Payment": "",
};

export function directionOf(kind) {
	return KIND_OPTIONS.find((k) => k.value === kind)?.direction || "Out";
}

const pad = (n) => String(n).padStart(2, "0");

/** First and last day of a "yyyy-mm", as ISO strings. */
export function monthBounds(month) {
	const [year, m] = String(month).split("-").map(Number);
	// Day 0 of the next month is the last day of this one — the only form of this
	// that survives February and leap years without a table.
	const last = new Date(year, m, 0).getDate();
	return { from: `${year}-${pad(m)}-01`, to: `${year}-${pad(m)}-${pad(last)}` };
}

export function currentMonth(today = new Date()) {
	return `${today.getFullYear()}-${pad(today.getMonth() + 1)}`;
}

/**
 * Plan rows as CalendarMonth chips.
 *
 * The chip state is the row's own meaning, not its status: a director scanning a
 * month needs to see money coming in apart from money going out before anything
 * else. Realized rows drop to the muted state because they are no longer a
 * question, and cancelled rows are not chips at all.
 */
export function calendarEvents(entries) {
	return (entries || [])
		.filter((row) => row.status !== "Cancelled")
		.map((row) => ({
			date: String(row.due_date || "").slice(0, 10),
			label: row.party_name || row.party || row.note || t(row.kind || ""),
			amount: row.amount,
			currency: row.currency,
			contractId: row.name,
			state: row.status === "Realized" ? "paid" : row.direction === "In" ? "inflow" : "outflow",
			entry: row,
		}))
		.filter((ev) => ev.date);
}

/**
 * Day buckets carried forward into a cumulative net.
 *
 * A day's own in-minus-out says nothing useful on its own; what a planner
 * actually asks a calendar is "by the 20th, am I still above water". Days the
 * server returned no bucket for are simply absent — the balance carries across
 * them unchanged, which is what a gap in a forecast means.
 */
export function runningBalance(days, opening = 0) {
	let balance = opening;
	return [...(days || [])]
		.sort((a, b) => String(a.due_date).localeCompare(String(b.due_date)))
		.map((day) => {
			const net = (day.inflow || 0) - (day.outflow || 0);
			balance += net;
			return { ...day, net, balance };
		});
}

/** The month's headline numbers, from the same day buckets the calendar draws. */
export function monthSummary(days) {
	const rows = days || [];
	const inflow = rows.reduce((sum, d) => sum + (d.inflow || 0), 0);
	const outflow = rows.reduce((sum, d) => sum + (d.outflow || 0), 0);
	const entries = rows.reduce((sum, d) => sum + (d.entries || 0), 0);
	// The heaviest outflow day is the one a planner moves things away from, so it
	// is worth naming rather than leaving them to scan the grid for it.
	const heaviest = rows.reduce((worst, d) => ((d.outflow || 0) > (worst?.outflow || 0) ? d : worst), null);
	return { inflow, outflow, net: inflow - outflow, entries, heaviest: heaviest?.due_date || null };
}
