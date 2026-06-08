<script setup>
/**
 * SalesOrderForm — unified full-page create / view Sales Order.
 *
 * Routes:
 *   /sales/orders/new    → blank editable form → create_sales_order
 *   /sales/orders/:name  → fetch sales_order_detail, render read-only with
 *                          status-gated actions (Submit / Create Invoice /
 *                          Cancel / Amend / Delete).
 *
 * Replaces the old createOpen modal + detailOpen offcanvas in SalesOrders.vue.
 * Field parity (the user's acceptance gate): every field captured at create —
 * price list, order date, delivery date, per-line discount — is present in the
 * view. Post-submit fields (reserved/delivered/billed/advance) render read-only.
 *
 * Edit mode: create (no name) OR loaded Draft (docstatus=0). Submitted/cancelled
 * orders are always read-only. Edits to a Draft call update_sales_order and save
 * without submitting; the existing Submit action then does the final submit+reserve.
 */
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import FormPage from "../../components/form/FormPage.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();

const today = new Date().toISOString().slice(0, 10);

// ── Mode ──────────────────────────────────────────────────────────────
// :name present → view existing; otherwise → create new.
const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);
// Editable when creating a new order OR viewing a Draft (docstatus=0).
// Submitted / cancelled orders are always read-only.
const editable = computed(() => isCreate.value || (doc.value !== null && doc.value.docstatus === 0));

// View mode (:name present) must paint FormPage's spinner until loadDoc() resolves —
// otherwise the shared items table renders a blank row whose !editable cells deref
// null `doc.currency`, throwing in the render fn and blanking the whole page.
const loading = ref(Boolean(route.params.name));
const loadError = ref("");
const doc = ref(null); // loaded sales_order_detail (view mode); null when creating

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

// ── Lookups ───────────────────────────────────────────────────────────
const warehouses = ref([]);
const warehousesLoading = ref(false);
const priceLists = ref([]);
const currencies = ref([]);

const DEFAULT_WAREHOUSE_NAME = "tayyor mahsulot";
function defaultWarehouseName() {
	const match = warehouses.value.find(
		(w) => (w.warehouse_name || "").trim().toLowerCase() === DEFAULT_WAREHOUSE_NAME
	);
	return match ? match.name : "";
}

async function loadWarehouses() {
	if (!activeCompany.value) return;
	warehousesLoading.value = true;
	try {
		warehouses.value = await call("stabler.api.inventory.list_stock_warehouses", {
			company: activeCompany.value,
		});
	} catch {
		warehouses.value = [];
	} finally {
		warehousesLoading.value = false;
	}
}
async function loadPriceLists() {
	try {
		priceLists.value = await call("stabler.api.sales.list_selling_price_lists");
	} catch {
		priceLists.value = [];
	}
}
async function loadCurrencies() {
	try {
		currencies.value = await call("stabler.api.sales.list_currencies");
	} catch {
		currencies.value = [];
	}
}

// ── Form model (shared by create + view) ──────────────────────────────
function blankLine() {
	return {
		item_code: "",
		item_name: "",
		uom: "",
		stock_uom: "",
		uoms: [],
		conversion_factor: 1,
		qty: 1,
		rate: 0,
		rateTouched: false, // true when user has manually edited the rate; prevents onUomChange overwrite
		discount_percentage: 0,
		discount_amount: 0,
		warehouse: "",
		availability: null,
		availabilityLoading: false,
		// read-only extras populated in view mode:
		reserved_qty: 0,
		delivered_qty: 0,
		price_list_rate: 0,
		amount: 0,
	};
}
function blankForm() {
	return {
		customer: "",
		customer_name: "",
		currency: "",
		price_list: "",
		set_warehouse: "",
		transaction_date: today,
		remarks: "",
		items: [blankLine()],
	};
}
const form = ref(blankForm());
const showDiscounts = ref(false);

const currencySymbol = computed(() => {
	const code = form.value.currency || currency.value;
	return (currencies.value.find((c) => c.name === code) || {}).symbol || "";
});

function lineAmount(line) {
	const qty = Number(line.qty || 0);
	const rate = Number(line.rate || 0);
	const discPct = Number(line.discount_percentage || 0);
	const discAmt = Number(line.discount_amount || 0);
	if (discPct > 0) return qty * Math.max(rate * (1 - discPct / 100), 0);
	if (discAmt > 0) return qty * Math.max(rate - discAmt, 0);
	return qty * rate;
}

const createTotal = computed(() =>
	form.value.items.reduce((s, r) => s + lineAmount(r), 0)
);
const totalsByUom = computed(() => {
	const map = new Map();
	for (const line of form.value.items) {
		if (!line.qty || !line.uom) continue;
		map.set(line.uom, (map.get(line.uom) || 0) + Number(line.qty));
	}
	return [...map.entries()];
});

