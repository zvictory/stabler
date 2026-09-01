import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const rfqSrc = readFileSync(resolve(here, "../pages/tender/rfq/RfqPrint.vue"), "utf8");
const salesInvoiceSrc = readFileSync(resolve(here, "../pages/sales/InvoicePrint.vue"), "utf8");
const purchasingInvoiceSrc = readFileSync(resolve(here, "../pages/purchasing/InvoicePrint.vue"), "utf8");

/**
 * Four measured defects across the print surfaces (RfqPrint.vue and the two
 * InvoicePrint.vue's), fixed together because they were measured together.
 *
 * Same idiom as sourcingAwardPanel.spec.js: no `mount(`, DOM-less. Source is read
 * as text and either (a) executed, when the defect is about LOGIC -- extracting a
 * real `v-if="…"` expression out of the template and running it through
 * `evalInScope`, never re-implementing the condition by hand, because a
 * hand-written reimplementation can't catch the condition itself being wired
 * wrong -- or (b) counted in isolated, anchored source text, when the defect is
 * a forbidden literal that must not exist (a hardcoded mm width, a spinner
 * class, a dead CSS class name). A bare `toContain` over the whole file is
 * avoided anywhere it could pass on a coincidence; counts are scoped to the
 * smallest anchored slice that actually matters.
 */

function anchor(src, marker, what) {
	const at = src.indexOf(marker);
	expect(at, `${what}: marker not found -- "${marker}" -- has the file moved?`).toBeGreaterThan(-1);
	return at;
}

/** Balanced `<div ...>…</div>` matcher: given the index of a "<div" open tag,
 *  returns {start, end, text} for the whole element through its matching close,
 *  correctly skipping over any nested <div>s in between. Same technique as the
 *  reference file's `braceMatched`, adapted from `{}` to tag pairs. */
function divBlockAt(src, divTagStart) {
	const firstGt = src.indexOf(">", divTagStart);
	let depth = 1;
	let i = firstGt + 1;
	while (depth > 0) {
		const nextOpen = src.indexOf("<div", i);
		const nextClose = src.indexOf("</div>", i);
		if (nextClose === -1) throw new Error(`unterminated <div> starting at ${divTagStart}`);
		if (nextOpen !== -1 && nextOpen < nextClose) {
			depth++;
			i = src.indexOf(">", nextOpen) + 1;
		} else {
			depth--;
			i = nextClose + "</div>".length;
		}
	}
	return { start: divTagStart, end: i, text: src.slice(divTagStart, i) };
}

/** Evaluate a template expression pulled out of the source, against a supplied scope. */
function evalInScope(expression, scope) {
	const keys = Object.keys(scope);
	return new Function(...keys, `return (${expression});`)(...keys.map((k) => scope[k]));
}

describe("defect 1: the 'Needed by' column header carries no hardcoded mm width", () => {
	// A hard millimetre width on a <th> holding TRANSLATED text, on a fixed A4
	// page that cannot grow sideways -- measured worst-case string growth
	// across the offered languages is 3.75x. None of the other four <th>s in
	// this row carry any inline width, so this one must not either.
	const needle = 't("Needed by")';
	const thNeedle = anchor(rfqSrc, needle, "the 'Needed by' header cell");
	const tagStart = rfqSrc.lastIndexOf("<th", thNeedle);
	const tagEnd = rfqSrc.indexOf(">", tagStart);
	const openTag = rfqSrc.slice(tagStart, tagEnd + 1);

	it("has no 'mm' unit anywhere in its opening tag", () => {
		// Would fail the instant a hardcoded "Nmm" width (in style="" or
		// otherwise) is reintroduced on this specific <th> -- whether the exact
		// "30mm" from the original defect or any other millimetre figure.
		const mmCount = (openTag.match(/mm/g) || []).length;
		expect(mmCount, `expected no "mm" in ${JSON.stringify(openTag)}`).toBe(0);
	});

	it("carries no inline style attribute at all, matching its undecorated siblings", () => {
		// The four sibling <th>s (#, Item, Qty, UOM) size purely from content and
		// carry no style attribute. Would fail if a width crept back in under a
		// different property name (e.g. min-width) or a different unit (px, cm).
		expect(/\bstyle\s*=/.test(openTag)).toBe(false);
	});
});

