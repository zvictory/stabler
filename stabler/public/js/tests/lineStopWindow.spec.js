import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/manufacturing/LineStops.vue"), "utf8");

/**
 * How one day and two clock times become the pair of stamps the server stores.
 *
 * The form asks the question the way a shift lead answers it — "today, 23:40 to
 * 00:10" — and not the way the column is shaped. That translation is the only
 * arithmetic on this screen, and it is worth pinning because both of its
 * failures are silent: a night-shift stop composed as `23:40 -> 00:10` on the
 * same day is rejected by the server as ending before it starts, and the
 * operator sees a refusal for a stop that really happened; while a stop
 * composed onto the wrong day lands in a window nobody is looking at.
 *
 * Orders on this floor are opened between 05:00 and 23:00 (anjan, 2026-08-28),
 * so the night shift is not hypothetical.
 *
 * Same constraint as finishSweepGuard.spec.js — @vue/test-utils is not a
 * devDependency, so the component is not mounted. The two functions are pulled
 * out of the shipped SFC and EXECUTED; a toContain() assertion passes just as
 * happily on a rollover wired the wrong way.
 */
function fnSource(name) {
	const start = src.indexOf(`function ${name}(`);
	expect(start, `${name}() is not in the shipped component`).toBeGreaterThan(-1);
	const end = src.indexOf("\n}", start);
	expect(end, `${name}(): unterminated body`).toBeGreaterThan(start);
	return src.slice(start, end + 2);
}

const stopWindow = new Function(
	`${fnSource("addDays")}\n${fnSource("stopWindow")}\nreturn stopWindow;`
)();

describe("an ordinary stop stays on its day", () => {
	it("composes both stamps from the day it was given", () => {
		expect(stopWindow("2026-08-28", "09:00", "09:35")).toEqual({
			from_time: "2026-08-28 09:00:00",
			to_time: "2026-08-28 09:35:00",
		});
	});

	it("adds the seconds the column expects", () => {
		expect(stopWindow("2026-08-28", "09:00", "09:35").from_time).toMatch(/:00$/);
	});
});

describe("a stop that runs past midnight lands on the next day", () => {
	it("rolls the end over", () => {
		expect(stopWindow("2026-08-28", "23:40", "00:10")).toEqual({
			from_time: "2026-08-28 23:40:00",
			to_time: "2026-08-29 00:10:00",
		});
	});

	it("rolls over the end of a month too", () => {
		// The date arithmetic goes through a real Date, so this is the case a
		// string-slicing version would get wrong on eleven days a year.
		expect(stopWindow("2026-08-31", "23:00", "01:00").to_time).toBe("2026-09-01 01:00:00");
	});

	it("rolls over the end of a year", () => {
		expect(stopWindow("2026-12-31", "22:30", "00:30").to_time).toBe("2027-01-01 00:30:00");
	});

	it("treats an identical pair as a rollover rather than a zero-length stop", () => {
		// Composed as a 24-hour stop, which the server refuses as a forgotten
		// timer. That refusal is the honest outcome: the operator meant something,
		// and it was not "a stop of no length".
		expect(stopWindow("2026-08-28", "09:00", "09:00").to_time).toBe("2026-08-29 09:00:00");
	});
});

describe("an incomplete form composes nothing", () => {
	it("returns null rather than a half-built pair", () => {
		// A pair with an empty half would be sent and refused by the server with
		// a message about times, when what is actually missing is a field.
		expect(stopWindow("", "09:00", "09:35")).toBeNull();
		expect(stopWindow("2026-08-28", "", "09:35")).toBeNull();
		expect(stopWindow("2026-08-28", "09:00", "")).toBeNull();
	});
});

describe("the screen states no figure it cannot measure", () => {
	it("shows minutes and a count, never a percentage of the shift", () => {
		// A "% of shift lost" needs a shift length nothing on this site records,
		// and a percentage is read as a measurement and staffed against.
		//
		// Asserted against the code with its comments stripped: an earlier version
		// of this test matched the prose in the component explaining why the
		// figure is absent, and failed on the very comment that documents it.
		const code = src.replace(/\/\/[^\n]*/g, "").replace(/<!--[\s\S]*?-->/g, "");
		for (const invented of ["percent", "ratio", "utilisation", "utilization", "oee"]) {
			expect(code.toLowerCase(), invented).not.toContain(invented);
		}
		expect(code).toContain("totalMinutes");
	});
});