function factorFor(line, uom) {
	const entry = (line.uoms || []).find((u) => u.uom === uom);
	return entry ? Number(entry.conversion_factor) || 1 : 1;
}
function isKorobkaUom(uom) {
	const name = String(uom || "").trim().toLowerCase();
	return name.includes("korobka") || name.includes("короб");
}
function preferredSalesUom(meta) {
	const uoms = meta.uoms || [];
	const korobka = uoms.find((u) => isKorobkaUom(u.uom));
	if (korobka) return korobka;
	const boxUom = uoms
		.filter((u) => u.uom !== meta.stock_uom && Number(u.conversion_factor) > 1)
		.sort((a, b) => Number(b.conversion_factor) - Number(a.conversion_factor))[0];
	return boxUom || uoms.find((u) => u.uom === (meta.default_uom || meta.stock_uom)) || null;
}
async function onUomChange(line) {
	line.conversion_factor = factorFor(line, line.uom);
	// Only auto-resolve the rate on UOM change when the user hasn't manually
	// overridden it. rateTouched is set by the MoneyInput @input handler.
	if (line.item_code && !line.rateTouched) {
		const { rate } = await resolveRate(line.item_code, line.rate, line.uom);
		line.rate = rate;
	}
}
function setLineUom(line, uom) {
	if (line.uom === uom) return;
	line.uom = uom;
	onUomChange(line);
}

// ── Customer / item pickers ───────────────────────────────────────────
function searchCustomers(q) {
	return call("stabler.api.sales.list_customers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}
async function pickCustomer(c) {
	form.value.customer = c.name;
	form.value.customer_name = c.customer_name;
	try {
		const defaults = await call("stabler.api.sales.get_customer_defaults", {
			company: activeCompany.value,
			customer: c.name,
		});
		form.value.currency = defaults.default_currency || "";
		form.value.price_list = defaults.resolved_price_list || "";
	} catch {
		// non-fatal
	}
}
function clearCustomer() {
	form.value.customer = "";
	form.value.customer_name = "";
	form.value.currency = "";
	form.value.price_list = "";
}

function searchItems(q) {
	return call("stabler.api.inventory.list_items", {
		search: q,
		warehouse: form.value.set_warehouse || undefined,
		limit: 30,
	});
}
async function resolveRate(itemCode, fallback = 0, uom = undefined) {
	if (!itemCode || !activeCompany.value) return { rate: Number(fallback || 0) };
	try {
		const res = await call("stabler.api.sales.get_item_price", {
			item_code: itemCode,
			company: activeCompany.value,
			customer: form.value.customer || undefined,
			price_list: form.value.price_list || undefined,
			uom: uom || undefined,
		});
		if (res && !res.unresolved && Number(res.price_list_rate) > 0) {
			return { rate: Number(res.price_list_rate) };
		}
		return { rate: Number(fallback || 0) };
	} catch {
		return { rate: Number(fallback || 0) };
	}
}
async function refreshLineRatesForPriceList() {
	const lines = form.value.items.filter((line) => line.item_code && !line.rateTouched);
	for (const line of lines) {
		const { rate } = await resolveRate(line.item_code, line.rate, line.uom);
		if (rate) line.rate = rate;
	}
}
async function pickItem(line, item) {
	line.item_code = item.item_code || item.name;
	line.item_name = item.item_name;
	if (!line.warehouse) line.warehouse = form.value.set_warehouse;
	try {
		const meta = await call("stabler.api.sales.item_sales_meta", {
			item_code: line.item_code,
			company: activeCompany.value,
			customer: form.value.customer || undefined,
			price_list: form.value.price_list || undefined,
		});
		line.stock_uom = meta.stock_uom || "";
		line.uoms = meta.uoms || [];
		const preferredUom = preferredSalesUom(meta);
		line.uom = preferredUom ? preferredUom.uom : (meta.default_uom || meta.stock_uom || "");
		line.conversion_factor = factorFor(line, line.uom);
		line.rateTouched = false; // fresh pick — allow auto-rate on UOM change
		// If we defaulted to a non-default UOM, resolve that UOM's price from the price list.
		if (preferredUom && preferredUom.uom !== meta.default_uom && form.value.price_list) {
			const { rate } = await resolveRate(line.item_code, meta.price_list_rate || meta.standard_rate || 0, line.uom);
			line.rate = rate;
		} else {
			line.rate = Number(meta.price_list_rate || meta.standard_rate || 0);
		}
	} catch {
		line.uom = item.stock_uom || "";
		line.stock_uom = item.stock_uom || "";
		line.uoms = [];
		line.conversion_factor = 1;
		const { rate } = await resolveRate(line.item_code, item.standard_rate);
		line.rate = rate;
	}
	scheduleAvailability(line);
}
function clearItem(line) {
	line.item_code = "";
	line.item_name = "";
	line.uom = "";
	line.stock_uom = "";
	line.uoms = [];
	line.conversion_factor = 1;
	line.rate = 0;
	line.discount_percentage = 0;
	line.discount_amount = 0;
	line.availability = null;
}

// ── Per-line availability (debounced 200ms) ───────────────────────────
const _availabilityTimers = new WeakMap();
function scheduleAvailability(line) {
	const prev = _availabilityTimers.get(line);
	if (prev) clearTimeout(prev);
	if (!line.item_code || !line.warehouse) {
		line.availability = null;
		return;
	}
	const handle = setTimeout(() => loadAvailability(line), 200);
	_availabilityTimers.set(line, handle);
}
async function loadAvailability(line) {
	if (!line.item_code || !line.warehouse) return;
	line.availabilityLoading = true;
	try {
		line.availability = await call("stabler.api.inventory.item_availability", {
			item_code: line.item_code,
			warehouse: line.warehouse,
		});
	} catch {
		line.availability = null;
	} finally {
		line.availabilityLoading = false;
	}
}
function lineStockQty(line) {
	return Number(line.qty || 0) * Number(line.conversion_factor || 1);
}
function isOverAvailable(line) {
	if (!line.item_code || !line.availability) return false;
	return lineStockQty(line) > Number(line.availability.free || 0);
}
function availabilityTone(line) {
	if (!line.availability) return "bg-secondary-lt";
	return isOverAvailable(line) ? "bg-red-lt" : "bg-green-lt";
}
const overAvailableRows = computed(() =>
	form.value.items
		.map((line, i) => ({ line, i }))
		.filter(({ line }) => line.item_code && isOverAvailable(line))
);
const hasOverAvailable = computed(() => overAvailableRows.value.length > 0);

// Re-resolve rates + defaults when the customer changes (create only).
watch(
	() => form.value.customer,
	async (customer) => {
		if (!isCreate.value || !customer) return;
		await refreshLineRatesForPriceList();
	}
);
watch(
	() => form.value.price_list,
	async () => {
		if (!editable.value) return;
		await refreshLineRatesForPriceList();
	}
);
// Propagate the header warehouse to lines (create only).
watch(
	() => form.value.set_warehouse,
	(now, was) => {
		if (!isCreate.value) return;
		for (const line of form.value.items) {
			if (!line.warehouse || line.warehouse === was) {
				line.warehouse = now;
				scheduleAvailability(line);
			}
		}
	}
);

function addLine() {
	const l = blankLine();
	l.warehouse = form.value.set_warehouse;
	form.value.items.push(l);
}
function onRowTab(idx, field, event) {
	const lastField = showDiscounts.value ? "disc" : "rate";
	if (field !== lastField) return;
	if (idx !== form.value.items.length - 1) return;
	event.preventDefault();
	addLine();
	nextTick(() => {
		const rows = document.querySelectorAll("tr.so-line-row");
		rows[rows.length - 1]?.querySelector("input")?.focus();
	});
}
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		form.value.items[0].warehouse = form.value.set_warehouse;
		return;
	}
	form.value.items.splice(idx, 1);
}

