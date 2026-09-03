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

/** The body of the `catch` block inside an already-extracted function body. */
function catchBlock(body) {
	const at = body.indexOf("catch");
	expect(at, "the function has no catch block").toBeGreaterThan(-1);
	const from = body.indexOf("{", at);
	let depth = 0;
	for (let i = from; i < body.length; i++) {
		if (body[i] === "{") depth++;
		else if (body[i] === "}" && --depth === 0) return body.slice(from + 1, i);
	}
	throw new Error("unterminated catch block");
}

/** The attributes of the first element whose opening tag matches `pattern`. */
function element(src, pattern) {
	const at = src.search(pattern);
	expect(at, `no element matching ${pattern}`).toBeGreaterThan(-1);
	return src.slice(at, src.indexOf(">", at) + 1);
}

describe("Purchase invoice — the tender the bill will carry", () => {
	it("re-derives the default when the company changes on a create form", () => {
		// Same bug as the Expenses screen: a default carried over from the previous
		// company is a value the server refuses on save.
		const at = invoiceCode.search(/watch\(\s*\(\)\s*=>\s*session\.company|watch\(\s*activeCompany|watch\(\s*company/);
		expect(at, "the purchase invoice form does not watch the company").toBeGreaterThan(-1);
		const body = invoiceCode.slice(at, invoiceCode.indexOf("});", at));
		expect(body).toMatch(/defaultOverheadDeal|overheadDeal/);
	});
});

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

	it("forgets the previous company's overhead bucket when the company changes", () => {
		// `loadOverheadDeal` short-circuits on the cached ref, so without this a new
		// entry created after switching company is pre-set with the PREVIOUS
		// company's GENEL GİDER deal — and the server refuses it with "Only an
		// active tender or GENEL GİDER can be selected." on a field the user never
		// touched.
		const at = expensesCode.search(/watch\(\s*activeCompany/);
		expect(at, "the company watcher is gone").toBeGreaterThan(-1);
		const body = expensesCode.slice(at, expensesCode.indexOf("});", at));
		expect(body).toMatch(/overheadDeal\.value\s*=\s*null/);
	});

	it("still offers GENEL GİDER when the lookup fails", () => {
		// Contract, "Frontend states": on a lookup error the picker stays usable
		// with the overhead bucket. Returning [] leaves the user with an empty menu
		// on a field the ledger will fill anyway.
		const body = fn(expensesCode, "searchDeals");
		const caught = body.slice(body.indexOf("catch"));
		expect(caught).toMatch(/overheadDeal/);
		expect(caught).not.toMatch(/return\s*\[\s*\]\s*;\s*\}?\s*$/);
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

	it("lets an existing bill have its tender removed, not only replaced", () => {
		// `tender: undefined` is dropped from the JSON body, so the server reads
		// "the form did not choose" and keeps whatever the bill already carried: a
		// manually chosen tender could be swapped but never cleared, and the user
		// watches the field they emptied come back on reload. On CREATE undefined
		// is still right — nothing was chosen, and the PO or GENEL GİDER decides.
		// On UPDATE an empty picker IS a choice, and "" is how it is expressed.
		const line = fn(invoiceCode, "toPayload")
			.split("\n")
			.find((each) => /^\s*tender:/.test(each));
		expect(line, "toPayload no longer sends a tender").toBeTruthy();
		const expression = line.replace(/^\s*tender:\s*/, "").replace(/,\s*$/, "");
		// The real expression, evaluated — not its spelling, which is free to change.
		const sent = (tender, isCreate, on = true) =>
			new Function(
				"m",
				"tenderOn",
				"isCreate",
				`return (${expression});`,
			)({ tender }, { value: on }, { value: isCreate });

		expect(sent("DEAL-1", true)).toBe("DEAL-1");
		expect(sent("DEAL-1", false)).toBe("DEAL-1");
		expect(sent("", true)).toBe(undefined);
		expect(sent("", false)).toBe("");
		expect(sent("DEAL-1", false, false)).toBe(undefined);
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

	it("still offers a selectable value when the lookup fails", () => {
		// R18. `return []` hands the user an empty menu on a field the ledger will
		// fill anyway: the bill posts either way, but the screen has stopped saying
		// where the money goes, and a lookup outage is not something the user can
		// fix. Expenses.vue already keeps the one always-valid row; this screen
		// returned nothing. The real branch is evaluated, not its spelling.
		const failure = catchBlock(fn(invoiceCode, "searchTenders"));
		const sent = (tender, label, cached) =>
			new Function(
				"err",
				"toast",
				"t",
				"form",
				"overheadDeal",
				failure,
			)(
				new Error("boom"),
				{ error: () => {} },
				(key) => key,
				{ value: { tender, tender_label: label } },
				{ value: cached },
			);

		// An existing bill: the tender it already carries stays pickable.
		expect(sent("DEAL-9", "Ministry of Roads", null)).toEqual([
			{ name: "DEAL-9", label: "Ministry of Roads", is_overhead: 0 },
		]);
		// A new bill: GENEL GİDER, which is where the server books it anyway.
		expect(sent("", "", { name: "OVH-1", organization: "GENEL GİDER" })).toEqual([
			{ name: "OVH-1", label: "GENEL GİDER", is_overhead: 1 },
		]);
		// Nothing known yet is the only case where an empty menu is honest.
		expect(sent("", "", null)).toEqual([]);
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
