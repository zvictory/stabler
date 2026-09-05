import { describe, expect, it } from "vitest";
import { readFileSync } from "fs";
import { dirname, resolve } from "path";
import { fileURLToPath } from "url";
import { nextTick, reactive, ref, watch } from "vue";

const here = dirname(fileURLToPath(import.meta.url));
const src = readFileSync(resolve(here, "../pages/purchasing/PurchaseOrderForm.vue"), "utf8");

/**
 * KOP-07 (docs/uat/tender/02-tender-uzmani.md:1027): `Purchase Order.custom_crm_deal`
 * is what puts a PO on the Tender PO control board (tender.py:515,538), and the
 * backend `create_purchase_order` already accepts a `deal` arg and writes it
 * (purchasing.py:1997-2004, guarded on the v34 column). But no SPA screen that
 * creates a PO ever sent it — the only writer in the whole SPA was the sourcing
 * bridge `create_po_from_quotation`. A purchaser opening a PO the normal way could
 * never attach it to its tender, and it would never appear on the control board.
 *
 * Same shape as manufacturingTabGates.spec.js: the source is EXECUTED, not
 * grepped, because a `toContain("deal")` assertion passes just as happily on a
 * gate wired backwards (e.g. sending `deal` regardless of whether `tender` is
 * even enabled for the company) as it does on a correct one.
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
	// `async function NAME(` first: plain `indexOf("function NAME(")` also matches
	// inside that text (just past the "async " keyword), which would silently
	// drop "async" from the lifted source and turn a body that awaits something
	// into a syntax error the moment `new Function` tries to compile it.
	let at = src.indexOf(`async function ${name}(`);
	if (at === -1) at = src.indexOf(`function ${name}(`);
	expect(at, `${name} is gone — has it moved or been renamed?`).toBeGreaterThan(-1);
	const braceStart = src.indexOf("{", at);
	const body = braceMatched(braceStart);
	return src.slice(at, braceStart) + body;
}

// toPayload closes over module-scope refs (`activeCompany`, `autoSubmit`) and,
// with the fix, `tenderOn` too — supply stand-ins the same way
// manufacturingTabGates.spec.js stands in for `session`/`t`.
function buildToPayload(tenderOnValue) {
	const literal = extractFunction("toPayload");
	const factory = new Function(
		"tenderOn",
		"activeCompany",
		"autoSubmit",
		`${literal}\nreturn toPayload;`
	);
	return factory({ value: tenderOnValue }, { value: "Mikas" }, { value: 1 });
}

function buildResolveDealFromQuery() {
	const literal = extractFunction("resolveDealFromQuery");
	const factory = new Function(`${literal}\nreturn resolveDealFromQuery;`);
	return factory();
}

function buildDealOptionLabel() {
	const literal = extractFunction("dealOptionLabel");
	const factory = new Function(`${literal}\nreturn dealOptionLabel;`);
	return factory();
}

// P3: `queryDealApplied` is instance-scoped and App.vue renders `<router-view>`
// with no `:key`, so navigating from one `?deal=` link to another re-uses this
// component instance — the latch must re-open when the query param itself
// changes to a different value. Extracted (not hand-rolled) so the test
// exercises the exact watcher the fix registers, brace/paren-matched the same
// way `extractFunction` lifts a function body.
function extractDealQueryWatch() {
	const at = src.indexOf("watch(() => route.query?.deal");
	expect(at, "the route-query deal watcher is gone — has it moved or been renamed?").toBeGreaterThan(-1);
	const parenStart = src.indexOf("(", at);
	let depth = 0;
	for (let i = parenStart; i < src.length; i++) {
		if (src[i] === "(") depth++;
		else if (src[i] === ")" && --depth === 0) return src.slice(at, i + 1) + ";";
	}
	throw new Error("unterminated watch(() => route.query?.deal ...)");
}

// Models the real onMounted/watch sequence for UAT G.7: `tenderOn` is a
// `computed` over session module data that is not always resolved by the time
// this component mounts, so `applyQueryDeal` has to be re-runnable — once,
// correctly — rather than a single snapshot read taken at mount. Built with
// REAL `ref`/`watch` from "vue" (a real dependency here), not a hand-rolled
// stand-in for Vue's own reactivity, so the test exercises the exact
// `watch(tenderOn, applyQueryDeal)` wiring the fix registers.
function buildQueryDealHarness({
	tenderOnValue,
	queryDeal,
	docNameValue = null,
	createFormReadyValue = true,
}) {
	const resolveLiteral = extractFunction("resolveDealFromQuery");
	const applyLiteral = extractFunction("applyQueryDeal");
	const watchAt = src.indexOf("watch(tenderOn, applyQueryDeal)");
	expect(watchAt, "the tenderOn watcher is gone — has it moved or been renamed?").toBeGreaterThan(-1);
	const dealQueryWatchLiteral = extractDealQueryWatch();

	const docName = ref(docNameValue);
	const form = ref({ deal: "" });
	const tenderOn = ref(tenderOnValue);
	// `reactive`, not a plain object: the fix's `watch(() => route.query?.deal, ...)`
	// needs a real reactive dependency to trigger on, same as vue-router's own
	// `route` — a plain object mutation would be invisible to Vue's watcher.
	const route = reactive({ query: { deal: queryDeal } });
	const labelCalls = [];
	async function loadDealLabel(dealName) {
		labelCalls.push(dealName);
	}

	// `createFormReadyValue` defaults to true: every existing caller here treats
	// `h.applyQueryDeal()` as "the onMounted call" firing the instant the create
	// branch has already run `form.value = blankForm()`. Only the Promise.all
	// race test below needs the form to start NOT ready, so it can model the
	// watcher firing before that branch has run at all.
	const factory = new Function(
		"docName",
		"form",
		"tenderOn",
		"route",
		"loadDealLabel",
		"watch",
		"createFormReadyValue",
		`let queryDealApplied = false;\nlet createFormReady = createFormReadyValue;\n${resolveLiteral}\n${applyLiteral}\nwatch(tenderOn, applyQueryDeal);\n${dealQueryWatchLiteral}\nreturn { applyQueryDeal, markFormReplaced: () => { form.value = { deal: "" }; createFormReady = true; } };`
	);
	const { applyQueryDeal, markFormReplaced } = factory(
		docName,
		form,
		tenderOn,
		route,
		loadDealLabel,
		watch,
		createFormReadyValue
	);
	return { docName, form, tenderOn, route, applyQueryDeal, markFormReplaced, labelCalls };
}

const baseModel = () => ({
	supplier: "SUP-0001",
	set_warehouse: "",
	transaction_date: "2026-08-27",
	schedule_date: "2026-08-27",
	remarks: "",
	items: [{ item_code: "ITEM-1", qty: 1, rate: 10 }],
	currency: "",
	price_list: "",
});

describe("PurchaseOrderForm carries a tender lot to create_purchase_order (KOP-07)", () => {
	it("sends the picked deal when the tender module is on", () => {
		const toPayload = buildToPayload(true);
		const payload = toPayload({ ...baseModel(), deal: "CRM-DEAL-2026-00107" });
		expect(payload.deal).toBe("CRM-DEAL-2026-00107");
	});

	it("sends nothing when no deal was picked", () => {
		const toPayload = buildToPayload(true);
		const payload = toPayload({ ...baseModel(), deal: "" });
		expect(payload.deal).toBeUndefined();
	});

	// The invisibility requirement: even if a `deal` somehow ended up on the
	// model (stale state, a company switch mid-edit), a tenant with the tender
	// module OFF must never have it leave the browser.
	it("never sends a deal when the tender module is off, even if one is set", () => {
		const toPayload = buildToPayload(false);
		const payload = toPayload({ ...baseModel(), deal: "CRM-DEAL-2026-00107" });
		expect(payload.deal).toBeUndefined();
	});
});

// Review follow-up (P1): without `active_tenders: 1`, `list_deals` takes the
// all-deals branch (`_crm_list`, search_fields organization/email/lead_name) —
// the id-search fix landed only in `list_active_tenders`, which this picker
// never reaches without the flag — and offers every Standard deal on the
// board, not just active tenders. Same shape as tenderDimension.spec.js:91
// for Expenses.vue's searchDeals.
describe("PurchaseOrderForm's deal picker only offers active tenders (P1)", () => {
	it("asks for active tenders, not for every deal on the CRM board", () => {
		expect(extractFunction("searchDeals")).toContain("active_tenders: 1");
	});
});

describe("PurchaseOrderForm prefills ?deal= from a tender screen (module-gated)", () => {
	it("prefills the deal from the query string when tender is on", () => {
		const resolveDealFromQuery = buildResolveDealFromQuery();
		expect(resolveDealFromQuery("CRM-DEAL-2026-00107", true)).toBe("CRM-DEAL-2026-00107");
	});

	it("ignores ?deal= entirely when the tender module is off", () => {
		const resolveDealFromQuery = buildResolveDealFromQuery();
		expect(resolveDealFromQuery("CRM-DEAL-2026-00107", false)).toBe("");
	});

	it("is blank with no query param", () => {
		const resolveDealFromQuery = buildResolveDealFromQuery();
		expect(resolveDealFromQuery(undefined, true)).toBe("");
	});
});

// UAT G.7: five deals of one buyer all rendered as "Mikas Savdo" — the label
// read only `organization`/`lead_name`, never the one field that is always
// unique, the deal's own id. Pinned as one function because both the search
// dropdown (`searchDeals`) and the locked/read-only label (`loadDealLabel`)
// must render the SAME string for the SAME deal.
describe("PurchaseOrderForm's deal option label distinguishes same-buyer deals", () => {
	it("appends the deal's own id after the organization, so identical buyers do not collide", () => {
		const dealOptionLabel = buildDealOptionLabel();
		expect(dealOptionLabel({ name: "CRM-DEAL-2026-00015", organization: "Mikas Savdo" })).toBe(
			"Mikas Savdo · CRM-DEAL-2026-00015"
		);
	});

	it("falls back to lead_name, with the id, when there is no organization", () => {
		const dealOptionLabel = buildDealOptionLabel();
		expect(dealOptionLabel({ name: "CRM-DEAL-2026-00016", lead_name: "Aziz Karimov" })).toBe(
			"Aziz Karimov · CRM-DEAL-2026-00016"
		);
	});

	it("falls back to the bare id when neither organization nor lead_name is set", () => {
		const dealOptionLabel = buildDealOptionLabel();
		expect(dealOptionLabel({ name: "CRM-DEAL-2026-00017" })).toBe("CRM-DEAL-2026-00017");
	});
});

// UAT G.7: opening `/purchasing/orders/new?deal=CRM-DEAL-2026-…` showed no deal
// in the picker. `tenderOn` is a `computed` over session module data that is
// not always resolved by the time this component mounts — the boot company and
// the SPA's active company need not be the same on the very first render — so
// a query deal read while tenderOn still read false must not be lost once the
// flag settles true.
describe("PurchaseOrderForm applies ?deal= once tenderOn is known, even when it arrives late", () => {
	it("applies immediately when tenderOn is already true at mount", async () => {
		const h = buildQueryDealHarness({ tenderOnValue: true, queryDeal: "CRM-DEAL-2026-00107" });
		await h.applyQueryDeal(); // the onMounted call
		expect(h.form.value.deal).toBe("CRM-DEAL-2026-00107");
		expect(h.labelCalls).toEqual(["CRM-DEAL-2026-00107"]);
	});

	it("applies once tenderOn flips true AFTER mount — the module flag arriving late", async () => {
		const h = buildQueryDealHarness({ tenderOnValue: false, queryDeal: "CRM-DEAL-2026-00107" });
		await h.applyQueryDeal(); // the onMounted call, while tenderOn still reads false
		expect(h.form.value.deal).toBe("");
		expect(h.labelCalls).toEqual([]);

		h.tenderOn.value = true; // company modules resolve after mount
		await nextTick(); // let the watch(tenderOn, applyQueryDeal) callback run
		expect(h.form.value.deal).toBe("CRM-DEAL-2026-00107");
		expect(h.labelCalls).toEqual(["CRM-DEAL-2026-00107"]);
	});

	it("never applies while editing an existing order, even if tenderOn later turns on", async () => {
		const h = buildQueryDealHarness({
			tenderOnValue: false,
			queryDeal: "CRM-DEAL-2026-00107",
			docNameValue: "PUR-ORD-2026-00001",
		});
		await h.applyQueryDeal();
		h.tenderOn.value = true;
		await nextTick();
		expect(h.form.value.deal).toBe("");
		expect(h.labelCalls).toEqual([]);
	});

	it("applies only once: a later tenderOn flip does not re-fight a deal the user cleared", async () => {
		const h = buildQueryDealHarness({ tenderOnValue: true, queryDeal: "CRM-DEAL-2026-00107" });
		await h.applyQueryDeal();
		expect(h.form.value.deal).toBe("CRM-DEAL-2026-00107");

		h.form.value.deal = ""; // the user cleared the picker
		h.tenderOn.value = false;
		await nextTick();
		h.tenderOn.value = true; // e.g. a company switch flips it back on
		await nextTick();
		expect(h.form.value.deal).toBe("");
	});
});

// The queryDealApplied latch alone still lost the deal: onMounted's own
// `Promise.all([loadWarehouses(), loadPriceLists(), loadCurrencies()])` can
// still be pending when `tenderOn` resolves true (session boot racing it) —
// so `watch(tenderOn, applyQueryDeal)` fires and writes onto whatever
// `form.value` was BEFORE the create branch has run `form.value =
// blankForm()`. That assignment then replaces the model outright, discarding
// the deal the watcher just wrote, and the mount's own `await
// applyQueryDeal()` call finds `queryDealApplied` already latched true and
// does nothing — the `?deal=` link is lost. `createFormReady` closes that
// window: it is set only once the create branch's own `blankForm()` has run,
// so the watcher cannot write onto a model that is about to be thrown away.
describe("PurchaseOrderForm does not lose ?deal= when tenderOn flips true mid-Promise.all", () => {
	it("the watcher must not latch onto the pre-mount model; the mount call applies the deal once the form is ready", async () => {
		const h = buildQueryDealHarness({
			tenderOnValue: false,
			queryDeal: "CRM-DEAL-2026-00107",
			createFormReadyValue: false,
		});

		// tenderOn flips true while onMounted's Promise.all is still pending —
		// before the create branch has replaced form.value or marked it ready.
		h.tenderOn.value = true;
		await nextTick(); // let watch(tenderOn, applyQueryDeal) run
		expect(h.form.value.deal).toBe("");
		expect(h.labelCalls).toEqual([]);

		// Promise.all resolves; the create branch runs:
		// form.value = blankForm(); createFormReady = true;
		h.markFormReplaced();

		// onMounted's own `await applyQueryDeal()` call, now that the form is ready.
		await h.applyQueryDeal();
		expect(h.form.value.deal).toBe("CRM-DEAL-2026-00107");
		expect(h.labelCalls).toEqual(["CRM-DEAL-2026-00107"]);
	});
});

// P3: `queryDealApplied` is instance-scoped, but App.vue's `<router-view>` has
// no `:key` (App.vue:28), so navigating from `/purchasing/orders/new?deal=A` to
// `...?deal=B` reuses this same instance — the latch never re-opens and B is
// silently dropped.
describe("PurchaseOrderForm re-applies ?deal= when the query itself changes to a new deal (P3)", () => {
	it("re-opens the latch when the query deal changes to a different value", async () => {
		const h = buildQueryDealHarness({ tenderOnValue: true, queryDeal: "CRM-DEAL-2026-00107" });
		await h.applyQueryDeal(); // the onMounted call, first navigation
		expect(h.form.value.deal).toBe("CRM-DEAL-2026-00107");

		// Second navigation to the SAME route component with a DIFFERENT ?deal= —
		// router-view has no :key, so this is the same component instance seeing
		// its route props change, exactly like vue-router replaces `route.query`.
		h.route.query = { deal: "CRM-DEAL-2026-00222" };
		await nextTick();
		expect(h.form.value.deal).toBe("CRM-DEAL-2026-00222");
		expect(h.labelCalls).toEqual(["CRM-DEAL-2026-00107", "CRM-DEAL-2026-00222"]);
	});

	it("does not re-apply when the query deal is unchanged", async () => {
		const h = buildQueryDealHarness({ tenderOnValue: true, queryDeal: "CRM-DEAL-2026-00107" });
		await h.applyQueryDeal();
		h.labelCalls.length = 0;

		// A navigation that replaces the query object (vue-router does this on
		// every route change) but leaves `deal` at the same value — e.g. an
		// unrelated query param changed — must not re-fight a deal the user may
		// since have cleared.
		h.route.query = { deal: "CRM-DEAL-2026-00107", other: "x" };
		await nextTick();
		expect(h.form.value.deal).toBe("CRM-DEAL-2026-00107");
		expect(h.labelCalls).toEqual([]);
	});
});
