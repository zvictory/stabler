/* global process */
// The only spec here that leaves the process. eslint.config.mjs declares browser
// globals for the whole tree; widening it to node for one file would relax the
// rule everywhere instead.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// The kassa mini app is a standalone www page with an inline <script>, not a Vue
// module, so there is nothing to import. Rather than assert that the source
// *contains* some string — which passes just as happily when the arithmetic is
// wrong — the day-window helpers are lifted out and actually run.
const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(resolve(here, "../../../www/kassa.html"), "utf8");
// The window's size belongs to the module that runs the query. The page used to
// hold its own `7`, which is one number in two languages and free to drift: the
// arrows could reach further back than the endpoint was willing to return, and
// the extra days would come back empty and read as "nothing happened".
const store = readFileSync(resolve(here, "../../../integrations/kassa/shadow_store.py"), "utf8");

const lift = (name) => {
	const at = html.indexOf(`function ${name}(`);
	if (at < 0) throw new Error(`kassa.html no longer defines ${name}()`);
	// Brace-match from the signature so a later edit to the body cannot silently
	// truncate what the test runs.
	let depth = 0;
	let i = html.indexOf("{", at);
	for (; i < html.length; i += 1) {
		if (html[i] === "{") depth += 1;
		else if (html[i] === "}" && (depth -= 1) === 0) break;
	}
	return html.slice(at, i + 1);
};

const windowDays = Number(/^WINDOW_DAYS = (\d+)$/m.exec(store)?.[1]);
const NAMES = ["toIso", "shiftIso", "earliestIso", "clampIso"];
// One sandbox for all four: clampIso calls earliestIso calls shiftIso calls toIso,
// so lifting them separately would only prove they parse.
const { shiftIso, earliestIso, clampIso } = new Function(
	`var WINDOW_DAYS = ${windowDays};\n` +
		NAMES.map(lift).join("\n") +
		`\nreturn { ${NAMES.join(", ")} };`,
)();

describe("kassa mini app — the browsable day window", () => {
	it("declares a seven-day window, which is what the cashiers asked for", () => {
		expect(windowDays).toBe(7);
	});

	it("keeps the number in one language — the page carries none of its own", () => {
		expect(html).not.toMatch(/var WINDOW_DAYS = \d/);
		expect(html).toContain("summary.window_days");
	});

	it("steps to the calendar day before", () => {
		expect(shiftIso("2026-08-01", -1)).toBe("2026-07-31");
		expect(shiftIso("2026-08-19", -1)).toBe("2026-08-18");
	});

	it("steps by the calendar west of Greenwich too", () => {
		// `new Date("2026-08-01")` is UTC midnight, which is still 31 July in every
		// negative offset — so parsing the ISO string instead of building the date
		// from its parts skips a day there. It cannot be caught in-process: Node
		// reads TZ once at startup, and both this machine and the cashiers sit at
		// UTC+5, where the broken form happens to give the right answer. Asserting
		// it here without leaving the process would be a test that cannot fail.
		const probe = `${NAMES.map(lift).join("\n")}
			var WINDOW_DAYS = ${windowDays};
			process.stdout.write([
				shiftIso("2026-08-01", -1),
				shiftIso("2026-01-01", -1),
				clampIso("2026-08-13", "2026-08-19"),
			].join(","));`;
		const out = execFileSync(process.execPath, ["-e", probe], {
			env: { ...process.env, TZ: "America/New_York" },
			encoding: "utf8",
		});
		expect(out).toBe("2026-07-31,2025-12-31,2026-08-13");
	});

	it("crosses month and year boundaries", () => {
		expect(shiftIso("2026-03-01", -1)).toBe("2026-02-28");
		expect(shiftIso("2027-01-01", -1)).toBe("2026-12-31");
		expect(shiftIso("2026-12-31", 1)).toBe("2027-01-01");
	});

	it("handles a leap day, because 2028-03-01 back one is not the 28th", () => {
		expect(shiftIso("2028-03-01", -1)).toBe("2028-02-29");
	});

	it("reaches exactly seven distinct days, today included", () => {
		// Off by one here and the window is either six days — losing the day the
		// cashier most often wants, a week ago — or eight, showing a day the
		// buttons then refuse to leave.
		const today = "2026-08-19";
		const seen = new Set();
		let day = today;
		for (let i = 0; i < 20; i += 1) {
			seen.add(day);
			day = clampIso(shiftIso(day, -1), today);
		}
		expect(seen.size).toBe(windowDays);
		expect(earliestIso(today)).toBe("2026-08-13");
	});

	it("refuses the future — there is nothing recorded there yet", () => {
		expect(clampIso("2026-08-20", "2026-08-19")).toBe("2026-08-19");
	});

	it("floors at the oldest day in the window instead of running off the end", () => {
		expect(clampIso("2026-01-01", "2026-08-19")).toBe("2026-08-13");
	});

	it("leaves a day inside the window alone", () => {
		expect(clampIso("2026-08-15", "2026-08-19")).toBe("2026-08-15");
	});

	it("asks the server for the day being viewed, not always for today", () => {
		// The endpoint has always accepted a date; the page pinned it to today, so
		// the arrows would repaint the same day forever.
		expect(html).toContain("date: VIEW_DATE,");
		expect(html).not.toContain("date: toIso(new Date()),");
	});

	it("runs its balance column from the window's opening, not the day's", () => {
		// The ledger now spans the whole window. Started from `opening_balances`
		// — the balance at the start of the LAST day — every row but the final
		// one would be wrong, and the final one right, which is the hardest
		// version of this mistake to notice.
		expect(html).toContain("window_opening_balances");
	});
});