// ── Pipeline stepper ──────────────────────────────────────────────────
// Returns the single furthest-reached stage (2..4). The Quotation stage (1) is always
// behind us — this form only ever renders a Sales Order. The template marks ONE step
// `.active` (=== this value); Tabler fills 1..active and grays the rest.
function pipelineStage(d) {
	if (!d) return 2;
	const delivered = Number(d.per_delivered) || 0;
	const billed = Number(d.per_billed) || 0;
	const invoiced = (d.sales_invoices || []).some((si) => Number(si.docstatus) === 1);
	// We sell from warehouse (no separate Delivery Note): a submitted Sales Invoice means
	// goods are gone AND billed, so the pipeline reaches Invoice and Deliver is implicitly done.
	if (invoiced || billed >= 100) return 4;
	if (delivered > 0 || billed > 0) return 3;
	return 2;
}

// Payment is orthogonal to fulfillment (ERPNext bills ≠ collects). Aggregate the
// outstanding across all SUBMITTED linked invoices; null = nothing invoiced yet (no badge).
const paymentBadge = computed(() => {
	const sis = (doc.value?.sales_invoices || []).filter((si) => Number(si.docstatus) === 1);
	if (!sis.length) return null;
	const grand = sis.reduce((s, si) => s + (Number(si.grand_total) || 0), 0);
	const due = sis.reduce((s, si) => s + (Number(si.outstanding_amount) || 0), 0);
	if (due <= 0.005) return { label: t("Paid"), cls: "bg-green-lt", icon: "ti-check" };
	if (due >= grand - 0.005) return { label: t("Unpaid"), cls: "bg-red-lt", icon: "ti-clock" };
	return { label: t("Partly paid"), cls: "bg-yellow-lt", icon: "ti-progress" };
});

// ── Load existing doc (view mode) ─────────────────────────────────────
function mapDetailToForm(d) {
	form.value = {
		customer: d.customer,
		customer_name: d.customer_name,
		currency: d.currency || "",
		price_list: d.selling_price_list || "",
		set_warehouse: d.set_warehouse || "",
		transaction_date: d.transaction_date || "",
		delivery_date: d.delivery_date || "",
		remarks: d.remarks || "",
		items: (d.items || []).map((it) => ({
			item_code: it.item_code,
			item_name: it.item_name,
			uom: it.uom || "",
			stock_uom: it.stock_uom || "",
			uoms: [], // populated by loadDraftUoms() when editing a Draft
			conversion_factor: Number(it.conversion_factor) || 1,
			qty: it.qty,
			rate: it.rate,
			rateTouched: false, // user has not manually edited this rate
			discount_percentage: it.discount_percentage || 0,
			discount_amount: it.discount_amount || 0,
			warehouse: it.warehouse || "",
			availability: null,
			availabilityLoading: false,
			reserved_qty: it.reserved_qty || 0,
			delivered_qty: it.delivered_qty || 0,
			price_list_rate: it.price_list_rate || 0,
			amount: it.amount || 0,
		})),
	};
	// Surface discount columns if any line carries a discount (parity).
	showDiscounts.value = form.value.items.some(
		(l) => Number(l.discount_percentage) > 0 || Number(l.discount_amount) > 0
	);
}

