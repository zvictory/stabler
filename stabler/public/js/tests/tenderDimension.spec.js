import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";

const here = dirname(fileURLToPath(import.meta.url));
const expenses = readFileSync(resolve(here, "../pages/money/Expenses.vue"), "utf8");
const invoice = readFileSync(resolve(here, "../pages/purchasing/PurchaseInvoiceForm.vue"), "utf8");

/**
 * ADR-609 P5a — the two screens that choose a tender.
 *
 * The tender is an accounting dimension now: `mandatory_for_pl` is on for every
 * tender company, so the server WILL put a value on each P&L row of anything
 * these forms post — the tender the document names, or GENEL GİDER. The screens
 * therefore have one job that nothing else can do for them: show, before Save,
 * what the ledger is about to say. A picker that offers a lost tender, or that
 * leaves a new expense blank while the server silently books it to overhead, is
 * telling the user something untrue about their own books.
 *
 * These are source guards, deliberately: the state they pin is what the
 * component SENDS and what it RENDERS, and both survive any amount of internal
 * refactoring. Comments are stripped first — an assertion a comment can satisfy
 * is an assertion that passes the moment somebody explains the mistake.
 *
 * DOM-less per vitest.config.mjs.
 */

/** The file with every comment blanked out — line count and numbering preserved. */
function withoutComments(src) {
	const blank = (m) => m.replace(/[^\n]/g, " ");
	return src
		.replace(/<!--[\s\S]*?-->/g, blank)
		.replace(/\/\*[\s\S]*?\*\//g, blank)
		.split("\n")
		.map((line) => (/^\s*\/\//.test(line) ? "" : line))
		.join("\n");
}

const expensesCode = withoutComments(expenses);
const invoiceCode = withoutComments(invoice);

/** The body of a named function, brace-matched. */
function fn(src, name) {
	const at = src.search(new RegExp(`(async\\s+)?function ${name}\\s*\\(`));
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const from = src.indexOf("{", at);
	let depth = 0;
	for (let i = from; i < src.length; i++) {
		if (src[i] === "{") depth++;
		else if (src[i] === "}" && --depth === 0) return src.slice(at, i + 1);
	}
	throw new Error(`unterminated ${name}`);
}

/** The attributes of the first element whose opening tag matches `pattern`. */
function element(src, pattern) {
	const at = src.search(pattern);
	expect(at, `no element matching ${pattern}`).toBeGreaterThan(-1);
	return src.slice(at, src.indexOf(">", at) + 1);
}

describe("Expenses — the tender picker offers only what the ledger accepts", () => {
	it("asks for active tenders, not for every deal on the board", () => {
		// `list_deals` without this flag returns 551 Standard deals on the test
		// site. Any of them saved fine and then meant nothing on the ledger.
		expect(fn(expensesCode, "searchDeals")).toContain("active_tenders: 1");
	});

	it("defaults a new entry to the overhead deal on a tender company", () => {
		// The server defaults an untagged P&L row to GENEL GİDER whatever the form
		// shows. Leaving the field blank does not leave the ledger blank — it just
		// stops the screen from admitting where the money is going.
		const body = fn(expensesCode, "openCreate");
		expect(body).toMatch(/tenderOn/);
		expect(body).toMatch(/defaultOverheadDeal|loadOverheadDeal|overheadDeal/);
	});

	it("never rewrites the tender an existing entry already carries", () => {
		// Same rule as `charge_type` in ADR-606: a stored value is what the ledger
		// says, and re-deriving it on load would rewrite history on the next save.
		const body = fn(expensesCode, "openEditFromDetail");
		expect(body).toContain("listRow?.crm_deal");
		expect(body).not.toMatch(/openCreate|defaultOverheadDeal\(\)/);
	});

	it("names the empty state instead of showing an empty menu", () => {
		expect(expensesCode).toMatch(/t\(['"]No active tenders['"]\)/);
	});

	it("keeps the picker usable when the lookup fails", () => {
		// A failed search must not leave the user with a dead control on a form
		// they still have to post: the toast explains, the field still works.
		const body = fn(expensesCode, "searchDeals");
		expect(body).toContain("catch");
		expect(body).toMatch(/toast\.(error|warning)/);
	});
});

describe("Purchase Invoice — a tender picker that says why it is disabled", () => {
	it("renders only for a user who can reach the tender module", () => {
		const at = invoiceCode.indexOf('t("Tender")');
		expect(at, "the Tender field is gone").toBeGreaterThan(-1);
		const block = invoiceCode.slice(Math.max(0, at - 400), at);
		expect(block).toContain("canAccessModule('tender')");
	});

	it("loads the value, its label and its locked state from the server", () => {
		const body = fn(invoiceCode, "fromDetail");
		for (const key of ["d.tender", "d.tender_label", "d.tender_locked"]) {
			expect(body, `fromDetail drops ${key}`).toContain(key);
		}
	});

	it("sends the tender it is showing", () => {
		// Without this the form renders a choice it never posts — the worst of the
		// three states, because it looks like it worked.
		expect(fn(invoiceCode, "toPayload")).toMatch(/tender:/);
	});

	it("disables the picker when the purchase order decided the value", () => {
		const tag = element(invoiceCode, /<Typeahead[^>]*v-model="form\.tender"/);
		expect(tag).toMatch(/:disabled="[^"]*tender_locked/);
	});

	it("says why it is disabled rather than ignoring the click", () => {
		expect(invoiceCode).toContain('t("Set by the purchase order")');
	});

	it("defaults a new invoice with no order to the overhead deal", () => {
		// Defining the helper is not the behaviour — mounting a blank form has to
		// CALL it, or the field renders empty while the server books the bill to
		// overhead anyway.
		const at = invoiceCode.indexOf("onMounted(");
		expect(at, "the mount hook is gone").toBeGreaterThan(-1);
		const mounted = invoiceCode.slice(at, invoiceCode.indexOf("\n});", at));
		expect(mounted).toMatch(/defaultOverheadDeal\(\)/);
		expect(mounted).toMatch(/blankForm\(\)/);
	});

	it("keeps the picker usable when the lookup fails", () => {
		const body = fn(invoiceCode, "searchTenders");
		expect(body).toContain("catch");
		expect(body).toMatch(/toast\.(error|warning)/);
	});
});

describe("Stabler invariants hold on both screens", () => {
	it("adds no Desk link", () => {
		for (const [name, src] of [
			["Expenses.vue", expensesCode],
			["PurchaseInvoiceForm.vue", invoiceCode],
		]) {
			expect(src, `${name} links out to the Desk`).not.toMatch(/["'`]\/app\//);
		}
	});

	it("adds no hand-written table-striped", () => {
		for (const src of [expensesCode, invoiceCode]) {
			expect(src).not.toContain("table-striped");
		}
	});

	it("ships every new string in all five catalogues", () => {
		// "GENEL GİDER" is a proper name and is deliberately absent: it is the
		// deal's own organization, rendered as stored, never translated.
		const keys = [
			"Tender",
			"Set by the purchase order",
			"No active tenders",
			"General overhead",
			"Only an active tender or GENEL GİDER can be selected.",
			"Could not load tenders",
		];
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
			for (const key of keys) {
				expect(rows.get(key), `${lang}.csv has no target for ${JSON.stringify(key)}`).toBeTruthy();
			}
			expect(rows.has("GENEL GİDER"), `${lang}.csv translates a proper name`).toBe(false);
		}
	});
});
