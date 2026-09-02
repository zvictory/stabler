import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const read = (rel) => readFileSync(resolve(here, "..", rel), "utf8");

const board = read("pages/sales/SalesOrderBoard.vue");
const funnel = read("pages/tender/TenderFunnel.vue");

/**
 * The filter travels with the click (prompt 18, acceptance row C14).
 *
 * `TenderFunnel.vue` states the intent in a comment: execution buckets open the
 * contract board, "whose columns ARE that list." Measured 2026-09-02, three
 * things stood between that sentence and the truth.
 *
 * 1. The buckets left with a bare `router.push("/tender/board")` — no query at
 *    all. Clicking a box reading "Procurement (PO) 1" landed on a board showing
 *    every submitted contract in the company, tender-linked or not.
 * 2. The board read `route.query.tender`. Every other tender drill-down in the
 *    SPA — six list pages plus the router's own access guard — reads
 *    `tender_only`. So even a reader who typed the module's usual parameter got
 *    the unfiltered board, silently.
 * 3. `tender_only=1` on the server meant `docstatus < 2` (drafts IN) plus a deal
 *    restriction, while the funnel counts `docstatus: 1` plus the same deal
 *    restriction. Fixing 1 and 2 alone would have landed the reader on a board
 *    holding drafts the number never counted. That half is pinned server-side in
 *    tests/test_tender_board_filter.py.
 *
 * DOM-less per vitest.config.mjs. `go()` is lifted from the funnel and run for
 * real against a fake router, because "the click carries the filter" is a claim
 * about what a function does.
 */

/** The drill-down pages that already had a name for this filter. */
const SIBLINGS = [
	"pages/sales/SalesOrders.vue",
	"pages/sales/SalesInvoices.vue",
	"pages/sales/DeliveryNotes.vue",
	"pages/purchasing/PurchaseOrders.vue",
	"pages/purchasing/PurchaseReceipts.vue",
	"pages/purchasing/PurchaseInvoices.vue",
];

describe("C14 — the board's filter matches the number that navigated to it", () => {
	it("uses the query parameter the rest of the module already uses", () => {
		// WHAT WOULD MAKE THIS FAIL: the board going back to `route.query.tender`,
		// or a sibling drifting to a different name. Asserting the RELATIONSHIP
		// rather than the literal string is the point: the name only has to be
		// shared, and this fails whichever side moves. A second name for one filter
		// is not a style question here — the router's access guard (router.js) keys
		// tender-role drill-down permission off `tender_only`, so a board on its own
		// spelling is outside that grant as well as outside the convention.
		const names = new Set(
			SIBLINGS.map((f) => read(f).match(/route\.query\.(\w+) === "1"/)?.[1]).filter(Boolean)
		);
		expect(names.size, `siblings disagree: ${[...names]}`).toBe(1);
		const [shared] = [...names];
		expect(board).toMatch(new RegExp(`route\\.query\\.${shared}\\b`));
		expect(read("router.js")).toMatch(new RegExp(`query\\.${shared} === "1"`));
	});

	it("no longer answers to the name only it used", () => {
		// WHAT WOULD MAKE THIS FAIL: leaving `route.query.tender` in place beside
		// the new name "for compatibility". Two spellings for one filter is how the
		// board ended up unfiltered in the first place, and nothing in the SPA ever
		// wrote the old one, so there is no link in the wild to keep working.
		expect(/route\.query\.tender\b(?!_)/.test(board), "the old `tender` key is back").toBe(false);
	});

	it("sends the flag to the server on every load", () => {
		// WHAT WOULD MAKE THIS FAIL: reading the query into a computed and then not
		// passing it. The badge would say the board is filtered while the request
		// asked for everything — a filter that lies is worse than the missing one,
		// because the reader now believes the count.
		//
		// This shows the flag is WRITTEN into the request. That it ARRIVES is
		// contractBoardReload.spec.js's "C14 — the request carries the filter the
		// board is showing", which runs the real load() against a fake `call`; the
		// harness for that lives there.
		const call = board.slice(
			board.indexOf("so_board"),
			board.indexOf("});", board.indexOf("so_board"))
		);
		expect(call).toMatch(/tender_only:\s*tenderOnly\.value/);
	});

	it("re-fetches when the filter is switched off", () => {
		// WHAT WOULD MAKE THIS FAIL: clearing the query without reloading. The
		// server decides this filter, so dropping the parameter changes the URL and
		// the badge and leaves the same filtered cards on screen — the reader asks
		// for everything and is shown the subset, with nothing left to say so.
		// Anchored to line start: a commented-out `// watch(tenderOnly, load);`
		// satisfies an unanchored match, which is how the mutation pass caught this
		// assertion passing over a disabled watch.
		expect(board).toMatch(/^watch\(tenderOnly, load\);$/m);
	});
});