async function loadDraftUoms() {
	// Populate UOM lists per line so the UOM toggle works when editing a Draft.
	// item_sales_meta is the same call pickItem() uses — reuse it here in parallel.
	await Promise.all(
		form.value.items
			.filter((l) => l.item_code)
			.map(async (l) => {
				try {
					const meta = await call("stabler.api.sales.item_sales_meta", {
						item_code: l.item_code,
						company: activeCompany.value,
						customer: form.value.customer || undefined,
						price_list: form.value.price_list || undefined,
					});
					l.stock_uom = meta.stock_uom || l.stock_uom;
					l.uoms = meta.uoms || [];
				} catch {
					// non-fatal — the UOM toggle simply stays hidden for this line
				}
			})
	);
}

async function loadDoc() {
	if (!docName.value) return;
	loading.value = true;
	loadError.value = "";
	try {
		const d = await call("stabler.api.sales.sales_order_detail", { name: docName.value });
		doc.value = d;
		mapDetailToForm(d);
		// Load UOM lists for draft items so the UOM toggle works in edit mode.
		if (d.docstatus === 0) await loadDraftUoms();
	} catch (err) {
		loadError.value = err?.message || t("Failed to load sales order.");
	} finally {
		loading.value = false;
	}
}

// ── Actions ───────────────────────────────────────────────────────────
const actionRunning = ref(false);
const actionError = ref("");
const submitError = ref("");
const lastReservationErrors = ref([]);

const canSubmit = computed(() => !!doc.value && doc.value.docstatus === 0);
const canCancel = computed(() => !!doc.value && doc.value.docstatus === 1);
const canCreateInvoice = computed(
	() =>
		!!doc.value &&
		doc.value.docstatus === 1 &&
		!(doc.value.sales_invoices && doc.value.sales_invoices.length)
);
const canAmend = computed(() => !!doc.value && doc.value.docstatus === 2);
const canDelete = computed(() => !!doc.value && doc.value.docstatus === 0);

async function submitCreate({ autoSubmit = 1 } = {}) {
	submitError.value = "";
	if (!form.value.customer) {
		submitError.value = t("Pick a customer.");
		return;
	}
	if (!form.value.set_warehouse) {
		submitError.value = t("Pick a warehouse.");
		return;
	}
	const lines = form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			qty: r.qty,
			rate: r.rate,
			uom: r.uom,
			conversion_factor: r.conversion_factor || 1,
			discount_percentage: r.discount_percentage || 0,
			discount_amount: r.discount_amount || 0,
			warehouse: r.warehouse || form.value.set_warehouse,
		}));
	if (!lines.length) {
		submitError.value = t("Add at least one item line.");
		return;
	}
	for (const [i, r] of lines.entries()) {
		if (!Number(r.qty) || Number(r.qty) <= 0) {
			submitError.value = t("Row {n}: qty must be greater than zero.", { n: i + 1 });
			return;
		}
	}
	await Promise.all(
		form.value.items
			.filter((l) => l.item_code && l.warehouse && !l.availability)
			.map((l) => loadAvailability(l))
	);
	const overRows = form.value.items
		.map((line, i) => ({ line, i }))
		.filter(({ line }) => line.item_code && isOverAvailable(line));
	if (autoSubmit && overRows.length) {
		const { line, i } = overRows[0];
		submitError.value = t(
			"Row {n} ({item}): qty exceeds available stock (available {free}).",
			{ n: i + 1, item: line.item_name || line.item_code, free: Number(line.availability.free).toFixed(2) }
		);
		return;
	}
	actionRunning.value = true;
	try {
		const created = await call("stabler.api.sales.create_sales_order", {
			company: activeCompany.value,
			customer: form.value.customer,
			set_warehouse: form.value.set_warehouse,
			transaction_date: form.value.transaction_date,
			remarks: form.value.remarks || undefined,
			items: lines,
			auto_submit: autoSubmit,
			currency: form.value.currency || undefined,
			price_list: form.value.price_list || undefined,
		});
		if (created?.name) {
			router.push("/sales/orders/" + created.name);
		}
	} catch (err) {
		submitError.value = err?.message || t("Failed to create sales order.");
	} finally {
		actionRunning.value = false;
	}
}

