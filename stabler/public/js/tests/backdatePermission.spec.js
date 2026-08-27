import { describe, expect, it, vi } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { todayIso } from "../composables/date.js";

// What the fake server was asked, and what it answers. `answer` is swapped per
// test before the module under test is re-imported.
const asked = [];
let answer = () => Promise.resolve({ can_backdate: true });

vi.mock("../api/client.js", () => ({
	call: (name, args) => {
		asked.push(name);
		return answer(name, args);
	},
}));

// The answer is cached at module scope on purpose — one request per page load,
// not one per form — so each test needs its own instance of the module.
async function fresh() {
	vi.resetModules();
	asked.length = 0;
	return await import("../composables/backdate.js");
}

const settle = () => new Promise((r) => setTimeout(r, 0));

describe("backdate permission", () => {
	it("assumes the user may backdate until the server says otherwise", async () => {
		// The form renders before the answer arrives. Starting closed would
		// flash a disabled past at every user for the length of one round trip,
		// including the administrators who are allowed to use it.
		answer = () => new Promise(() => {});
		const { useCanBackdate } = await fresh();

		expect(useCanBackdate().value).toBe(true);
	});

	it("closes the past when the server refuses it", async () => {
		answer = () => Promise.resolve({ can_backdate: false });
		const { useCanBackdate } = await fresh();
		const canBackdate = useCanBackdate();

		await settle();

		expect(canBackdate.value).toBe(false);
	});

	it("leaves the past open for a user the server allows", async () => {
		answer = () => Promise.resolve({ can_backdate: true });
		const { useCanBackdate } = await fresh();
		const canBackdate = useCanBackdate();

		await settle();

		expect(canBackdate.value).toBe(true);
	});

	it("keeps backdating available when the endpoint is not installed", async () => {
		// The rule and this endpoint both live in `stable_app`, which is on
		// production and on no development bench. A site without it has no
		// backdating rule to obey; a site with it must not lose the capability
		// to a timeout. The validate hook is the source of truth either way, so
		// guessing `true` costs one honest error message, while guessing
		// `false` silently removes a permission the user really holds.
		answer = () => Promise.reject(new Error("ModuleNotFoundError: stable_app"));
		const { useCanBackdate } = await fresh();
		const canBackdate = useCanBackdate();

		await settle();

		expect(canBackdate.value).toBe(true);
	});

	it("asks the server once however many forms ask it", async () => {
		answer = () => Promise.resolve({ can_backdate: false });
		const { useCanBackdate } = await fresh();
		const first = useCanBackdate();
		const second = useCanBackdate();

		await settle();

		expect(asked).toEqual(["stable_app.api.guards.can_backdate"]);
		expect(first.value).toBe(false);
		expect(second.value).toBe(false);
	});
});

describe("useBackdateGuard", () => {
	it("hands the form a bound only once the server has refused", async () => {
		answer = () => Promise.resolve({ can_backdate: false });
		const { useBackdateGuard } = await fresh();
		const { canBackdate, minPostingDate } = useBackdateGuard();

		// Before the answer lands the calendar is open, so an administrator
		// never sees the past flicker shut on a form they may use.
		expect(minPostingDate.value).toBe("");

		await settle();

		expect(canBackdate.value).toBe(false);
		expect(minPostingDate.value).toBe(todayIso());
	});

	it("leaves the calendar open for a user the server allows", async () => {
		answer = () => Promise.resolve({ can_backdate: true });
		const { useBackdateGuard } = await fresh();
		const { minPostingDate } = useBackdateGuard();

		await settle();

		expect(minPostingDate.value).toBe("");
	});
});

describe("earliestPostingDate", () => {
	it("leaves the calendar unbounded when backdating is allowed", async () => {
		const { earliestPostingDate } = await fresh();

		expect(earliestPostingDate(true, "2026-08-27")).toBe("");
	});

	it("floors the calendar at today when it is not", async () => {
		const { earliestPostingDate } = await fresh();

		expect(earliestPostingDate(false, "2026-08-27")).toBe("2026-08-27");
	});
});

const here = dirname(fileURLToPath(import.meta.url));

