import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

import { convertedPreview } from "../composables/landedLine.js";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/PoControlBoard.vue"), "utf8");

/**
 * What the landed-charge editor's footer is allowed to add up.
 *
 * The bug this file exists for: a charge line quoted in a foreign currency
 * carries the user's figure in `amount_original`. The company-currency `amount`
 * is derived by the SERVER, at the one chokepoint both reads and writes pass
 * through (`stabler/api/tender.py`, "what stops the two from ever disagreeing").
 * So while the modal is open `amount` is null on a line just added and stale on
 * one just edited — and the footer summed exactly that field.
 *
 * The result was arithmetic the user could watch go wrong: a 1 200 USD freight
 * line printed `= 15 360 000` in its own cell, from `convertedPreview`, and
 * contributed ZERO to the "Landed total" printed directly beneath it. The stored
 * plan was correct the whole time — `saveEditor` sends `amount_original` and the
 * server re-derives — so this was never data corruption. It was worse placed
 * than that: right in the database, wrong on the screen where the vendor is
 * chosen.
 *
 * `null` from a preview means the line cannot be valued at all (a currency with
 * no usable rate). Those must be COUNTED, never silently added as zero — adding
 * them as zero is how a total quietly shrinks, which is the failure the module's
 * own comment names.
 */
function braceMatched(from) {
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(from, i + 1);
	}
	throw new Error("unterminated block");
}

function extractFunction(name) {
	const at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	return src.slice(at, braceStart) + braceMatched(braceStart);
}

const load = (name) => new Function(`${extractFunction(name)}\nreturn ${name};`)();

// `convertedPreview` is IMPORTED, not extracted: ADR-605's second review moved it
// into `composables/landedLine.js` because this component's own copy read the rate
// and nothing else, so a line whose currency was picked but whose figure was not
// yet typed printed "= 0" with a good rate and no warning. `actualPreview` stays
// local, and is NOT a currency rule at all: the actual is company currency at both
// of its sources — the row's own `MoneyInput` is bound `:currency="ccy"`, and
// `landed_actual_from_voucher` returns the linked document's BASE total.
const actualPreview = load("actualPreview");
const priceLines = load("priceLines");

/** 1 200 USD at 12 800 — the line the officer just added, not yet saved. */
const FRESH_FOREIGN = { currency: "USD", fx_rate: 12800, amount_original: 1200, amount: null, actual: null };
/** The same line after the server has valued it, then re-typed by the user. */
const EDITED_FOREIGN = { currency: "USD", fx_rate: 12800, amount_original: 2000, amount: 12800000, actual: null };
/** Currency chosen, no rate yet: not valuable, and not zero either. */
const UNVALUED = { currency: "USD", fx_rate: 0, amount_original: 1200, amount: null, actual: null };
/** An ordinary company-currency line. */
const HOME = { currency: "", fx_rate: 0, amount_original: null, amount: 3200000, actual: 3100000 };

/** USD picked on a line already holding the so'm figure; the CBU rate IS good. */
const HALF_SWITCHED = {
	currency: "USD",
	fx_rate: 12950,
	amount_original: 0,
	amount: 3200000,
	actual: null,
};

describe("a currency picked before the figure is typed", () => {
	// ADR-605 second review, P2, in the screen it was reachable from: pick USD at
	// the row's currency select, press the CBU button, and this component's own
	// `convertedPreview` returned `0 * 12950 = 0`. It printed "= 0", the missing-rate
	// warning stayed hidden because the rate was not missing, and `saveEditor` stored
	// a zero over the officer's 3 200 000. A charge that reads as free makes a vendor
	// read as cheap.

	it("cannot be valued, and says so instead of printing zero", () => {
		expect(convertedPreview(HALF_SWITCHED)).toBe(null);
	});

	it("is counted as unvalued rather than added to the footer as nothing", () => {
		const { total, unvalued } = priceLines([HOME, HALF_SWITCHED], convertedPreview);
		expect(total).toBe(3200000);
		expect(unvalued).toBe(1);
	});

	it("never relabels the company-currency figure as the new currency", () => {
		// The opposite failure, and the reason `null` is the answer: 3 200 000 so'm
		// multiplied by 12 950 is not a freight charge, it is a catastrophe.
		expect(convertedPreview(HALF_SWITCHED)).not.toBe(3200000 * 12950);
		expect(convertedPreview(HALF_SWITCHED)).not.toBe(3200000);
	});

	it("leaves the untouched currency row alone", () => {
		// Currency picked, nothing anywhere: an empty row, not a broken one. Flagging
		// it would park a permanent warning under every line just added.
		expect(
			convertedPreview({ currency: "USD", fx_rate: 0, amount_original: null, amount: null }),
		).toBe(0);
	});
});