async function submitDoc() {
	if (!doc.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.submit_sales_order", { name: doc.value.name });
		lastReservationErrors.value = res?.reservation_errors || [];
		await loadDoc();
	} catch (err) {
		actionError.value = err?.message || t("Submit failed.");
	} finally {
		actionRunning.value = false;
	}
}
async function cancelDoc() {
	if (!doc.value?.name) return;
	if (!window.confirm(t("Cancel sales order {name}? Stock reservations will be released.", { name: doc.value.name }))) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.cancel_sales_order", { name: doc.value.name });
		lastReservationErrors.value = [];
		await loadDoc();
	} catch (err) {
		actionError.value = err?.message || t("Cancel failed.");
	} finally {
		actionRunning.value = false;
	}
}
async function createInvoice() {
	if (!doc.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.create_sales_invoice", {
			sales_order: doc.value.name,
		});
		if (res?.name) {
			router.push("/sales/invoices/" + res.name);
		}
	} catch (err) {
		actionError.value = err?.message || t("Failed to create invoice.");
	} finally {
		actionRunning.value = false;
	}
}
async function amendDoc() {
	if (!doc.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.amend_sales_order", { name: doc.value.name });
		if (res?.name) router.push("/sales/orders/" + res.name);
	} catch (err) {
		actionError.value = err?.message || t("Amend failed.");
	} finally {
		actionRunning.value = false;
	}
}
async function deleteDoc() {
	if (!doc.value?.name) return;
	if (!window.confirm(t("Delete order {name}? This cannot be undone.", { name: doc.value.name }))) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.delete_sales_order", { name: doc.value.name });
		router.push("/sales/orders");
	} catch (err) {
		actionError.value = err?.message || t("Delete failed.");
	} finally {
		actionRunning.value = false;
	}
}

async function saveDraft() {
	// Persist edits to an existing Draft without submitting/reserving stock.
	if (!doc.value?.name) return;
	actionError.value = "";
	if (!form.value.customer) { actionError.value = t("Pick a customer."); return; }
	if (!form.value.set_warehouse) { actionError.value = t("Pick a warehouse."); return; }
	const lines = form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			qty: r.qty,
			rate: r.rate,
			uom: r.uom,
			conversion_factor: r.conversion_factor || 1,
			discount_percentage: r.discount_percentage || 0,
			discount_amount: r.discount_amount || 0,
			warehouse: r.warehouse || form.value.set_warehouse,
		}));
	if (!lines.length) { actionError.value = t("Add at least one item line."); return; }
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.update_sales_order", {
			name: doc.value.name,
			items: lines,
			set_warehouse: form.value.set_warehouse,
			transaction_date: form.value.transaction_date,
			delivery_date: form.value.delivery_date || form.value.transaction_date,
			remarks: form.value.remarks || undefined,
			currency: form.value.currency || undefined,
			price_list: form.value.price_list || undefined,
		});
		await loadDoc(); // refresh with server-computed totals
	} catch (err) {
		actionError.value = err?.message || t("Save failed.");
	} finally {
		actionRunning.value = false;
	}
}

// ── Mount ─────────────────────────────────────────────────────────────
async function prefillNewForCustomer(name) {
	try {
		const [cdata, defaults] = await Promise.all([
			call("stabler.api.sales.get_customer", { name }),
			call("stabler.api.sales.get_customer_defaults", {
				company: activeCompany.value,
				customer: name,
			}),
		]);
		form.value.customer = cdata.name;
		form.value.customer_name = cdata.customer_name;
		form.value.currency = defaults.default_currency || "";
		form.value.price_list = defaults.resolved_price_list || "";
	} catch {
		// non-fatal
	}
}

// Reload whenever the :name param changes — navigating /orders/new → /orders/:name
// after create reuses this component instance, so onMounted alone won't refetch.
watch(docName, loadDoc);

onMounted(async () => {
	await Promise.all([loadWarehouses(), loadPriceLists(), loadCurrencies()]);
	if (isCreate.value) {
		form.value = blankForm();
		form.value.set_warehouse = defaultWarehouseName();
		const newFor = route.query?.new_for;
		if (newFor) await prefillNewForCustomer(String(newFor));
	} else {
		await loadDoc();
	}
});
</script>

