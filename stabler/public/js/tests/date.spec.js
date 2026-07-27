import { afterEach, describe, expect, it, vi } from "vitest";

import {
	daysAgoIso,
	formatDate,
	formatDateTime,
	parseDateInput,
	presetRange,
	startOfMonthIso,
	startOfYearIso,
	todayIso,
} from "../composables/date.js";

afterEach(() => {
	vi.useRealTimers();
});

// Fake time is pinned with a LOCAL constructor (year, monthIndex, day), not an
// ISO string: `new Date("2026-07-27")` is UTC midnight, which is 2026-07-26 in
// every negative-offset zone. That is the exact bug date.js was written to avoid,
// so the tests must not reintroduce it.
const freeze = (y, m, d) => vi.useFakeTimers({ now: new Date(y, m - 1, d, 12, 0, 0) });

describe("formatDate — dd.mm.yyyy in all five languages", () => {
	// The rule is that the format does NOT vary by language. There is no locale
	// parameter here by design; if one ever appears, this test is what should stop it.
	it("reorders an ISO date into dd.mm.yyyy", () => {
		expect(formatDate("2026-07-27")).toBe("27.07.2026");
	});

	it("drops the time part of a datetime", () => {
		expect(formatDate("2026-07-27 14:30:00")).toBe("27.07.2026");
		expect(formatDate("2026-01-05T00:00:00")).toBe("05.01.2026");
	});

	it("keeps the leading zeros — 05.01, never 5.1", () => {
		expect(formatDate("2026-01-05")).toBe("05.01.2026");
	});

	it.each([[null], [undefined], [""], ["2026"]])("renders %p as an em dash", (value) => {
		expect(formatDate(value)).toBe("—");
	});

	// Frappe's date-only fields come back as "0000-00-00" from some legacy rows.
	// It is a real (if ugly) value, so it formats rather than blowing up.
	it("does not throw on a zero date", () => {
		expect(formatDate("0000-00-00")).toBe("00.00.0000");
	});
});

describe("formatDateTime — dd.mm.yyyy HH:mm", () => {
	it("keeps hours and minutes, drops seconds", () => {
		expect(formatDateTime("2026-07-27 14:30:59")).toBe("27.07.2026 14:30");
	});

	it("accepts the T separator as well as a space", () => {
		expect(formatDateTime("2026-07-27T14:30:00")).toBe("27.07.2026 14:30");
	});

	// Frappe stores date-only fields as "yyyy-mm-dd 00:00:00". Printing "00:00"
	// next to a delivery date reads as midnight-the-deadline, not "no time given".
	it("suppresses an all-zero time instead of printing 00:00", () => {
		expect(formatDateTime("2026-07-27 00:00:00")).toBe("27.07.2026");
		expect(formatDateTime("2026-07-27")).toBe("27.07.2026");
	});

	it("keeps a real midnight-adjacent time", () => {
		expect(formatDateTime("2026-07-27 00:01:00")).toBe("27.07.2026 00:01");
	});

	// Users.vue feeds last_active straight in, and Frappe hands that back as a
	// unix timestamp in seconds on some paths and milliseconds on others. Both
	// must land on the same instant -- asserting equality rather than a literal
	// keeps this independent of the runner's timezone.
	it("reads 10-digit input as seconds and 13-digit as milliseconds", () => {
		const seconds = formatDateTime("1769500000");
		expect(seconds).toBe(formatDateTime("1769500000000"));
		expect(seconds).toMatch(/^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$/);
	});

	it.each([[null], [undefined], [""]])("renders %p as an em dash", (value) => {
		expect(formatDateTime(value)).toBe("—");
	});
});

describe("parseDateInput — what DateInput hands back to the model", () => {
	it("converts a fully typed dd.mm.yyyy into ISO", () => {
		expect(parseDateInput("27.07.2026")).toBe("2026-07-27");
	});

	it("trims surrounding whitespace", () => {
		expect(parseDateInput("  27.07.2026  ")).toBe("2026-07-27");
	});

	// Returning "" mid-typing is what keeps a half-entered date out of the
	// payload. Anything looser would send "2026-7-2" to the backend on keystroke 6.
	it.each([["2"], ["27.0"], ["27.07.20"], ["7.7.2026"], ["2026-07-27"], ["27/07/2026"]])(
		"refuses the incomplete or non-dd.mm.yyyy input %p",
		(value) => {
			expect(parseDateInput(value)).toBe("");
		}
	);

	it.each([["00.07.2026"], ["32.07.2026"], ["27.00.2026"], ["27.13.2026"]])(
		"refuses the out-of-range date %p",
		(value) => {
			expect(parseDateInput(value)).toBe("");
		}
	);

	it.each([[null], [undefined], [""]])("renders %p as an empty string", (value) => {
		expect(parseDateInput(value)).toBe("");
	});
});

describe("presetRange — the period filter every list page shares", () => {
	it("covers today, the month and the year from a mid-month day", () => {
		freeze(2026, 7, 27);
		expect(presetRange("today")).toEqual({ from: "2026-07-27", to: "2026-07-27" });
		expect(presetRange("mtd")).toEqual({ from: "2026-07-01", to: "2026-07-27" });
		expect(presetRange("this_month")).toEqual({ from: "2026-07-01", to: "2026-07-31" });
		expect(presetRange("ytd")).toEqual({ from: "2026-01-01", to: "2026-07-27" });
		expect(presetRange("this_year")).toEqual({ from: "2026-01-01", to: "2026-12-31" });
		expect(presetRange("last_year")).toEqual({ from: "2025-01-01", to: "2025-12-31" });
	});

	// mtd stops at today, this_month runs to the end of the month. A report that
	// confuses the two shows a full month of budget against three weeks of spend.
	it("ends mtd at today but this_month at the last day", () => {
		freeze(2026, 7, 27);
		expect(presetRange("mtd").to).toBe("2026-07-27");
		expect(presetRange("this_month").to).toBe("2026-07-31");
	});

	it("rolls last_month back across the year boundary", () => {
		freeze(2026, 1, 15);
		expect(presetRange("last_month")).toEqual({ from: "2025-12-01", to: "2025-12-31" });
	});

	it("gets February right in a leap year", () => {
		freeze(2024, 3, 10);
		expect(presetRange("last_month")).toEqual({ from: "2024-02-01", to: "2024-02-29" });
	});

	it("gets a 30-day month right", () => {
		freeze(2026, 7, 5);
		expect(presetRange("last_month")).toEqual({ from: "2026-06-01", to: "2026-06-30" });
	});

	// Empty strings, not undefined: the callers spread these into the query params,
	// and "no bound" has to serialise as an absent filter rather than "undefined".
	it.each([["all"], ["custom"], ["nonsense-key"]])("returns an open range for %p", (key) => {
		expect(presetRange(key)).toEqual({ from: "", to: "" });
	});
});

describe("ISO helpers — local calendar, never toISOString()", () => {
	// UTC+5 (Tashkent) is why these exist: at 02:00 local, toISOString() reports
	// yesterday, so "today" filters would silently miss the morning's documents.
	it("reads today from the local calendar", () => {
		freeze(2026, 7, 27);
		expect(todayIso()).toBe("2026-07-27");
		expect(startOfMonthIso()).toBe("2026-07-01");
		expect(startOfYearIso()).toBe("2026-01-01");
	});

	it("walks back across a month boundary", () => {
		freeze(2026, 7, 27);
		expect(daysAgoIso(30)).toBe("2026-06-27");
		expect(daysAgoIso(0)).toBe("2026-07-27");
	});
});
