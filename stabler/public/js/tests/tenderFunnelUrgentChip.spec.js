import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const funnel = readFileSync(resolve(here, "../pages/tender/TenderFunnel.vue"), "utf8");
const api = readFileSync(resolve(here, "../../../api/tender.py"), "utf8");

/**
 * The urgent chip on the "Bid submitted" box said `<48h`. Nothing computes 48
 * hours.
 *
 * Measured 2026-09-02, server side, three functions deep:
 *
 *   submitted_urgent += 1   when   stage == "submitted" and urgent
 *   urgent            =     _deal_deadlines(deal, company, intake)["risk"] == "risk"
 *   ["risk"]          =     "risk" if ANY milestone has status "risk"
 *   _milestone        =     "risk" when NOT done and (date - today).days < 0
 *
 * So the chip counts submitted deals with at least one milestone whose date has
 * already passed and which is not yet done. Not a 48-hour warning: a deal three
 * months overdue is counted, a deal due tomorrow is not.
 *
 * The same falsehood sat in three places. Two were `rule:` lines — query syntax
 * the reader is told to check the numbers against — and two sibling branches
 * corrected one each, in different words. This third one is the only one of the
 * three that is TRANSLATED PROSE, so it was the one a Russian or Uzbek user
 * actually read, and neither branch touched it.
 *
 * DOM-less per vitest.config.mjs.
 */

/** Source of one top-level Python function, docstring stripped. */
function pyBody(name) {
	const m = new RegExp(`^def ${name}\\(`, "m").exec(api);
	expect(m, `api/tender.py has no ${name}`).not.toBeNull();
	const tail = api.slice(m.index);
	const nxt = /\n(?:@|def )/.exec(tail.slice(1));
	const body = nxt ? tail.slice(0, nxt.index + 1) : tail;
	// A docstring is prose, and prose is not an implementation. Asserting against
	// it is how a sibling branch's four money tests stayed green while the helper
	// under them was replaced with `return 0.0`.
	return body.replace(/"""[\s\S]*?"""/g, "");
}

describe("the urgent chip states the rule the server actually applies", () => {
	it("does not claim a 48-hour threshold in anything the reader reads as prose", () => {
		// WHAT WOULD MAKE THIS FAIL: `<48h` coming back in a t() string. The number
		// is not approximately right and not a rounding of the real rule — there is
		// no hour-based threshold in the computation at all, so a reader who trusts
		// it mis-sorts their day.
		//
		// The ban is every `48` in the file EXCEPT one still on a `rule:` line. That
		// exception is not indulgence: `rule:` at :117 carries the identical
		// falsehood, and `feat/prompt-15-pipeline-overview` has already corrected it
		// on its own branch as row F11. Correcting it here too would guarantee a
		// conflict on the line its review is actively judging, so it stays theirs.
		// Written as an allow-list rather than a count so it passes at zero — when
		// that branch lands, this test needs no edit.
		const offenders = funnel
			.split("\n")
			.map((line, i) => [i + 1, line])
			.filter(([, line]) => /\b48\s*h?\b/i.test(line))
			.filter(([, line]) => !/^\s*rule:/.test(line));
		expect(offenders, `48-hour claims outside a rule line: ${JSON.stringify(offenders)}`).toEqual(
			[]
		);
	});

	it("names the chip with a literal key so it reaches the catalogues", () => {
		// WHAT WOULD MAKE THIS FAIL: a computed key. The harvester scans for
		// literal t("…") only; a key it cannot see is a string that renders in
		// English in all four other languages, which is how thirteen colour names
		// went untranslated on the CRM board.
		const at = funnel.indexOf("submitted_urgent");
		expect(at, "the urgent chip has gone").toBeGreaterThan(-1);
		const chip = funnel.slice(at, funnel.indexOf("tone:", at));
		expect(chip).toMatch(/t\("\{count\} [^"]+"/);
	});

	it("puts nothing after the count that has to agree with it", () => {
		// WHAT WOULD MAKE THIS FAIL: `{count} deals overdue`, or any noun after the
		// number. English needs deal/deals, Russian needs three forms, and the i18n
		// layer has no plural support — `1 days over` shipped on a sibling branch
		// this same day for exactly this reason. An adjective carries no agreement
		// in any of the five, so the count may lead and nothing need follow it.
		const m = /t\("(\{count\} [^"]+)"/.exec(funnel.slice(funnel.indexOf("submitted_urgent")));
		expect(m, "no {count} chip key found").not.toBeNull();
		expect(m[1]).toBe("{count} overdue");
	});
});

describe("the server has not grown the threshold the chip used to claim", () => {
	it("still decides risk on a date already passed, not on hours remaining", () => {
		// WHAT WOULD MAKE THIS FAIL: someone adding a real 48h (or 2-day) rule to
		// _milestone. This test is the other direction of the same claim: if the
		// server ever DOES warn ahead of the date, the chip is wrong again — in the
		// opposite direction — and this is what says so. Without it, the pair of
		// facts is pinned in one direction only and the text silently goes stale
		// the way `<48h` did.
		const body = pyBody("_milestone");
		expect(body).toMatch(/elif days < 0:\s*\n\s*status = "risk"/);
		expect(/\b48\b/.test(body), "a 48-hour threshold has appeared in _milestone").toBe(false);
	});

	it("rolls the milestones up as any-of, which is why no list belongs in the words", () => {
		// WHAT WOULD MAKE THIS FAIL: the roll-up changing to worst-of-a-fixed-list,
		// or the chip's wording naming milestones. `_deal_deadlines` builds four
		// milestones and appends a FIFTH, `guarantee`, whenever the intake carries a
		// guarantee-return date — so any wording that enumerates them is incomplete
		// the day a sixth is added. That is not hypothetical: one of the two sibling
		// branches corrected its own copy of this rule to a four-name list that
		// already omits `guarantee`.
		const body = pyBody("_deal_deadlines");
		expect(body).toMatch(/if m\["status"\] == "risk":\s*\n\s*worst = "risk"/);
		expect(body).toMatch(/_milestone\("guarantee"/);
	});
});

describe("the replacement is translated everywhere before it ships", () => {
	it("carries the new key in all five catalogues, and not the old one", () => {
		// WHAT WOULD MAKE THIS FAIL: replacing the string and leaving the catalogues
		// alone — which would swap a translated falsehood for an untranslated truth
		// and make the screen WORSE for four of the five languages. The old key is
		// asserted gone so its five rows cannot sit there looking maintained.
		for (const lang of ["en", "ru", "uz", "uzc", "tr"]) {
			const raw = readFileSync(resolve(here, `../../../translations/${lang}.csv`), "utf8");
			const rows = new Map();
			for (const line of raw.split("\n")) {
				if (!line) continue;
				const m = /^(?:"((?:[^"]|"")*)"|([^,]*)),(.*)$/.exec(line);
				if (!m) continue;
				const key = m[1] !== undefined ? m[1].replaceAll('""', '"') : m[2];
				let val = m[3];
				if (val.startsWith('"') && val.endsWith('"')) val = val.slice(1, -1).replaceAll('""', '"');
				rows.set(key, val);
			}
			expect(rows.get("{count} overdue"), `${lang}.csv has no target for the new chip`).toBeTruthy();
			expect(rows.has("{count} deadline <48h"), `${lang}.csv still carries the old key`).toBe(false);
			expect(rows.get("{count} overdue")).toContain("{count}");
		}
	});
});