describe("the landed-charge footer counts what the rows are showing", () => {
	it("counts a freshly added foreign line at the figure its own cell prints", () => {
		// The regression, stated as arithmetic: the cell renders convertedPreview
		// and the footer must reach the same number. Summing `amount` gives 0 here.
		expect(convertedPreview(FRESH_FOREIGN)).toBe(15360000);
		expect(priceLines([FRESH_FOREIGN], convertedPreview).total).toBe(15360000);
	});

	it("follows the user's edit rather than the server's stale conversion", () => {
		// `amount` still holds the value of the PREVIOUS figure. Believing it
		// would price the plan at what the officer typed a minute ago.
		expect(priceLines([EDITED_FOREIGN], convertedPreview).total).toBe(25600000);
	});

	it("counts a line it cannot value instead of adding it as zero", () => {
		const { total, unvalued } = priceLines([HOME, UNVALUED], convertedPreview);
		expect(total).toBe(3200000);
		expect(unvalued).toBe(1);
	});

	it("still reads company-currency lines from the derived field", () => {
		// A line with no currency of its own has nothing to convert; `amount` is
		// the figure, and the customs calculator writes it directly.
		expect(priceLines([HOME], convertedPreview).total).toBe(3200000);
		expect(priceLines([HOME], convertedPreview).unvalued).toBe(0);
	});

	it("treats an actual nobody has recorded yet as zero, not as unmeasurable", () => {
		// Planned and actual are not symmetrical. A planned line with a currency
		// and no rate is an INCOMPLETE PLAN and must be flagged. An actual of
		// nothing is not incomplete — it is the ordinary state of a charge that
		// has not been invoiced yet, and flagging it would put a permanent
		// warning under every open PO.
		expect(actualPreview(FRESH_FOREIGN)).toBe(0);
		expect(priceLines([FRESH_FOREIGN], actualPreview).unvalued).toBe(0);
	});

	it("counts an invoiced foreign line at the figure its own row prints", () => {
		// ADR-605 fourth review, P1. The row renders `l.actual` — the officer's box
		// and the GL pull both write company currency there — while the footer ran
		// the same line through a currency conversion keyed on `actual_original`,
		// which no control on this screen has ever written. So the row printed
		// 15 500 000 and the footer under it printed 0, with no warning, and the
		// plan-vs-actual colour read GREEN for a PO that is over plan.
		const invoiced = { ...FRESH_FOREIGN, actual: 15500000 };
		expect(actualPreview(invoiced)).toBe(15500000);
		expect(priceLines([invoiced], actualPreview).total).toBe(15500000);
		expect(priceLines([invoiced], actualPreview).unvalued).toBe(0);
	});

	it("does not withhold the actual because the PLAN cannot be valued", () => {
		// The invoice was paid whatever the plan's rate says. Zeroing it here would
		// understate what was spent on a line already flagged for its plan.
		const paid = { ...UNVALUED, actual: 15500000 };
		expect(actualPreview(paid)).toBe(15500000);
		expect(priceLines([paid], convertedPreview).unvalued).toBe(1);
	});
});

describe("the footer's totals are wired to those functions, not to the derived fields", () => {
	it("neither total reduces over the server-derived amount/actual", () => {
		// The guard on the wiring. The arithmetic above can be perfect while the
		// computeds still sum `l.amount` — that is exactly the shape the bug had.
		expect(src).not.toMatch(/reduce\(\(a, l\) => a \+ \(Number\(l\.amount\) \|\| 0\), 0\)/);
		expect(src).not.toMatch(/reduce\(\(a, l\) => a \+ \(Number\(l\.actual\) \|\| 0\), 0\)/);
		expect(src).toMatch(/priceLines\(editorLines\.value, convertedPreview\)/);
		expect(src).toMatch(/priceLines\(editorLines\.value, actualPreview\)/);
	});

	it("tells the user what the PLANNED total left out", () => {
		// A total that is merely CORRECT about what it could value, while silently
		// dropping what it could not, is the same lie in a quieter voice. Severity
		// is carried by three codes at once — colour, icon and word — not by colour.
		expect(src).toMatch(
			/v-if="editorPlanned\.unvalued" class="small text-danger"><i class="ti ti-alert-triangle/,
		);
	});

	it("makes no such claim about the ACTUAL half, because it has nothing to drop", () => {
		// ADR-605 fourth review, P1. The actual is company currency at both of its
		// sources, so `actualPreview` never refuses a line and that count was
		// structurally zero — a warning that could not fire, standing in for one
		// that was needed. The figures it was silently omitting were the ones the
		// conversion zeroed, and the cure was to stop converting.
		expect(src).not.toMatch(/editorActualPriced\.unvalued/);
		expect(src).not.toMatch(/Lines with no exchange rate, not in this total/);
	});
});