describe("defect 2: a missing response deadline states so explicitly -- it does not vanish", () => {
	// Recomputed fresh INSIDE each `it` below, deliberately -- not hoisted to
	// describe-scope. Pre-fix, the fallback genuinely does not exist, and a
	// describe-scope `expect()` that throws during collection (the reference
	// file's own idiom) takes the whole file's collection down with it, which
	// would hide defects 1/3/4's red status in the same run. Per-test extraction
	// keeps every `it` here -- and every other describe in this file -- reporting
	// its own independent pass/fail.
	function extractDeadlineBranches() {
		const metaOpen = anchor(rfqSrc, '<div class="rfq-meta">', "the deadline meta wrapper");
		const metaBlock = divBlockAt(rfqSrc, metaOpen);

		const trueDivStart = rfqSrc.indexOf("<div", metaOpen + 1);
		expect(trueDivStart, "no child <div> inside rfq-meta -- has the deadline line been restructured?")
			.toBeGreaterThan(-1);
		const trueBlock = divBlockAt(rfqSrc, trueDivStart);
		const trueTagEnd = rfqSrc.indexOf(">", trueDivStart);
		const trueOpenTag = rfqSrc.slice(trueDivStart, trueTagEnd + 1);
		const ifMatch = trueOpenTag.match(/v-if="([^"]*)"/);
		expect(ifMatch, `the date branch lost its v-if guard: ${JSON.stringify(trueOpenTag)}`).not.toBeNull();

		const falseDivStart = rfqSrc.indexOf("<div", trueBlock.end);
		const hasFallbackInWrapper = falseDivStart > -1 && falseDivStart < metaBlock.end;

		return { ifExpr: ifMatch[1], hasFallbackInWrapper, falseDivStart };
	}

	it("the v-if guard, executed against a doc with no schedule_date, is false", () => {
		// Executes the REAL extracted expression rather than re-testing a
		// hand-written stand-in: a stand-in would keep passing even if the
		// template's own guard were spelled backwards or pointed at the wrong
		// field, which is exactly the failure mode this idiom exists to catch.
		const { ifExpr } = extractDeadlineBranches();
		expect(evalInScope(ifExpr, { doc: { schedule_date: null } })).toBeFalsy();
	});

	it("the same guard, executed against a doc that has a schedule_date, is true", () => {
		const { ifExpr } = extractDeadlineBranches();
		expect(evalInScope(ifExpr, { doc: { schedule_date: "2026-09-10" } })).toBeTruthy();
	});

	it("a fallback element sits inside rfq-meta directly after the date branch", () => {
		// The heart of the regression: pre-fix, nothing followed the v-if at
		// all, so an empty schedule_date rendered literally nothing -- absence
		// read as "they forgot to print it", not "no deadline was set".
		const { hasFallbackInWrapper } = extractDeadlineBranches();
		expect(hasFallbackInWrapper).toBe(true);
	});

	it("that element is a v-else or v-else-if, not unrelated markup that merely follows", () => {
		// Would fail if the "fallback" is coincidental -- some other div that
		// happens to sit next -- rather than actually wired to this v-if.
		const { hasFallbackInWrapper, falseDivStart } = extractDeadlineBranches();
		expect(hasFallbackInWrapper, "no fallback element to inspect").toBe(true);
		const falseTagEnd = rfqSrc.indexOf(">", falseDivStart);
		const falseOpenTag = rfqSrc.slice(falseDivStart, falseTagEnd + 1);
		expect(/^<div\s+v-else(-if)?[\s=>]/.test(falseOpenTag)).toBe(true);
	});

	it("the fallback branch renders real translated text, not an empty stub", () => {
		// Would fail against a "fix" like `<div v-else></div>` -- structurally
		// present, still shows the supplier nothing.
		const { hasFallbackInWrapper, falseDivStart } = extractDeadlineBranches();
		expect(hasFallbackInWrapper, "no fallback element to inspect").toBe(true);
		const falseBlock = divBlockAt(rfqSrc, falseDivStart);
		const tCalls = falseBlock.text.match(/t\(\s*"[^"]+"\s*\)/g) || [];
		expect(tCalls.length).toBeGreaterThan(0);
	});
});

describe("defect 3: the loading state on the RFQ letter is a skeleton, never a spinner", () => {
	it("has zero Bootstrap spinner markup anywhere in the file", () => {
		const spinnerCount = (rfqSrc.match(/spinner-border/g) || []).length;
		expect(spinnerCount, "would fail the moment a spinner-border reappears anywhere in RfqPrint.vue").toBe(0);
	});

	it("renders SkeletonRows inside the loading branch, textually before the printable a4-print branch", () => {
		const loadingBranch = anchor(rfqSrc, 'v-if="loading"', "the loading branch");
		const a4Branch = anchor(rfqSrc, 'class="a4-print"', "the a4-print branch");
		const skeletonPos = rfqSrc.indexOf("SkeletonRows", loadingBranch);
		expect(skeletonPos, "SkeletonRows is not used inside the loading branch").toBeGreaterThan(-1);
		// Print safety: this file hides everything except .a4-print at print time
		// (isolation by inclusion, see the @media print block) -- so a skeleton
		// that sits in the mutually-exclusive v-if/else-if branch BEFORE a4-print
		// can never coexist with it on screen, and is therefore already excluded
		// from print output by the same mechanism that already hides .no-print
		// and the error alert. Would fail if the skeleton were moved inside (or
		// after) the a4-print branch.
		expect(skeletonPos).toBeLessThan(a4Branch);
	});

	it("imports SkeletonRows from the shared component", () => {
		const importCount = (rfqSrc.match(/import\s+SkeletonRows\s+from\s+["'][^"']*SkeletonRows\.vue["']/g) || [])
			.length;
		expect(importCount).toBe(1);
	});
});

describe("defect 4: the dead print-wrapper class is gone from all three print surfaces", () => {
	// Confirmed independently on 2026-09-01 by grepping stabler/public/css/, every
	// <style> block in these three components, and the rest of the tracked repo:
	// zero CSS rules named .print-wrapper exist anywhere. This regex covers both
	// a template class= reference AND a stray CSS selector reappearing later,
	// since it scans each file's full text (template + script + style).
	//
	// Each file gets its OWN assertion on purpose: one file silently diverging
	// (the class re-added to only one of the three) must fail on its own, not
	// get averaged away by the other two passing.
	const files = {
		"tender/rfq/RfqPrint.vue": rfqSrc,
		"sales/InvoicePrint.vue": salesInvoiceSrc,
		"purchasing/InvoicePrint.vue": purchasingInvoiceSrc,
	};

	for (const [label, src] of Object.entries(files)) {
		it(`${label} contains zero occurrences of "print-wrapper"`, () => {
			const count = (src.match(/print-wrapper/g) || []).length;
			expect(count, `expected 0 occurrences of "print-wrapper" in ${label}, found ${count}`).toBe(0);
		});
	}
});
