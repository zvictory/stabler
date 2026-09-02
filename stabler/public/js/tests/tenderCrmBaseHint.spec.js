import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const crm = readFileSync(resolve(here, "../pages/tender/TenderCrm.vue"), "utf8");
const RULES = readFileSync(resolve(here, "../../../../.claude/rules/10-frontend.md"), "utf8");

/**
 * The base-currency companion line — .claude/rules/10-frontend.md's FOURTH
 * documented exception, added 2026-09-02 on Zafar's explicit instruction ("hem
 * usd veya başka currency hem uzs olarak gösterebilirsin, tıpkı COA'da
 * gösterdiğin gibi").
 *
 * The Chart of Accounts is the shape being copied — main line in the account's
 * own currency, `≈ <base>` underneath, and only when the two differ — but NOT
 * the mechanism: the COA's hint is a SECOND STORED ledger figure (`b.base`),
 * so it converts nothing and needs no exception. A CRM deal has no stored base
 * figure, so this line applies a rate, and the rule's conditions come with it:
 *
 *   - a live rate, never a literal;
 *   - stated ONCE on the page with the date it was read, never per row;
 *   - never a replacement for the transaction-currency figure;
 *   - nothing rendered at all when no rate is available.
 *
 * Each is one test below. The rate itself is the server's: crm_board reads
 * _cbu_rate_on_or_before, the same reader validate_exchange_rate measures every
 * real document against (tests/test_tender_crm_card_currency.py).
 *
 * DOM-less per vitest.config.mjs.
 */

/** Source of the helper named `name`, from its declaration to its closing brace. */
function fn(name) {
	const m = crm.match(new RegExp(`^(?:function ${name}\\(|const ${name} =)[\\s\\S]*?^\\}`, "m"));
	expect(m, `TenderCrm.vue has no top-level ${name}`).not.toBeNull();
	return m[0];
}

describe("the rule itself records the exception", () => {
	it("is written down, not just implemented", () => {
		// WHAT WOULD MAKE THIS FAIL: shipping the conversion without amending the
		// rule. 10-frontend.md forbids base-currency sub-lines and then names its
		// exceptions one by one, each with the argument for it. A fourth conversion
		// living only in a .vue file is how the ban stops meaning anything — the
		// next reader finds a screen that contradicts the rule and copies it.
		expect(RULES).toMatch(/Documented exception:\*\* the Tender CRM/);
	});
});

describe("a rate is stated once, with its date", () => {
	it("renders the rate outside the card and lane loops", () => {
		// WHAT WOULD MAKE THIS FAIL: a per-row rate hint. The rule says the rate is
		// stated "once — in the section head, with the timestamp it was read at —
		// and never per row", and the Sourcing workspace's own per-row hints were
		// removed rather than grandfathered. Thirteen lanes each repeating "1 USD =
		// 12 600 сўм" is noise that also invites the reader to think the rates differ.
		const strip = crm.slice(crm.indexOf("crm-rate-note"), crm.indexOf("</div>", crm.indexOf("crm-rate-note")));
		expect(strip, "no crm-rate-note region").not.toEqual("");
		expect(crm.match(/crm-rate-note/g)?.length, "the rate note appears more than once").toBeLessThanOrEqual(
			2,
		);
		const lane = crm.slice(crm.indexOf("crm-col-sum"), crm.indexOf("</div>", crm.indexOf("crm-col-sum")));
		expect(lane).not.toMatch(/rateOf|rates\[/);
	});

	it("says when the rate was read", () => {
		// WHAT WOULD MAKE THIS FAIL: printing the rate bare. A CBU rate is a rate as
		// of a DATE — _cbu_rate_on_or_before returns the latest row on or before
		// today, which on a weekend or a gap is several days old. A converted figure
		// whose age the reader cannot see is a figure they cannot check.
		expect(crm).toMatch(/formatDate\(/);
		const note = crm.slice(crm.indexOf("crm-rate-note"), crm.indexOf("</span>", crm.indexOf("crm-rate-note")));
		expect(note + crm.slice(crm.indexOf("rateNote"), crm.indexOf("rateNote") + 600)).toMatch(/\.date/);
	});
});

describe("nothing is rendered when there is no rate", () => {
	it("returns null rather than a number when the currency is unknown", () => {
		// WHAT WOULD MAKE THIS FAIL: a `|| 1` or a `|| 0` fallback in the converter.
		// 1 prints the foreign figure under the base symbol — precisely the defect
		// that opened this whole thread — and 0 prints "≈ 0,00 сўм" over a real
		// contract. Absent is the only honest third answer, and it is what the user
		// chose when asked.
		const src = fn("toBase");
		expect(src).toMatch(/return null/);
		expect(/\|\|\s*1\b/.test(src), "a `|| 1` rate fallback is back").toBe(false);
	});

	it("refuses a mixed total when any one of its currencies has no rate", () => {
		// WHAT WOULD MAKE THIS FAIL: skipping the unconvertible rows and summing the
		// rest. The reader would see a base total that silently omits a contract —
		// worse than no total, because it looks complete. All or nothing.
		const src = fn("baseTotal");
		expect(src).toMatch(/return null/);
	});

	it("guards every rendered companion on the converted value existing", () => {
		// WHAT WOULD MAKE THIS FAIL: rendering `≈ {{ toBase(...) }}` unguarded.
		// formatMoney(null) returns "—", so the screen would print "≈ —" in three
		// places rather than printing nothing.
		const hints = crm.match(/≈[^<]*/g) ?? [];
		expect(hints.length, "no ≈ companion is rendered at all").toBeGreaterThanOrEqual(2);
		for (const site of ["crm-base-hint"]) {
			expect(crm).toContain(site);
		}
		expect(crm).toMatch(/v-if="[^"]*baseTotal\(/);
	});
});

describe("the companion never replaces the transaction-currency figure", () => {
	it("keeps the per-currency lines beside it", () => {
		// WHAT WOULD MAKE THIS FAIL: swapping the lane header to a single converted
		// number. The rule is explicit — "never a replacement for the
		// transaction-currency total" — and the per-currency lines are the only
		// figures on this screen that are not derived from a rate.
		const lane = crm.slice(crm.indexOf("crm-col-sum"), crm.indexOf("</div>", crm.indexOf("crm-col-sum")));
		expect(lane).toMatch(/v-for="tot in laneTotals\(l\.id\)"/);
		expect(lane).toMatch(/formatMoney\(\s*tot\.total,\s*tot\.ccy/);
	});

	it("says nothing extra when the deal is already in the base currency", () => {
		// WHAT WOULD MAKE THIS FAIL: converting base to base. It is the same number
		// printed twice, which is the exact thing the COA's own comment warns
		// against, and it would double the height of every ordinary card on a board
		// whose deals are nearly all in so'm.
		expect(fn("toBase")).toMatch(/===\s*baseCurrency\.value/);
	});
});
