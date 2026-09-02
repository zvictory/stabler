import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { oldestStamp } from "../composables/date.js";

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(resolve(here, "..", rel), "utf8");

/**
 * Every tender screen states when its numbers were read, from the SERVER's clock.
 * Acceptance rows P15 (14), F18 (15), W18 (16), M15 (17), C20 (18), and D12 (13),
 * which landed first and set the shape.
 *
 * Two of these screens auto-refresh, one has no refresh at all, and none of them
 * said how old their figures were. `generated_at` was already on the wire from
 * the operations desk and read nowhere in the SPA; the server half of this change
 * puts it on the other five payloads (stabler/tests/test_tender_generated_at.py).
 *
 * DOM-less, like sourcingWorkspaceConformance.spec.js — `vitest.config.mjs` runs
 * `environment: "node"`. The pure helper is imported and exercised for real; the
 * per-screen wiring is asserted against the source, because "this screen reads
 * generated_at rather than the browser clock" is a statement about the code.
 */

/** Files that own a fetch and must therefore state its freshness. */
const SCREENS = [
	{ prompt: 13, row: "D12", file: "pages/tender/OperationsDesk.vue", payload: "deskData" },
	{ prompt: 14, row: "P15", file: "pages/tender/DirectorBoard.vue", payload: "data" },
	{ prompt: 15, row: "F18", file: "pages/tender/TenderOverview.vue", payload: "flow" },
	{ prompt: 16, row: "W18", file: "pages/tender/TenderFlow.vue", payload: "data" },
	{ prompt: 17, row: "M15", file: "pages/tender/MyTenders.vue", payload: "data" },
	{ prompt: 18, row: "C20", file: "pages/sales/SalesOrderBoard.vue", payload: "board" },
];

/** Pages that draw a second component with its own fetch, and so have two clocks. */
const TWO_PAYLOAD_PAGES = [
	"pages/tender/DirectorBoard.vue",
	"pages/tender/TenderOverview.vue",
];

/** The `const lastReadAt = ...;` definition, as source text. */
function stampDefinition(file) {
	const src = read(file);
	const at = src.indexOf("const lastReadAt");
	expect(at, `${file} defines no lastReadAt — the screen cannot state its freshness`).toBeGreaterThan(-1);
	return src.slice(at, src.indexOf(";", at));
}

describe("oldestStamp — a page is only as fresh as its stalest block", () => {
	it("returns the earliest of several server stamps", () => {
		// WHAT WOULD MAKE THIS FAIL: returning the newest. Two blocks fetched
		// separately means one can be minutes older than the other; reporting the
		// newer one tells the reader the whole screen is fresher than half of it is,
		// which is the failure mode a freshness stamp exists to prevent.
		expect(oldestStamp(["2026-09-02 14:23:11", "2026-09-02 09:05:00"])).toBe("2026-09-02 09:05:00");
		expect(oldestStamp(["2026-09-02 09:05:00", "2026-09-02 14:23:11"])).toBe("2026-09-02 09:05:00");
	});

	it("ignores blocks that have not answered yet", () => {
		// WHAT WOULD MAKE THIS FAIL: treating a missing stamp as the oldest. Both
		// pages render their second block conditionally on a role, so on a reader
		// without that role the second stamp is permanently absent — and an empty
		// string sorts before every real date, which would blank the stamp forever.
		expect(oldestStamp([undefined, "2026-09-02 14:23:11"])).toBe("2026-09-02 14:23:11");
		expect(oldestStamp(["2026-09-02 14:23:11", ""])).toBe("2026-09-02 14:23:11");
		expect(oldestStamp([null, undefined])).toBe("");
		expect(oldestStamp([])).toBe("");
	});

	it("compares the stamps as the server writes them", () => {
		// WHAT WOULD MAKE THIS FAIL: parsing to Date first. frappe.utils.now() emits
		// "yyyy-mm-dd HH:MM:SS[.ffffff]", which Safari refuses as a Date argument
		// (space, not T) and returns Invalid Date for — the sort would then be by
		// NaN and the "oldest" would be whichever happened to be first.
		expect(oldestStamp(["2026-09-02 14:23:11.999999", "2026-09-02 14:23:11.000001"])).toBe(
			"2026-09-02 14:23:11.000001",
		);
	});
});

describe("every screen that owns a fetch states its freshness", () => {
	for (const { prompt, row, file, payload } of SCREENS) {
		describe(`${prompt} · ${row} · ${file.split("/").pop()}`, () => {
			it("derives the stamp from the payload's generated_at", () => {
				// WHAT WOULD MAKE THIS FAIL: the screen going back to no stamp at all
				// (four of these six had none) or stamping from its own state. Only
				// generated_at describes the DATA; everything else describes the view.
				const def = stampDefinition(file);
				expect(def).toMatch(/generated_at/);
				expect(def).toMatch(new RegExp(`\\b${payload}\\b`));
			});

			it("formats it through the shared composable", () => {
				// WHAT WOULD MAKE THIS FAIL: a local slice(11, 16). formatTime already
				// handles both shapes frappe emits and the empty case; a per-screen
				// copy is the defect .claude/rules/10-frontend.md names for dates.
				expect(stampDefinition(file)).toMatch(/formatTime\(/);
			});

			it("never falls back to the reader's own clock", () => {
				// WHAT WOULD MAKE THIS FAIL: `generated_at ?? new Date()` on a screen
				// mid-deploy against an older server. A browser-clock stamp is
				// indistinguishable from a real one and is wrong by the reader's
				// timezone — worse than the blank this renders instead.
				expect(stampDefinition(file)).not.toMatch(/\bDate\b/);
			});

			it("renders the stamp only when there is one", () => {
				// WHAT WOULD MAKE THIS FAIL: dropping the v-if. The label would then
				// stand alone over an empty value on every screen that has not loaded
				// yet, reading as "Last read (never)".
				// (boolean form, not toMatch: a failing toMatch on a whole .vue file
				// prints the entire file, and a failure nobody reads is not a gate.)
				expect(/v-if="lastReadAt"/.test(read(file)), `${file} renders the stamp unconditionally`).toBe(true);
			});
		});
	}
});

describe("a page with two independent fetches reports the older of them", () => {
	for (const file of TWO_PAYLOAD_PAGES) {
		it(`${file.split("/").pop()} folds the funnel's stamp in`, () => {
			// WHAT WOULD MAKE THIS FAIL: stamping only the page's own payload. Both
			// of these draw <TenderFunnel>, which fetches tender_funnel on its own
			// schedule — measured 2026-09-02, that is a second request with a second
			// generation time. A stamp that covers half the screen is a stamp that
			// says the other half is fresher than it is.
			const def = stampDefinition(file);
			expect(def).toMatch(/oldestStamp\(/);
			expect(def).toMatch(/funnelStamp/);
			expect(/@loaded="/.test(read(file)), `${file} never listens for the funnel's stamp`).toBe(true);
		});
	}

	it("TenderFunnel hands its own generation time up to whoever draws it", () => {
		// WHAT WOULD MAKE THIS FAIL: removing the emit. Both hosts would then read
		// funnelStamp as permanently undefined, oldestStamp would quietly ignore it,
		// and the two pages would silently go back to stamping half of themselves.
		const src = read("pages/tender/TenderFunnel.vue");
		expect(/defineEmits\(\[[^\]]*"loaded"/.test(src), 'TenderFunnel declares no "loaded" emit').toBe(true);
		expect(
			/emit\("loaded",[^)]*generated_at/.test(src),
			"TenderFunnel never emits its payload's generated_at",
		).toBe(true);
	});
});
