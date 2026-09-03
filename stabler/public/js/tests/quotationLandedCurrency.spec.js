import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

import { convertedPreview, unvaluedReason } from "../composables/landedLine.js";

const here = dirname(fileURLToPath(import.meta.url));
const editor = readFileSync(resolve(here, "../components/LandedChargesEditor.vue"), "utf8");
const workspace = readFileSync(resolve(here, "../pages/tender/SourcingWorkspace.vue"), "utf8");
const board = readFileSync(resolve(here, "../pages/tender/PoControlBoard.vue"), "utf8");

/**
 * ADR-605 — one landed-charge number, one currency label.
 *
 * The defect: `get_quotation_landed` adds the charge total to `base_grand_total`,
 * which is COMPANY currency, and the comparison table prints the delivered total
 * with `baseCcy`. The editor printed the very same stored numbers with the
 * QUOTATION's currency — `SourcingWorkspace.vue` passed `landedRow?.currency ||
 * 'USD'` into the modal — so an officer typing "1200" into a USD-labelled box put
 * 1 200 so'm into the sum that decides which vendor wins. Nothing on either screen
 * disagreed; the two screens simply never met.
 *
 * The fix is the shape a PO landed line already has: the totals are company
 * currency, a line may name its OWN currency, and the converted figure is shown
 * beside it. A line whose currency has no usable rate cannot be valued at all —
 * it must be visibly excluded, with a message that names the action, because
 * counting it at its raw number or as zero both make the vendor read as cheap.
 */