/** Lift `function go(st)` from the funnel and bind it to a fake router. */
function liftGo(router) {
	const fn = funnel.match(/^function go\(st\)[\s\S]*?^\}/m);
	expect(fn, "TenderFunnel.vue has no top-level go()").not.toBeNull();
	return new Function("router", `${fn[0]}\nreturn go;`)(router);
}

function spyRouter() {
	const pushed = [];
	return { pushed, push: (to) => pushed.push(to) };
}

describe("C14 — the funnel carries its filter to the board", () => {
	it("opens the board filtered to tender contracts", () => {
		// WHAT WOULD MAKE THIS FAIL: the bare router.push("/tender/board") coming
		// back. The funnel's execution buckets count only Sales Orders tagged to a
		// deal; landing on the unfiltered board shows every contract in the company,
		// so the reader's next act — counting the cards — disagrees with the box
		// they just clicked.
		const r = spyRouter();
		liftGo(r)({ kind: "so", key: "procurement" });
		expect(r.pushed).toHaveLength(1);
		expect(r.pushed[0]).toEqual({ path: "/tender/board", query: { tender_only: "1" } });
	});

	it("leaves deal stages going where they went", () => {
		// WHAT WOULD MAKE THIS FAIL: routing every bucket to the board. Deal stages
		// are not contracts — they open My Tenders filtered to the classified set,
		// and that half of go() was never the defect.
		const r = spyRouter();
		liftGo(r)({ kind: "deal", key: "submitted" });
		expect(r.pushed[0]).toEqual({
			path: "/tender/my-tenders",
			query: { funnel_stage: "submitted" },
		});
	});
});

describe("C14 — a filtered board says so, and can be left", () => {
	/** The rendered #meta slot. */
	const meta = () => {
		const at = board.indexOf("#meta>");
		expect(at, "the board has no #meta slot").toBeGreaterThan(-1);
		return board.slice(at, board.indexOf("</template>", at));
	};

	it("wears the same badge the six sibling drill-downs wear", () => {
		// WHAT WOULD MAKE THIS FAIL: inventing a seventh way to say "filtered".
		// Every other screen reached from a tender number carries exactly
		// `badge bg-blue-lt text-blue` with the key "Tender records"; a reader who
		// drills into orders, then invoices, then the board should not have to learn
		// the mark three times.
		const sibling = read(SIBLINGS[0]).match(
			/<span v-if="tenderOnly"[^>]*>\{\{ t\("([^"]+)"\) \}\}/
		);
		expect(sibling, "the sibling badge has moved").not.toBeNull();
		expect(meta()).toMatch(/v-if="tenderOnly"[\s\S]{0,120}badge bg-blue-lt text-blue/);
		expect(meta()).toContain(`t("${sibling[1]}")`);
	});

	it("offers a way back to the whole board", () => {
		// WHAT WOULD MAKE THIS FAIL: shipping the badge alone, which is what the six
		// siblings do. They can afford it: each sits in a ListToolbar full of
		// controls the reader can already change. This board has no toolbar and no
		// control for this flag, so a badge alone would be a filter you can enter
		// and cannot leave except by editing the address bar. Before this change the
		// mode was unreachable, so the missing exit cost nothing; the funnel click
		// is what makes it a trap.
		expect(meta()).toMatch(/@click="clearTenderOnly"/);
		expect(board).toMatch(/^function clearTenderOnly\(\)/m);
	});

	it("clears only this filter, not the board's other query state", () => {
		// WHAT WOULD MAKE THIS FAIL: router.replace({ query: {} }). The board also
		// reads stage/period/risk/due/status/from_date/to_date out of the URL
		// (tenderBoardFilters.js), so blanking the query would silently drop filters
		// the reader set elsewhere while they were only asking to see non-tender
		// contracts again.
		const fn = board.match(/^function clearTenderOnly\(\)[\s\S]*?^\}/m);
		expect(fn, "clearTenderOnly is gone").not.toBeNull();
		expect(fn[0]).toMatch(/\.\.\.route\.query/);
		expect(fn[0]).toMatch(/delete\s+\w+\.tender_only/);
	});

	it("says nothing when the board is not filtered", () => {
		// WHAT WOULD MAKE THIS FAIL: rendering the badge unconditionally. A mark
		// that is always there marks nothing, and the reader would read the ordinary
		// board as a subset of itself.
		expect(meta()).toMatch(/v-if="tenderOnly"/);
		expect(meta()).not.toMatch(/v-else\b/);
	});
});
