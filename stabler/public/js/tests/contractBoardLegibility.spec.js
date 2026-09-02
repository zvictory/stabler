import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/sales/SalesOrderBoard.vue"), "utf8");

/**
 * Two things the payload said and the board did not — prompt 18's S7, rows C15
 * and C16.
 *
 * C15: `_stages()` has always returned `is_won` and `is_closed`. The header
 * rendered neither, so the column that means "won" and the column that means
 * "dead" looked exactly like the five ordinary ones between them. The server
 * half of this claim is tests/test_tender_stage_flags.py.
 *
 * C16: the fact that a contract came from a tender — on the TENDER module's own
 * board — was an icon in a `:title`, reachable only by hovering. The design
 * calls this the fourth instance of the same defect in the package, after
 * prompt 11's Red Channel, prompt 12's freight_booking_status and prompt 10's
 * evidence line.
 *
 * Both fixes are the same move: put the word on the screen. So both are tested
 * the same way — the text must be there, and the tooltip must not be the only
 * place it lives.
 *
 * DOM-less per vitest.config.mjs.
 */

/** The stage column's header, where the two flags are drawn. */
function header() {
	const at = src.indexOf('class="card-header py-2 px-2 d-flex');
	expect(at, "the stage header has moved").toBeGreaterThan(-1);
	return src.slice(at, src.indexOf("</div>", src.indexOf("ti-trash")));
}

/** The card's body, where the tender badge lives. */
function cardBody() {
	const at = src.indexOf('class="card-body p-2"', src.indexOf("data-so-card"));
	expect(at, "the card body has moved").toBeGreaterThan(-1);
	return src.slice(at, src.indexOf("customer_name", at));
}

describe("a terminal column says so", () => {
	it("draws both flags, in words", () => {
		// WHAT WOULD MAKE THIS FAIL: rendering neither, which is the defect, or
		// rendering them as a colour or an icon, which moves the fact somewhere a
		// reader has to already know how to look. "Paid" and "Closed" are the two
		// columns a manager scans for first; that they are terminal is the single
		// most consequential thing a stage header can say.
		const h = header();
		expect(h).toMatch(/v-if="s\.is_won"/);
		expect(h).toMatch(/v-if="s\.is_closed"/);
		expect(h).toMatch(/t\("Won"\)/);
		expect(h).toMatch(/t\("Closed"\)/);
	});

	it("draws them independently rather than as one choice", () => {
		// WHAT WOULD MAKE THIS FAIL: `v-else-if`. They are two separate Check
		// fields on the doctype and a manager can set both — a stage that is won
		// AND terminal is an ordinary thing to configure. A `v-else` would hide
		// one of the two facts and there would be no sign that it had.
		expect(/v-else-if="s\.is_closed"/.test(header()), "the closed flag is drawn as an alternative").toBe(
			false
		);
	});

	it("puts the two words through the translator", () => {
		// WHAT WOULD MAKE THIS FAIL: hardcoding English. Four languages are
		// offered; a header that reads "Won" to a Russian user is a word they
		// have to guess at, in the one place on the column that is not a number.
		// Whitespace-tolerant: prettier wraps the longer chip across three lines,
		// and a test that fails on line breaks measures the formatter, not the code.
		expect(header()).toMatch(/\{\{\s*t\("Won"\)\s*\}\}/);
		expect(header()).toMatch(/\{\{\s*t\("Closed"\)\s*\}\}/);
	});
});

describe("a contract from a tender says so without being hovered", () => {
	it("prints the word beside the flag icon", () => {
		// WHAT WOULD MAKE THIS FAIL: the icon-only badge coming back. On the
		// tender module's own board, which contract came from a tender is the
		// board's whole subject — and it was reachable only by hovering, which
		// on a touch device means not at all.
		const body = cardBody();
		expect(body).toMatch(/v-if="c\.deal"/);
		expect(body).toMatch(/t\("Tender"\)/);
	});

	it("stops hiding the meaning in a tooltip", () => {
		// WHAT WOULD MAKE THIS FAIL: keeping `:title="t('From tender')"` beside
		// the new text. Then the same fact is stated twice, in two wordings, and
		// the tooltip is the one that will drift — a title is not something
		// anyone re-reads when the label changes.
		expect(/:title="t\('From tender'\)"/.test(src), "the From tender tooltip is still there").toBe(false);
	});

	it("keeps the icon, which was never the problem", () => {
		// WHAT WOULD MAKE THIS FAIL: deleting the flag icon along with the
		// tooltip. An icon beside a word is a scanning aid; an icon INSTEAD of a
		// word is a puzzle. This fix is about adding the word, not removing the
		// picture.
		expect(cardBody()).toMatch(/ti-flag/);
	});
});