function braceMatched(src, from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(src, name) {
	const at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(src, braceStart);
}

/** Load one function plus whatever it calls, in one scope. */
const load = (src, name, ...deps) =>
	new Function(
		`${[...deps, name].map((n) => extractFunction(src, n)).join("\n")}\nreturn ${name};`,
	)();

// `convertedPreview` and `unvaluedReason` are IMPORTED above, from the module both
// editors now share (`composables/landedLine.js`). They used to be extracted from
// this component's own source, which is precisely how the PO board came to carry a
// second, weaker copy of the same rule.
//
// `priceLines` stays extracted: it is not shared, because the two editors disagree
// about what to exclude (this one skips recoverable VAT, the PO's does not). It
// calls `convertedPreview` by name, so the real one is injected here rather than a
// stub — a total computed with a different rule than the cells above it is the very
// split under test.
const priceLines = new Function(
	"convertedPreview",
	`${extractFunction(editor, "priceLines")}\nreturn priceLines;`,
)(convertedPreview);
const isBlankLine = load(editor, "isBlankLine");
// `fetchChargeRate` is stubbed rather than extracted: it is an async network call
// and nothing here is about the CBU fetch. What is under test is what
// `onChargeCurrency` does to the two amount fields on the way past.
const onChargeCurrency = new Function(
	`let fetched = null; function fetchChargeRate(l) { fetched = l; }\n${extractFunction(editor, "onChargeCurrency")}\nreturn onChargeCurrency;`,
)();

/** 1 200 USD of freight at 12 950 — the line the officer just typed. */
const FOREIGN = { currency: "USD", fx_rate: 12950, amount_original: 1200, amount: null, is_recoverable_vat: false };
/** Currency chosen, no rate yet: not valuable, and not zero either. */
const UNVALUED = { currency: "USD", fx_rate: 0, amount_original: 1200, amount: null, is_recoverable_vat: false };
/** Every line stored before ADR-605: a bare company-currency amount. */
const LEGACY = { currency: "", fx_rate: 0, amount_original: null, amount: 3200000, is_recoverable_vat: false };
/** Recoverable VAT: capitalized nowhere, IAS 2 §11. */
const VAT = { currency: "USD", fx_rate: 12950, amount_original: 100, amount: null, is_recoverable_vat: true, charge_type: "VAT" };

describe("the editor's footer adds up what its own rows are showing", () => {
	it("values a foreign line at the rate on that line, not at its typed figure", () => {
		// WHAT WOULD MAKE THIS FAIL: summing `amount` (or `amount_original`)
		// straight — 1 200 in a so'm total, the ADR-605 defect exactly.
		expect(convertedPreview(FOREIGN)).toBe(15540000);
		expect(priceLines([FOREIGN]).total).toBe(15540000);
	});

	it("passes a legacy company-currency line through untouched", () => {
		// WHAT WOULD MAKE THIS FAIL: routing a currency-less line through the
		// rate — every charge stored before ADR-605 would move.
		expect(convertedPreview(LEGACY)).toBe(3200000);
		expect(priceLines([LEGACY]).total).toBe(3200000);
	});

	it("refuses to value a currency with no rate, and counts it instead", () => {
		// WHAT WOULD MAKE THIS FAIL: returning 0 or 1200 from convertedPreview —
		// the total silently shrinks and this vendor looks cheapest.
		expect(convertedPreview(UNVALUED)).toBeNull();
		const { total, unvalued } = priceLines([FOREIGN, UNVALUED]);
		expect(total).toBe(15540000);
		expect(unvalued).toBe(1);
	});

	it("keeps recoverable VAT out of the capitalized total", () => {
		// WHAT WOULD MAKE THIS FAIL: the currency rule swallowing the IAS 2 §11
		// rule — a converted VAT line re-entering the landed total.
		expect(priceLines([FOREIGN, VAT]).total).toBe(15540000);
	});
});

describe("the editor and the comparison table label the same number the same way", () => {
	it("hands the editor the company currency the totals are actually in", () => {
		// WHAT WOULD MAKE THIS FAIL: passing the quotation's currency back
		// (`landedRow?.currency`) — the modal's totals get a label the sum they
		// feed does not use. This is the defect, in one attribute.
		expect(workspace).toMatch(/<LandedChargesEditor[\s\S]{0,400}?:currency="baseCcy"/);
		expect(workspace).not.toMatch(/:currency="landedRow\?\.currency/);
	});

	it("prints every editor total in that company currency, never in a line's own", () => {
		// WHAT WOULD MAKE THIS FAIL: a footer formatted with `line.currency`, so
		// three charges in three currencies stack under one sign.
		for (const total of ["baseTotal", "landedChargesTotal", "totalDeliveredCost"]) {
			expect(editor, `${total} must be labelled with the company currency`).toMatch(
				new RegExp(`formatMoney\\(\\s*${total}\\s*,\\s*props\\.currency`),
			);
		}
	});

	it("shows a foreign line's converted value beside the figure that was typed", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping the `= <converted>` cell, leaving
		// the officer to trust that a USD box reaches a so'm total correctly.
		expect(editor).toMatch(/convertedPreview\(line\)\s*!==\s*null/);
	});
});

describe("an unvalued line names the action, not just the fact", () => {
	it("tells the officer what to do about the missing rate", () => {
		// WHAT WOULD MAKE THIS FAIL: a bare "incomplete" badge. The officer has
		// two ways out — supply a rate, or drop the currency — and a message that
		// states neither leaves the line stuck and the total quietly short.
		const message = editor.match(/t\("No rate for \{ccy\}[^"]*"/);
		expect(message, "the editor must name the missing-rate remedy").not.toBeNull();
		expect(message[0]).toMatch(/enter a rate/i);
		expect(message[0]).toMatch(/clear the currency/i);
	});

	it("still saves, because the server stores the line and flags it", () => {
		// ADR-605 review, item 2. Blocking Save here contradicted the server's own
		// contract — store, exclude, flag — and made `has_unvalued_charges`, the
		// comparison badge, the winner-selector mark and the pre-win estimate's
		// "incomplete" note all unreachable through the product: nothing carrying
		// the flag could ever be saved. An estimate typed under deadline must be
		// saveable half-finished.
		// WHAT WOULD MAKE THIS FAIL: putting `unvaluedCount` back into :disabled.
		const button = editor.slice(editor.indexOf('class="btn btn-primary"'));
		expect(button.slice(0, 200)).not.toMatch(/unvaluedCount/);
		// The flag has to stay visible somewhere, or excluding the line is silent.
		expect(editor).toMatch(/v-if="unvaluedCount"/);
	});

	it("marks the winner selector option whose delivered total is short", () => {
		// ADR-605 review, item 4. This <select> is the control that AWARDS the lot.
		// The comparison table above it is where the officer reads; this is where
		// they act, and the figure printed beside each supplier's name here is
		// short by whatever that bid's unvalued lines hold.
		// WHAT WOULD MAKE THIS FAIL: flagging only in the table, so the last thing
		// seen before awarding is a confident number with nothing beside it.
		const option = workspace.slice(
			workspace.indexOf('v-model="awardForm.selected_quotation"'),
			workspace.indexOf('t("Technical evaluation result")'),
		);
		expect(option).toMatch(/r\.has_unvalued_charges/);
		expect(option).toMatch(/t\('incomplete'\)|t\("incomplete"\)/);
	});

	it("warns on the comparison row whose delivered total is short", () => {
		// WHAT WOULD MAKE THIS FAIL: the table trusting `has_landed_estimate`
		// alone. An estimate WAS typed, so the K3 completeness banner stays quiet
		// while the delivered total is missing whatever the unvalued lines hold.
		expect(workspace).toMatch(/r\.has_unvalued_charges/);
	});
});

describe("a currency picked with nothing typed in it is not worth zero", () => {
	/** The ADR-605 review's P0, reproduced as the officer meets it. */
	const HALF_SWITCHED = { currency: "USD", fx_rate: 12950, amount_original: null, amount: 3200000, is_recoverable_vat: false };

	it("refuses to value a line whose figure was never typed in its currency", () => {
		// The trap: `converted_amount(0, "USD", 12950)` is 0.0, not null — so the
		// line was valued at a bare zero, NOT flagged, and the vendor kept a
		// landed total missing a whole charge. WHAT WOULD MAKE THIS FAIL:
		// multiplying `amount_original` without first asking whether it exists.
		expect(convertedPreview(HALF_SWITCHED)).toBeNull();
		expect(priceLines([HALF_SWITCHED]).unvalued).toBe(1);
	});

	it("never re-labels the company-currency figure as the new currency", () => {
		// The opposite failure, and just as wrong: 3 200 000 so'm shown as
		// 3 200 000 USD, or multiplied by the rate. Both invent money.
		const value = convertedPreview(HALF_SWITCHED);
		expect(value).not.toBe(3200000);
		expect(value).not.toBe(3200000 * 12950);
	});

	it("does not seed the currency box from the company-currency amount", () => {
		// WHAT WOULD MAKE THIS FAIL: `line.amount_original = line.amount` on
		// currency change — which silently relabels the figure and hides the P0
		// behind a plausible-looking number.
		const line = { currency: "USD", fx_rate: 0, rate_date: "", fx_source: "", amount: 3200000, amount_original: null };
		onChargeCurrency(line);
		expect(line.amount_original).toBeNull();
	});

	it("names entering the amount, not just the rate, when that is what is missing", () => {
		// Two different broken states, two different remedies. Telling an officer
		// to "enter a rate" when the rate is already there is a dead end.
		expect(unvaluedReason(HALF_SWITCHED)).toBe("amount");
		expect(unvaluedReason({ currency: "USD", fx_rate: 0, amount_original: 1200, amount: 0 })).toBe("rate");
		expect(editor).toMatch(/t\("Enter the amount in \{ccy\} and a rate, or clear the currency"/);
	});

	it("treats a row that has only just been added as empty, not broken", () => {
		// WHAT WOULD MAKE THIS FAIL: flagging a blank line, which parks a
		// permanent warning under every estimate the moment a currency is picked.
		const blank = { currency: "USD", fx_rate: 0, amount_original: null, amount: 0 };
		expect(convertedPreview(blank)).toBe(0);
		expect(priceLines([blank]).unvalued).toBe(0);
	});
});

describe("clearing the currency keeps the number", () => {
	it("carries the typed figure into the company-currency box", () => {
		// "Clear the currency" is one of the two remedies the row prescribes, and
		// it means "this number is already in company currency". WHAT WOULD MAKE
		// THIS FAIL: nulling `amount_original` without carrying it across — which
		// destroyed the figure on any line created this session, so following the
		// screen's own advice lost the officer's work.
		const line = { currency: "", fx_rate: 12950, rate_date: "2026-09-03", fx_source: "x", amount: 0, amount_original: 1200 };
		onChargeCurrency(line);
		expect(line.amount).toBe(1200);
		expect(line.amount_original).toBeNull();
	});

	it("leaves an existing company-currency figure alone", () => {
		const line = { currency: "", fx_rate: 0, rate_date: "", fx_source: "", amount: 3200000, amount_original: null };
		onChargeCurrency(line);
		expect(line.amount).toBe(3200000);
	});
});

describe("the line's currency and its rate travel together to the server", () => {
	// ADR-606 review: the row -> wire mapping moved out of `save()` into the
	// named `savedChargeLine`, so that the round trip `loadedLine` -> row ->
	// `savedChargeLine` can be exercised. Same claim, read where it now lives.
	const save = extractFunction(editor, "savedChargeLine");

	it("sends the three quote fields with every line", () => {
		// WHAT WOULD MAKE THIS FAIL: dropping any one. Without `currency` the
		// server cannot convert; without `fx_rate` it cannot value; without
		// `rate_date` nobody can tell which day's quote produced the figure.
		for (const field of ["currency", "fx_rate", "rate_date"]) {
			expect(save, `savedChargeLine() drops ${field}`).toMatch(new RegExp(`${field}:`));
		}
	});

	it("sends the typed figure separately from the company-currency one", () => {
		// WHAT WOULD MAKE THIS FAIL: sending only `amount`. The server derives
		// `amount` from `amount_original × fx_rate`; collapsing them lets the
		// stored figure be converted a second time on the next save.
		expect(save).toMatch(/amount_original:/);
	});

	it("clears the rate when the currency changes", () => {
		// WHAT WOULD MAKE THIS FAIL: carrying a USD rate onto a EUR line — the
		// transfer form shipped exactly that (P0-TRF-1) and it inverted transfers.
		const onCurrency = extractFunction(editor, "onChargeCurrency");
		expect(onCurrency).toMatch(/fx_rate\s*=\s*0/);
		expect(onCurrency).toMatch(/rate_date\s*=\s*""/);
	});
});

describe("a line is dropped on save only when it is empty on every field", () => {
	// ADR-605 second review, P1. The old filter was
	// `Number(c.currency ? c.amount_original : c.amount) > 0 || c.description.trim()`.
	// It asks the CURRENCY box the moment a currency exists — so the one row shape
	// this whole feature is about, a legacy so'm line onto which USD has just been
	// picked, tested as blank. It was never sent, `update_quotation_landed` replaced
	// the stored array without it, and the charge was deleted with no message at
	// all. If it was the only line, `custom_landed_charges` went NULL and the
	// estimate the officer had been building simply ceased to exist.
	const halfSwitched = {
		currency: "USD",
		amount: 3_200_000,
		amount_original: null,
		description: "",
		charge_type: "Freight",
	};

	it("keeps the legacy line that has just been given a currency", () => {
		expect(isBlankLine(halfSwitched)).toBe(false);
	});

	it("keeps a line that carries only a currency, before anything is typed", () => {
		// The officer picks EUR first and types second. Dropping the row here means
		// the pick is undone by the save with no explanation.
		expect(isBlankLine({ currency: "EUR", amount: 0, amount_original: null, description: "" })).toBe(
			false,
		);
	});

	it("keeps a line that carries only a description", () => {
		expect(
			isBlankLine({ currency: "", amount: 0, amount_original: null, description: "port fees" }),
		).toBe(false);
	});

	it("keeps a company-currency line and a currency line with a typed figure", () => {
		expect(isBlankLine({ currency: "", amount: 250_000, amount_original: null, description: "" })).toBe(
			false,
		);
		expect(isBlankLine({ currency: "USD", amount: 0, amount_original: 1200, description: "" })).toBe(
			false,
		);
	});

	it("drops the untouched row the modal adds for you", () => {
		// `addChargeLine` pushes exactly this. Sending it would store a "General 0"
		// charge on every save — the one thing the filter is actually for.
		expect(
			isBlankLine({
				charge_type: "Freight",
				description: "",
				amount: 0,
				currency: "",
				fx_rate: 0,
				rate_date: "",
				amount_original: null,
			}),
		).toBe(true);
	});

	it("is what save() filters on", () => {
		// WHAT WOULD MAKE THIS FAIL: a second, inline predicate in save(). The
		// filter and the rule have to be the same thing, or fixing one leaves the
		// other deleting rows.
		const save = editor.slice(editor.indexOf("async function save()"));
		expect(save).toMatch(/\.filter\(\(c\) => !isBlankLine\(c\)\)/);
	});
});

describe("both landed editors value a line with one rule", () => {
	// ADR-605 second review, P2. `PoControlBoard.vue` carried its own
	// `convertedPreview` that read the rate and nothing else:
	//
	//     if (!l.currency) return Number(l.amount) || 0;
	//     const rate = Number(l.fx_rate) || 0;
	//     if (rate <= 0) return null;
	//     return Math.round((Number(l.amount_original) || 0) * rate * 100) / 100;
	//
	// Pick USD on a so'm line, press the CBU button, and the rate is GOOD while
	// `amount_original` is still empty: that arithmetic prints "= 0", the
	// missing-rate warning never fires because no rate is missing, and the save
	// stores nothing. Two copies of a money rule is two rules.

	it("neither component defines a convertedPreview of its own", () => {
		for (const [name, src] of [
			["LandedChargesEditor.vue", editor],
			["PoControlBoard.vue", board],
		]) {
			expect(src, `${name} still defines its own convertedPreview`).not.toMatch(
				/function convertedPreview\s*\(/,
			);
		}
	});

	it("both import it from the shared module", () => {
		expect(editor).toMatch(/import \{[^}]*convertedPreview[^}]*\} from "\.\.\/composables\/landedLine\.js"/);
		expect(board).toMatch(
			/import \{[^}]*convertedPreview[^}]*\} from "\.\.\/\.\.\/composables\/landedLine\.js"/,
		);
	});

	it("refuses the half-switched PO line the old board copy valued at zero", () => {
		// The exact row the board could reach: currency picked, rate fetched,
		// nothing typed in that currency yet, and the so'm figure still sitting
		// there. `null`, not 0 — a charge that reads as free makes a vendor read as
		// cheap.
		expect(convertedPreview({ currency: "USD", amount: 3_200_000, amount_original: 0, fx_rate: 12_950 })).toBe(
			null,
		);
	});

	it("still values the ordinary PO line the board has always shown", () => {
		expect(
			convertedPreview({ currency: "USD", amount: 0, amount_original: 1200, fx_rate: 12_800 }),
		).toBe(15_360_000);
		expect(convertedPreview({ currency: "", amount: 4_200_000, amount_original: null, fx_rate: 0 })).toBe(
			4_200_000,
		);
	});

	it("reaches the same verdict as line_value on every case line_value has", () => {
		// This used to be `expect(shared).toMatch(/line_value/)`, which the module's
		// own JSDoc satisfied — it asserted that the file MENTIONS the server rule,
		// not that it agrees with it, and would have stayed green through any change
		// to the arithmetic. The claim it was making is worth keeping, so it is made
		// properly: the five cases of `TestLineValueIsTheOneRule`
		// (test_tender_landed_math.py), each with the verdict that test asserts.
		// `null` here is the server's `unvalued=True`; a number is its company amount.
		const cases = [
			["no currency: the figure is already company currency", { currency: "", amount: 3200000 }, 3200000],
			[
				"a currency line is valued from what was typed IN that currency",
				{ currency: "USD", amount: 0, amount_original: 1200, fx_rate: 12950 },
				15540000,
			],
			[
				"an unusable rate leaves the line unvalued",
				{ currency: "USD", amount: 0, amount_original: 1200, fx_rate: 0 },
				null,
			],
			[
				"a currency with no typed figure is unvalued, not zero",
				{ currency: "USD", amount: 3200000, amount_original: 0, fx_rate: 12950 },
				null,
			],
			[
				"a currency line with nothing on either side is empty, not broken",
				{ currency: "USD", amount: 0, amount_original: 0, fx_rate: 0 },
				0,
			],
		];
		for (const [why, line, expected] of cases) {
			expect(convertedPreview(line), why).toBe(expected);
		}
	});

	it("never relabels the company-currency figure as the currency just picked", () => {
		// `line_value`'s other half: the opposite failure to valuing at 0. Asserted
		// as its own case because both are "wrong" and only one of them looks wrong.
		const half = { currency: "USD", amount: 3200000, amount_original: 0, fx_rate: 12950 };
		expect(convertedPreview(half)).not.toBe(3200000 * 12950);
		expect(convertedPreview(half)).not.toBe(3200000);
	});
});