const page = (rel) => readFileSync(resolve(here, "../pages/", rel), "utf8");

/** The one `<DateInput>` in `rel` bound to `field`, as written. */
function dateInput(rel, field) {
	const src = page(rel);
	const tags = src.match(
		new RegExp(`<DateInput\\b[^>]*v-model="${field.replace(".", "\\.")}"[^>]*/>`, "g"),
	);
	expect(tags, `${rel} — <DateInput v-model="${field}">`).toHaveLength(1);
	return tags[0];
}

// Every SPA date field that ends up on a doctype `stable_app` guards. The
// doctype is what decides, not the screen: `guards.BACKDATE_DOCTYPES` lists
// eight, `hooks.doc_events` binds `block_backdated_writes` to `validate` on all
// eight, and a field that reaches one of them is a field the server will refuse
// a past date on.
//
// The doctype is not always the one the screen is named after. The import
// order's advance-payment drawer posts a Payment Entry; the remittance posts a
// Journal Entry through `post_register`; the service billing queue posts either
// a Sales Invoice or a Stock Entry depending on the chosen action. Each was
// traced to its `frappe.new_doc(...)` rather than guessed from the filename.
const GUARDED = [
	["imports/ImportOrderForm.vue", "advDate", "Payment Entry"],
	["inventory/StockEntries.vue", "form.posting_date", "Stock Entry"],
	["money/Expenses.vue", "form.posting_date", "Journal Entry"],
	["money/PaymentEntryForm.vue", "form.posting_date", "Payment Entry"],
	["money/Transfers.vue", "form.posting_date", "Journal Entry"],
	["purchasing/PurchaseInvoiceForm.vue", "form.posting_date", "Purchase Invoice"],
	["purchasing/PurchaseReceipts.vue", "form.posting_date", "Purchase Receipt"],
	["remittance/NewRemittance.vue", "form.posting_date", "Journal Entry"],
	["sales/SalesOrderFormClassic.vue", "form.transaction_date", "Sales Order"],
	["sales/SalesOrderFormModern.vue", "form.transaction_date", "Sales Order"],
	["sales/SalesReturnForm.vue", "form.posting_date", "Sales Invoice"],
	["service/BillingQueue.vue", "form.posting_date", "Sales Invoice / Stock Entry"],
];

// Date fields on doctypes nothing guards. Constraining these would take away a
// capability the server grants — the same defect as offering one it refuses,
// pointed the other way, and the harder one to notice because it fails by
// silence. `ImportOrderForm.vue` appears in both tables on purpose: its order
// date is a Purchase Order's and stays open, while the advance drawer three
// hundred lines below posts a Payment Entry and does not.
const UNGUARDED = [
	["imports/ImportOrderForm.vue", "form.transaction_date", "Purchase Order"],
	["purchasing/PurchaseOrderForm.vue", "form.transaction_date", "Purchase Order"],
	["sales/QuotationForm.vue", "form.transaction_date", "Quotation"],
	["sfa/VanStock.vue", "form.posting_date", "Van Stock"],
];

describe("the date fields that reach a guarded doctype", () => {
	// `set_posting_time = 1` (inventory.py, 2026-08-27) is what made this
	// urgent: the operator's chosen date now survives to `validate` instead of
	// being reset in silence, so the guard refuses submissions that used to
	// succeed on the wrong date. Payment Entry showed it first — three
	// refusals within minutes of the restart that deployed it.
	it.each(GUARDED)("%s — %s writes a %s", (rel, field) => {
		expect(dateInput(rel, field)).toMatch(/:min="minPostingDate"/);
	});

	it.each(GUARDED)("%s says why the past is closed", (rel) => {
		const src = page(rel);
		expect(src).toMatch(/v-if="[^"]*!canBackdate"/);
		expect(src).toContain("Only an administrator can post to an earlier date.");
	});
});

describe("the date fields nothing guards", () => {
	it.each(UNGUARDED)("%s — %s writes a %s, so it stays open", (rel, field) => {
		expect(dateInput(rel, field)).not.toMatch(/:min=/);
	});
});
