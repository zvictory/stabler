import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/tender/BidPricing.vue"), "utf8");

/**
 * ADR-609 P5b — the ledger side of the bid-pricing card.
 *
 * The card already shows a "Plan vs actual" block whose actual column is derived
 * from DOCUMENTS: the Sales Order's invoiced percentage, the Purchase Order's
 * total, the Journal Entries carrying `custom_crm_deal`. P5a made every stamped
 * voucher's GL row name its tender, so the same question can now be answered from
 * the ledger — and the two answers differ in ways that matter (a PO placed but
 * not received reads as landed; a stamped bill with no PO behind it is invisible).
 *
 * Three properties of this section are worth pinning in source, because each one
 * is invisible in a screenshot and each has a plausible-looking wrong version:
 *
 *   * it is a SECOND request with its own failure. The pricing card is the
 *     officer's working tool and a ledger endpoint that falls over must not take
 *     it down — so `loadLedger` may not share `load`'s loading flag, nor be
 *     awaited from inside it;
 *   * the difference is the SERVER's. `delta` is computed once, in Python, where
 *     it is tested; a browser that subtracts the two columns itself is a second
 *     implementation of the same arithmetic that nothing measures;
 *   * every state names an action. "Unavailable" without "save Stabler Settings"
 *     and "empty" without "post or tag a document" leave the reader with a blank
 *     panel and no idea whether it is broken or simply early.
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

const template = src.slice(src.indexOf("<template>"));

// The section is bounded by its own comment and the card's action bar, which is
// its next sibling. Slicing to the end of the file instead would drag the "Save
// bid pricing" primary into every assertion below about this region's buttons.
const SECTION_START = "<!-- Ledger vs documents";
const SECTION_END = '<div class="text-end mt-3">';
const sectionAt = template.indexOf(SECTION_START);
const sectionEnd = template.indexOf(SECTION_END, sectionAt);
if (sectionAt < 0 || sectionEnd < sectionAt) {
	throw new Error(
		"the ledger section is not between its own comment and the card's action bar — " +
			"it has moved, and every assertion below would measure the wrong markup",
	);
}
const ledgerSection = template.slice(sectionAt, sectionEnd);

describe("the ledger side is a second request that cannot take the pricing card down", () => {
	it("calls the ledger endpoint and nothing else", () => {
		// WHAT WOULD MAKE THIS FAIL: folding the ledger into `deal_bid_pricing`.
		// That endpoint is what the officer's own screen depends on; adding a GL
		// scan to it makes every bid-pricing load pay for a report nobody may be
		// reading, and a slow ledger becomes a slow pricing card.
		const fn = extractFunction("loadLedger");
		expect(fn).toMatch(/call\(\s*"stabler\.api\.tender_gl\.tender_gl_pnl"/);
		expect(fn).toMatch(/deal:\s*props\.deal/);
	});

	it("carries its own busy flag and never touches the pricing one", () => {
		// WHAT WOULD MAKE THIS FAIL: reusing `loading`. The whole card renders a
		// spinner instead of its body while `loading` is true, so a slow ledger
		// read would blank the inputs the officer is typing into.
		const fn = extractFunction("loadLedger");
		expect(fn).toMatch(/ledgerLoading\.value\s*=\s*true/);
		expect(fn).toMatch(/ledgerLoading\.value\s*=\s*false/);
		expect(fn).not.toMatch(/[^r]\bloading\.value/);
		// And the FAILURE flag is cleared on entry, not only set on failure.
		// `v-if="ledgerFailed"` wins over the `v-else-if="ledger"` that renders the
		// table, so without this a successful Retry loads the figures and leaves the
		// warning banner standing over them — for the rest of the session. Every
		// other assertion in this file stays green while that happens.
		expect(fn).toMatch(/ledgerFailed\.value\s*=\s*false/);
	});

	it("catches its own failure instead of letting it escape", () => {
		// WHAT WOULD MAKE THIS FAIL: no catch. An unhandled rejection in the
		// watcher leaves `ledgerLoading` true forever — a spinner in a void, which
		// the frontend rules ban by name.
		const fn = extractFunction("loadLedger");
		expect(fn).toMatch(/try\s*\{/);
		expect(fn).toMatch(/catch\s*\(/);
		expect(fn).toMatch(/finally\s*\{/);
		expect(fn).toMatch(/ledgerFailed\.value\s*=\s*true/);
		expect(fn).toMatch(/ledgerErrorDetail\.value\s*=/);
	});

	it("is triggered beside `load`, not from inside it", () => {
		// WHAT WOULD MAKE THIS FAIL: `await loadLedger()` at the end of `load`.
		// The pricing data would then wait on the ledger, and a ledger that throws
		// before its own try block would abort the load that called it.
		expect(extractFunction("load")).not.toMatch(/loadLedger/);
		expect(src).toMatch(/watch\(\s*\(\)\s*=>\s*props\.deal,\s*loadLedger,\s*\{\s*immediate:\s*true\s*\}\s*\)/);
	});

	it("clears the stale ledger when a reload fails", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `ledger` set. The previous deal's — or
		// the previous attempt's — figures would stay on screen under an error
		// banner, which is the one presentation worse than no figures at all.
		expect(extractFunction("loadLedger")).toMatch(/catch[\s\S]*ledger\.value\s*=\s*null/);
	});
});

describe("the difference between the two columns is computed once, on the server", () => {
	it("prints the server's delta", () => {
		// WHAT WOULD MAKE THIS FAIL: `fm(r.gl - r.documents)`. The reconciliation
		// rules — which document figure is comparable to which buckets, and that an
		// uninvoiced deal reads 0 rather than its planned revenue — all live in
		// `_tender_gl` and are tested there. Re-deriving the number here forks them.
		expect(ledgerSection).toMatch(/fm\(\s*r\.delta\s*\)/);
		expect(ledgerSection).not.toMatch(/r\.gl\s*-\s*r\.documents/);
		expect(ledgerSection).not.toMatch(/r\.documents\s*-\s*r\.gl/);
	});

	it("colours a difference by what it means for that row, not by its sign", () => {
		// A ledger holding MORE revenue than the documents knew is good news; a
		// ledger holding more cost is not. WHAT WOULD MAKE THIS FAIL: one rule for
		// every row, which paints an overrun green on three lines out of four.
		const fn = extractFunction("deltaClass");
		expect(fn).toMatch(/"revenue"/);
		expect(fn).toMatch(/"result"/);
		expect(fn).toMatch(/text-red/);
		expect(fn).toMatch(/text-green/);
		// Zero is neither good nor bad, and painting it green says the two sources
		// were checked and agreed — which is exactly what it does mean, but only
		// once something has been posted. Neutral until then.
		expect(fn).toMatch(/text-secondary/);
	});

	it("renders every amount through the card's own money formatter", () => {
		// WHAT WOULD MAKE THIS FAIL: `toLocaleString()`, or a second formatter.
		// The GL totals are company currency and so is `props.currency`; `fm` is
		// what makes the two tables of this card agree on how a som is written.
		// PROPERTY reads only. Anchored on the dot because the section's own title
		// contains the word "documents": an assertion written on the bare word
		// passed on `{{ t("Ledger vs documents") }}` and measured nothing.
		const amounts =
			ledgerSection.match(/\{\{[^}]*\.(documents|gl|delta|amount|stock_on_hand|net)\b[^}]*\}\}/g) || [];
		expect(amounts.length).toBeGreaterThan(3);
		for (const cell of amounts) expect(cell, `${cell} is not formatted`).toMatch(/fm\(/);
	});
});

describe("every state of the section names what to do about it", () => {
	it("says the dimension is not set up, and what creates it", () => {
		// WHAT WOULD MAKE THIS FAIL: "no data". A site that never ran v103 has no
		// tender column on GL Entry at all, and the fix is one save on a settings
		// screen — a sentence the reader can act on, versus one they cannot.
		expect(ledgerSection).toMatch(
			/t\("Ledger view unavailable: the tender dimension is not set up for this company\. Save Stabler Settings with the tender module on to create it\."\)/,
		);
		expect(ledgerSection).toMatch(/ledger\.available/);
	});

	it("distinguishes 'nothing posted yet' from 'not set up'", () => {
		// The two look identical on screen — four zeroes — and mean opposite
		// things: one is an early tender, the other a broken install. WHAT WOULD
		// MAKE THIS FAIL: a single empty state for both.
		expect(ledgerSection).toMatch(
			/t\("No ledger entry carries this tender yet\. Post or tag an invoice, delivery or expense to see the ledger side\."\)/,
		);
		expect(ledgerSection).toMatch(/ledger\.row_count/);
	});

	it("offers a retry when the read failed, and shows why", () => {
		// WHAT WOULD MAKE THIS FAIL: an error with no way back. The failure is
		// usually transient and the officer has no other route to this figure.
		expect(ledgerSection).toMatch(/t\("Could not load the ledger view\."\)/);
		expect(ledgerSection).toMatch(/t\("Retry"\)/);
		// The server's own detail, and ONLY when there is one. `err.message` is
		// routinely empty (a network drop, an aborted fetch); defaulting it to the
		// generic sentence printed that sentence twice, the second time dressed as
		// the server's explanation of itself.
		expect(ledgerSection).toMatch(/v-if="ledgerErrorDetail"/);
		expect(ledgerSection).toMatch(/\{\{ ledgerErrorDetail \}\}/);
		const generic = ledgerSection.match(/t\("Could not load the ledger view\."\)/g) || [];
		expect(generic, "the generic sentence is rendered more than once").toHaveLength(1);
		// The defect itself, pinned where it was written.
		expect(extractFunction("loadLedger")).not.toMatch(
			/ledgerErrorDetail\.value\s*=[^;\n]*\|\|\s*t\(/,
		);
	});

	it("says it is loading rather than showing an empty table", () => {
		expect(ledgerSection).toMatch(/t\("Loading ledger…"\)/);
		expect(ledgerSection).toMatch(/ledgerLoading/);
	});

	it("explains each server note in a sentence that names the repair", () => {
		// The notes are CODES on the wire so the server never ships prose. WHAT
		// WOULD MAKE THIS FAIL: printing the code. "landed_credit_surplus" tells
		// the reader nothing; the sentence tells them to re-tag the bill.
		const fn = extractFunction("ledgerNote");
		for (const code of ["not_invoiced", "landed_credit_surplus", "stock_on_hand", "no_documents"]) {
			expect(fn, `the ${code} note has no sentence`).toMatch(new RegExp(`"${code}"`));
		}
		expect(fn).toMatch(/Re-tag that bill/);
		expect(ledgerSection).toMatch(/ledgerNote\(/);
	});
});

describe("the landed row is reconciled against two buckets and shows both", () => {
	it("lists the cost-of-goods accounts and the landed accounts under it", () => {
		// The documents' landed figure is a PURCHASE total; in the ledger the goods
		// reach cogs on delivery and the charges sit in landed. WHAT WOULD MAKE
		// THIS FAIL: showing one bucket's accounts under a row whose total is both,
		// so the breakdown never adds up to the line above it.
		const fn = extractFunction("ledgerAccounts");
		expect(fn).toMatch(/cogs/);
		expect(fn).toMatch(/landed/);
		expect(fn).toMatch(/revenue/);
		expect(fn).toMatch(/expenses/);
	});

	it("reports stock still on hand outside the result", () => {
		// Goods bought for this tender and not yet delivered are an asset. WHAT
		// WOULD MAKE THIS FAIL: adding it to a cost row, which shows the tender at
		// a loss for the whole period between receipt and delivery.
		expect(ledgerSection).toMatch(/t\("Stock on hand for this tender"\)/);
		expect(ledgerSection).toMatch(/ledger\.stock_on_hand\s*>\s*0/);
	});
});

describe("the section obeys the card's house rules", () => {
	it("adds no second primary button to a region that already has one", () => {
		// "Save bid pricing" is this region's only primary. WHAT WOULD MAKE THIS
		// FAIL: a `btn-primary` Refresh, which competes with Save for the eye on a
		// card whose whole purpose is saving a price.
		expect(ledgerSection).toMatch(/t\("Refresh"\)/);
		expect(ledgerSection).not.toMatch(/btn-primary/);
		const buttons = ledgerSection.match(/class="btn[^"]*"/g) || [];
		expect(buttons.length).toBeGreaterThan(1);
		for (const cls of buttons) expect(cls).toMatch(/btn-outline-secondary/);
	});

	it("keeps the striping global and the Desk out of the SPA", () => {
		// `make guards` greps the whole tree for both. This records the intent at
		// the point it could be reintroduced, and fails in the file being edited
		// rather than in a gate whose output is one line at the end of a run.
		expect(ledgerSection).not.toMatch(/table-striped/);
		expect(ledgerSection).not.toMatch(/\/app\//);
		expect(ledgerSection).toMatch(/table table-no-stripe table-sm/);
	});

	it("was not built by editing the block above it", () => {
		// WHAT WOULD MAKE THIS FAIL: replacing "Plan vs actual". The transition
		// period's whole premise is both sources on screen at once — the council's
		// decision says "in the transition the two sources sit side by side".
		expect(src).toMatch(/t\("Plan vs actual"\)/);
		expect(src).toMatch(/actual\.ostatok_delta/);
		expect(src).toMatch(/t\("Ledger vs documents"\)/);
	});
});

describe("the section is fed by the endpoint's own shape", () => {
	it("reads the reconciliation rows in the order the server sent them", () => {
		// WHAT WOULD MAKE THIS FAIL: indexing `reconciliation[0..3]` by hand, or
		// re-sorting. The server freezes the order and the label comes from `key`;
		// a client-side order silently relabels every figure.
		expect(ledgerSection).toMatch(/v-for="r in ledger\.reconciliation"/);
		expect(ledgerSection).toMatch(/ledgerLabel\(r\.key\)/);
		expect(ledgerSection).not.toMatch(/reconciliation\[\d\]/);
		expect(ledgerSection).not.toMatch(/reconciliation[^<]*\.sort\(/);
	});

	it("labels each row from its key with a real translation call", () => {
		// WHAT WOULD MAKE THIS FAIL: `t(labels[key])`, which the harvester cannot
		// see — the four labels would never enter a catalogue and would render in
		// English on a Russian screen.
		const fn = extractFunction("ledgerLabel");
		for (const label of [
			"Net revenue",
			"Cost of goods and landed charges",
			"Tender expenses",
			"Operating result",
		]) {
			expect(fn, `${label} is not a literal t() call`).toMatch(
				new RegExp(`t\\("${label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}"\\)`),
			);
		}
	});

	it("translates the voucher type names it prints", () => {
		// "Sales Invoice" is an ERPNext doctype name and reads as English in the
		// middle of a Russian table. WHAT WOULD MAKE THIS FAIL: interpolating
		// `v.voucher_type` raw.
		expect(ledgerSection).toMatch(/t\(\s*v\.voucher_type\s*\)/);
		expect(ledgerSection).toMatch(/ledger\.by_voucher/);
	});
});