<template>
	<FormPage
		:title="isCreate ? t('New Sales Order') : t('Sales Order')"
		:doc-name="doc?.name || null"
		:status="doc?.status || null"
		:docstatus="doc?.docstatus ?? null"
		:loading="loading"
		:error="loadError"
		back-path="/sales/orders"
	>
		<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
		<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>

		<!-- Pipeline stepper + reservation badge (view mode) -->
		<div v-if="!isCreate && doc" class="mb-4">
			<div class="d-flex align-items-center gap-2 mb-3">
				<span class="text-secondary">{{ doc.customer_name }}</span>
				<span v-if="doc.has_reservations" class="badge bg-green-lt">
					<i class="ti ti-lock me-1"></i>{{ t("Reserved") }}
				</span>
				<span v-if="paymentBadge" class="badge" :class="paymentBadge.cls">
					<i class="ti me-1" :class="paymentBadge.icon"></i>{{ paymentBadge.label }}
				</span>
			</div>
			<ul class="steps steps-counter mb-0">
				<li class="step-item" :class="{ active: pipelineStage(doc) === 1 }">{{ t("Quotation") }}</li>
				<li class="step-item" :class="{ active: pipelineStage(doc) === 2 }">{{ t("Sales Order") }}</li>
				<li class="step-item" :class="{ active: pipelineStage(doc) === 3 }">{{ t("Deliver") }}</li>
				<li class="step-item" :class="{ active: pipelineStage(doc) === 4 }">{{ t("Invoice") }}</li>
			</ul>
		</div>

		<div v-if="lastReservationErrors.length" class="alert alert-warning">
			<div class="fw-semibold mb-1">
				<i class="ti ti-alert-triangle me-1"></i>{{ t("Some lines could not be reserved") }}
			</div>
			<ul class="mb-0 ps-3 small">
				<li v-for="(e, i) in lastReservationErrors" :key="i">
					<span v-if="e.item" class="font-monospace">{{ e.item }}</span>
					<span v-if="e.line"> · {{ t("line") }} {{ e.line }}</span>
					<span v-if="e.error"> — {{ e.error }}</span>
				</li>
			</ul>
		</div>

		<div v-if="doc?.sales_invoices && doc.sales_invoices.length" class="alert alert-info">
			<div class="fw-semibold mb-1"><i class="ti ti-link me-1"></i>{{ t("Linked invoices") }}</div>
			<div class="small">
				<router-link
					v-for="si in doc.sales_invoices"
					:key="si.name"
					:to="'/sales/invoices/' + si.name"
					class="badge bg-blue-lt me-1 font-monospace text-decoration-none"
				>{{ si.name }}</router-link>
			</div>
		</div>

		<!-- ── Header fields ── -->
		<div class="row g-3 mb-3">
			<div class="col-md-6">
				<label class="form-label" :class="{ required: editable }">{{ t("Customer") }}</label>
				<Typeahead
					v-if="editable"
					v-model="form.customer"
					:search="searchCustomers"
					:display="form.customer_name"
					:placeholder="t('Search customer name…')"
					:no-results-text="t('No customers match that name')"
					open-on-focus
					@pick="pickCustomer"
					@clear="clearCustomer"
				>
					<template #option="{ item }">
						<div class="d-flex align-items-center gap-2">
							<span class="avatar avatar-xs bg-purple-lt">{{ (item.customer_name || item.name).charAt(0).toUpperCase() }}</span>
							<div>
								<div class="fw-semibold">{{ item.customer_name }}</div>
								<div class="small text-secondary">{{ item.name }} · {{ item.customer_group || "—" }}</div>
							</div>
						</div>
					</template>
				</Typeahead>
				<div v-else class="form-control-plaintext fw-semibold py-1">
					{{ form.customer_name }}
					<span class="text-secondary fw-normal font-monospace small">· {{ form.customer }}</span>
				</div>
			</div>
			<div class="col-md-6">
				<label class="form-label" :class="{ required: editable }">{{ t("Warehouse") }}</label>
				<Select
					v-if="editable"
					v-model="form.set_warehouse"
					:options="warehouses"
					value-key="name"
					:disabled="warehousesLoading"
					:placeholder="warehousesLoading ? t('Loading warehouses…') : t('Pick a warehouse')"
				>
					<template #option="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
					<template #selected="{ option }">{{ option.warehouse_name }} ({{ option.name }})</template>
				</Select>
				<div v-else class="form-control-plaintext font-monospace py-1">{{ form.set_warehouse || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Order date") }}</label>
				<DateInput v-if="editable" v-model="form.transaction_date" />
				<div v-else class="form-control-plaintext py-1">{{ formatDateTime(form.transaction_date) || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Price list") }}</label>
				<Select
					v-if="editable"
					v-model="form.price_list"
					:options="priceLists"
					value-key="name"
					:placeholder="t('— auto from customer —')"
				>
					<template #option="{ option }">{{ option.name }} ({{ option.currency }})</template>
					<template #selected="{ option }">{{ option.name }} ({{ option.currency }})</template>
				</Select>
				<div v-else class="form-control-plaintext py-1">{{ form.price_list || "—" }}</div>
			</div>
			<div class="col-md-3">
				<label class="form-label">{{ t("Currency") }}</label>
				<div class="form-control-plaintext font-monospace fw-semibold py-1">
					{{ form.currency || currency }}
					<span v-if="currencySymbol" class="text-secondary fw-normal">({{ currencySymbol }})</span>
				</div>
			</div>
		</div>

		<!-- ── Read-only post-submit datagrid (view mode) ── -->
		<div v-if="!isCreate && doc" class="datagrid mb-3">
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Net total") }}</div>
				<div class="datagrid-content font-monospace">{{ formatMoney(doc.net_total, doc.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Grand total") }}</div>
				<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(doc.grand_total, doc.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Advance paid") }}</div>
				<div class="datagrid-content font-monospace">{{ formatMoney(doc.advance_paid, doc.currency, user.language) }}</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Delivered") }}</div>
				<div class="datagrid-content font-monospace">{{ Number(doc.per_delivered || 0).toFixed(0) }}%</div>
			</div>
			<div class="datagrid-item">
				<div class="datagrid-title">{{ t("Billed") }}</div>
				<div class="datagrid-content font-monospace">{{ Number(doc.per_billed || 0).toFixed(0) }}%</div>
			</div>
		</div>

		<!-- ── Items ── -->
		<div class="d-flex align-items-center mb-2">
			<h6 class="text-uppercase text-secondary small mb-0">{{ t("Items") }}</h6>
			<div class="form-check form-switch ms-auto mb-0">
				<input class="form-check-input" type="checkbox" id="soShowDisc" v-model="showDiscounts" />
				<label class="form-check-label small text-secondary" for="soShowDisc">{{ t("Show discounts") }}</label>
			</div>
		</div>
		<div class="table-responsive">
			<table class="table table-sm table-vcenter">
				<thead>
					<tr>
						<th class="text-end text-secondary" style="width: 36px">#</th>
						<th style="min-width: 220px">{{ t("Item") }}</th>
						<th style="width: 90px">{{ t("Qty") }}</th>
						<th v-if="!editable" class="text-end">{{ t("Reserved") }}</th>
						<th v-if="!editable" class="text-end">{{ t("Delivered") }}</th>
						<th style="width: 120px">{{ t("UOM") }}</th>
						<th v-if="!editable" class="text-end">{{ t("List rate") }}</th>
						<th style="width: 140px">{{ t("Rate") }}</th>
						<th v-if="showDiscounts" style="width: 70px">%</th>
						<th v-if="showDiscounts" style="width: 130px">{{ t("Disc") }}</th>
						<th class="text-end" style="width: 130px">{{ t("Amount") }}</th>
						<th v-if="editable" style="width: 40px"></th>
					</tr>
				</thead>
				<tbody>
					<template v-for="(line, idx) in form.items" :key="idx">
						<tr class="so-line-row">
							<td class="align-top text-end text-secondary font-monospace small">{{ idx + 1 }}</td>
							<td class="align-top">
								<Typeahead
									v-if="editable"
									:model-value="line.item_code"
									:search="searchItems"
									:display="line.item_name || line.item_code"
									:placeholder="t('Search item…')"
									:no-results-text="t('No items match')"
									size="sm"
									menu-min-width="280px"
									open-on-focus
									@pick="(it) => pickItem(line, it)"
									@clear="clearItem(line)"
								>
									<template #option="{ item: it }">
										<div class="fw-semibold small">{{ it.item_name }}</div>
										<div class="small text-secondary font-monospace">{{ it.item_code }} · {{ it.stock_uom || "—" }}</div>
									</template>
								</Typeahead>
								<template v-else>
									<div class="fw-semibold">{{ line.item_name || line.item_code }}</div>
									<div class="small text-secondary font-monospace">{{ line.item_code }}</div>
								</template>
								<div v-if="editable && line.item_code && line.warehouse" class="mt-1">
									<span v-if="line.availabilityLoading" class="text-secondary small">
										<span class="spinner-border spinner-border-sm me-1"></span>{{ t("Checking availability…") }}
									</span>
									<span v-else-if="line.availability" class="badge" :class="availabilityTone(line)">
										{{ t("Available") }}: {{ Number(line.availability.free).toFixed(2) }}
										({{ t("On hand") }}: {{ Number(line.availability.actual).toFixed(2) }},
										{{ t("Reserved") }}: {{ Number(line.availability.reserved).toFixed(2) }})
									</span>
								</div>
							</td>
							<td class="align-top">
								<input
									v-if="editable"
									v-model.number="line.qty"
									type="number"
									step="any"
									inputmode="decimal"
									class="form-control form-control-sm font-monospace text-end"
								/>
								<div v-else class="font-monospace text-end">{{ line.qty }}</div>
							</td>
							<td v-if="!editable" class="align-top text-end font-monospace">
								<span v-if="Number(line.reserved_qty || 0) > 0" class="badge bg-green-lt">{{ Number(line.reserved_qty).toFixed(2) }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td v-if="!editable" class="align-top text-end font-monospace">{{ line.delivered_qty || 0 }}</td>
							<td class="align-top">
								<template v-if="editable">
									<div
										v-if="line.uoms && line.uoms.length > 1 && line.uoms.length <= 3"
										class="btn-group btn-group-sm w-100"
										role="group"
									>
										<button
											v-for="u in line.uoms"
											:key="u.uom"
											type="button"
											class="btn"
											:class="line.uom === u.uom ? 'btn-primary' : 'btn-outline-secondary'"
											@click="setLineUom(line, u.uom)"
										>{{ u.uom }}</button>
									</div>
									<Select
										v-else-if="line.uoms && line.uoms.length > 3"
										v-model="line.uom"
										size="sm"
										:options="line.uoms"
										value-key="uom"
										label-key="uom"
										@change="onUomChange(line)"
									/>
									<input v-else v-model="line.uom" type="text" class="form-control form-control-sm" />
									<div v-if="line.uom && line.stock_uom && line.uom !== line.stock_uom && line.conversion_factor !== 1" class="small text-secondary mt-1">
										1{{ line.uom[0].toUpperCase() }} = {{ line.conversion_factor }}{{ line.stock_uom[0].toUpperCase() }}
									</div>
								</template>
								<div v-else>{{ line.uom || "—" }}</div>
							</td>
							<td v-if="!editable" class="align-top text-end font-monospace text-secondary small">
								{{ line.price_list_rate > 0 ? formatMoney(line.price_list_rate, doc?.currency, user.language) : "—" }}
							</td>
							<td class="align-top">
								<MoneyInput
									v-if="editable"
									v-model="line.rate"
									size="sm"
									@input="line.rateTouched = true"
									@keydown.tab.exact="onRowTab(idx, 'rate', $event)"
								/>
								<div v-else class="text-end font-monospace">{{ formatMoney(line.rate, doc?.currency, user.language) }}</div>
							</td>
							<td v-if="showDiscounts" class="align-top">
								<input
									v-if="editable"
									v-model.number="line.discount_percentage"
									type="number"
									step="any"
									min="0"
									max="100"
									inputmode="decimal"
									class="form-control form-control-sm font-monospace text-end"
									placeholder="0"
								/>
								<div v-else class="text-end font-monospace small">{{ line.discount_percentage > 0 ? line.discount_percentage + "%" : "—" }}</div>
							</td>
							<td v-if="showDiscounts" class="align-top">
								<MoneyInput
									v-if="editable"
									v-model="line.discount_amount"
									size="sm"
									@keydown.tab.exact="onRowTab(idx, 'disc', $event)"
								/>
								<div v-else class="text-end font-monospace small">
									{{ line.discount_amount > 0 ? formatMoney(line.discount_amount, doc?.currency, user.language) : "—" }}
								</div>
							</td>
							<td class="align-top text-end font-monospace">
								{{ formatMoney(editable ? lineAmount(line) : (line.amount || lineAmount(line)), form.currency || currency, user.language) }}
							</td>
							<td v-if="editable" class="align-top">
								<button type="button" class="btn btn-sm btn-icon btn-ghost-danger" @click="removeLine(idx)">
									<i class="ti ti-trash"></i>
								</button>
							</td>
						</tr>
					</template>
				</tbody>
				<tfoot>
					<tr v-if="editable">
						<td :colspan="showDiscounts ? 9 : 7">
							<button type="button" class="btn btn-sm btn-ghost-primary" @click="addLine">
								<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
							</button>
						</td>
					</tr>
					<tr>
						<td colspan="2" class="align-middle">
							<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t('item') : t('items') }}</span>
							<span v-for="[uom, qty] in totalsByUom" :key="uom" class="badge bg-blue-lt ms-1 font-monospace">{{ qty }} {{ uom }}</span>
						</td>
						<td class="text-end text-uppercase small text-secondary"></td>
						<td class="text-end font-monospace fw-bold">{{ formatMoney(createTotal, form.currency || currency, user.language) }}</td>
						<td></td>
					</tr>
				</tfoot>
			</table>
		</div>

		<div class="mt-3">
			<label class="form-label">{{ t("Terms / remarks") }}</label>
			<textarea v-if="editable" v-model="form.remarks" class="form-control" rows="2"></textarea>
			<div v-else class="form-control-plaintext py-1">{{ form.remarks || "—" }}</div>
		</div>

		<RelatedDocuments v-if="!isCreate && doc" doctype="Sales Order" :name="doc.name" />

		<!-- ── Actions ── -->
		<template #actions>
			<template v-if="isCreate">
				<div v-if="hasOverAvailable" class="w-100 small text-danger mb-1">
					<i class="ti ti-alert-triangle me-1"></i>{{ t("One or more lines exceed available stock. Reduce qty or choose a different warehouse.") }}
				</div>
				<button type="button" class="btn btn-link link-secondary" :disabled="actionRunning" @click="router.push('/sales/orders')">{{ t("Cancel") }}</button>
				<button type="button" class="btn btn-outline-primary ms-auto" :disabled="actionRunning" @click="submitCreate({ autoSubmit: 0 })">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Save as draft") }}
				</button>
				<button type="button" class="btn btn-primary" :disabled="actionRunning || hasOverAvailable" @click="submitCreate({ autoSubmit: 1 })">
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Submit & reserve stock") }}
				</button>
			</template>
			<template v-else>
				<button
					v-if="canDelete"
					type="button"
					class="btn btn-outline-primary"
					:disabled="actionRunning"
					@click="saveDraft"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-device-floppy me-1"></i>{{ t("Save changes") }}
				</button>
				<button
					v-if="canSubmit"
					type="button"
					class="btn btn-primary"
					:disabled="actionRunning"
					@click="submitDoc"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-check me-1"></i>{{ t("Submit") }}
				</button>
				<button
					v-if="canCreateInvoice"
					type="button"
					class="btn btn-success"
					:disabled="actionRunning"
					@click="createInvoice"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-file-invoice me-1"></i>{{ t("Create Invoice") }}
				</button>
				<button
					v-if="canCancel"
					type="button"
					class="btn btn-outline-danger ms-auto"
					:disabled="actionRunning"
					@click="cancelDoc"
				>
					<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
				</button>
				<button
					v-if="canAmend"
					type="button"
					class="btn btn-outline-secondary"
					:disabled="actionRunning"
					@click="amendDoc"
				>
					<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-copy me-1"></i>{{ t("Amend") }}
				</button>
				<button
					v-if="canDelete"
					type="button"
					class="btn btn-outline-danger"
					:class="{ 'ms-auto': !canCancel }"
					:disabled="actionRunning"
					@click="deleteDoc"
				>
					<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
				</button>
			</template>
		</template>
	</FormPage>
</template>