describe("what a read hands the modal is what the modal can hand back", () => {
	// ADR-605 third review, P0. Storing the RAW line closed the first hop; this is
	// the second. `po_landed_charges` returns the VALUED shape, where `amount` is the
	// DERIVED figure and is 0.0 on a line nothing can value. The modal used to bind
	// that 0.0 — so the officer's 3 200 000 so'm was off the screen, `isSendable` read
	// the same 0.0 and dropped the row, and `save_po_landed_charges` replaces the
	// whole array. The charge left the Purchase Order with no message at all, and the
	// cheapest-vendor badge can flip on the difference.
	//
	// `test_landed_charge_currency.py::TestThePoRoundTripIsAFixedPoint` pins the
	// server halves against the same contract; between them the loop is closed.
	const editorLine = load("editorLine");
	const savedLine = load("savedLine");
	const isSendable = load("isSendable");

	/** One half-switched line as `_parse_landed` returns it: USD picked, rate good,
	 *  nothing typed in USD, and the so'm figure preserved under `amount_given`. */
	const READ_HALF_SWITCHED = {
		type: "transport",
		label: "Freight",
		amount: 0,
		amount_given: 3200000,
		actual: 0,
		currency: "USD",
		fx_rate: 12950,
		rate_date: "2026-09-03",
		amount_original: 0,
		unvalued: true,
		vat_recoverable: true,
		vat_pct: 12,
	};

	it("reads the figure the officer typed, not the one the server derived", () => {
		expect(editorLine(READ_HALF_SWITCHED).amount).toBe(3200000);
	});

	it("keeps the row on the next save instead of deleting the charge", () => {
		expect(isSendable(editorLine(READ_HALF_SWITCHED))).toBe(true);
	});

	it("sends back exactly what was stored", () => {
		const sent = savedLine(editorLine(READ_HALF_SWITCHED));
		expect(sent.amount).toBe(3200000);
		expect(sent.amount_original).toBe(0);
		expect(sent.currency).toBe("USD");
		expect(sent.fx_rate).toBe(12950);
		expect(sent.rate_date).toBe("2026-09-03");
	});

	it("never sends a derived key back to the server", () => {
		// `unvalued` and `amount_given` are a verdict and a copy the read computed.
		// Echoing one into the payload puts it back in the column, where it can only
		// go stale. `actual_original` is here for the opposite reason: nothing can
		// write it, so sending it keeps a key alive that the server once divided by.
		const sent = savedLine(editorLine(READ_HALF_SWITCHED));
		for (const derived of ["unvalued", "amount_given", "actual_given", "actual_original"]) {
			expect(Object.hasOwn(sent, derived), `saveEditor echoes ${derived}`).toBe(false);
		}
	});

	it("hands an invoiced actual straight back, in company currency", () => {
		// The actual side of the same round trip. `_parse_landed` no longer converts
		// it, so what the modal reads into its box is what the server stored and what
		// the next save returns — the fixed point the planned side already has.
		const read = { ...READ_HALF_SWITCHED, amount_original: 1200, actual: 15500000, unvalued: false };
		const row = editorLine(read);
		expect(row.actual).toBe(15500000);
		expect(savedLine(row).actual).toBe(15500000);
	});

	it("leaves an ordinary converted line alone", () => {
		// Nothing was typed in company currency here, so `amount_given` is 0 and the
		// figure lives in `amount_original`. The row still has to survive the trip.
		const read = { ...READ_HALF_SWITCHED, amount: 15540000, amount_given: 0, amount_original: 1200, unvalued: false };
		const row = editorLine(read);
		expect(row.amount).toBe(0);
		expect(row.amount_original).toBe(1200);
		expect(isSendable(row)).toBe(true);
		expect(savedLine(row).amount_original).toBe(1200);
	});

	it("still drops a row the officer never touched", () => {
		// The filter is not a no-op: `addLine` pushes an empty row and sending it
		// would store a "transport 0" charge on every save.
		expect(isSendable(editorLine({ type: "transport" }))).toBe(false);
	});
});

describe("the modal names the remedy the line actually needs", () => {
	// ADR-605 third review, P2. Both strings on this screen asserted a missing rate,
	// and the shared rule refuses a half-switched line whose rate is perfectly good —
	// so the advice was reachable and wrong.

	it("asks for a rate only when the rate is what is missing", () => {
		expect(src).toMatch(/unvaluedReason\(l\) === 'rate'/);
		expect(src).toMatch(/No rate for \{ccy\} — enter a rate or clear the currency/);
	});

	it("asks for the amount when that is what is missing", () => {
		expect(src).toMatch(/Enter the amount in \{ccy\} and a rate, or clear the currency/);
		expect(src).not.toMatch(/t\("Enter an exchange rate"\)/);
	});

	it("uses the same two messages as the quotation editor", () => {
		// One vocabulary across both landed editors, for the same reason there is one
		// rule behind them: an officer who learns the remedy on one screen should not
		// have to learn it again on the other.
		const editor = readFileSync(resolve(here, "../components/LandedChargesEditor.vue"), "utf8");
		for (const key of [
			"No rate for {ccy} — enter a rate or clear the currency",
			"Enter the amount in {ccy} and a rate, or clear the currency",
		]) {
			expect(editor).toContain(key);
			expect(src).toContain(key);
		}
	});

	it("does not tell the planned footer's count that a rate is missing", () => {
		// The PLANNED footer counts whatever `convertedPreview` refuses, which is no
		// longer only a rate problem.
		expect(src).toMatch(/Lines that cannot be valued, not in this total: \{count\}[^]*?editorPlanned\.unvalued/);
	});
});
