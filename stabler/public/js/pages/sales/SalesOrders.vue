<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();

const today = new Date().toISOString().slice(0, 10);
const monthAgo = new Date(Date.now() - 90 * 86400000).toISOString().slice(0, 10);
const fromDate = ref(monthAgo);
const toDate = ref(today);
const status = ref("");
const limit = ref(100);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const lastReservationErrors = ref([]);

const warehouses = ref([]);
const warehousesLoading = ref(false);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const STATUSES = [
	"",
	"Draft",
	"To Deliver and Bill",
	"To Bill",
	"To Deliver",
	"Completed",
	"Cancelled",
	"Closed",
	"On Hold",
];

const statusBadge = (s) => {
	const m = {
		Draft: "bg-secondary-lt",
		"To Deliver and Bill": "bg-yellow-lt",
		"To Bill": "bg-orange-lt",
		"To Deliver": "bg-blue-lt",
		Completed: "bg-green-lt",
		Cancelled: "bg-red-lt",
		Closed: "bg-secondary-lt",
		"On Hold": "bg-purple-lt",
	};
	return m[s] || "bg-secondary-lt";
};

function pipelineStage(s) {
	if (s === "Completed") return 3;
	if (s === "To Bill") return 2;
	if (s === "To Deliver") return 2;
	if (s === "To Deliver and Bill") return 1;
	return 1;
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

// The New SO modal pre-selects the finished-goods warehouse. Match on the
// display name (record name carries a company suffix, e.g. "Tayyor mahsulot - A").
const DEFAULT_WAREHOUSE_NAME = "tayyor mahsulot";
function defaultWarehouseName() {
	const match = warehouses.value.find(
		(w) => (w.warehouse_name || "").trim().toLowerCase() === DEFAULT_WAREHOUSE_NAME
	);
	return match ? match.name : "";
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sales.list_sales_orders", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load sales orders.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.sales.sales_order_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || "Failed to load." };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
	lastReservationErrors.value = [];
}

const totals = computed(() => ({
	count: rows.value.length,
	grand: rows.value.reduce((s, r) => s + Number(r.grand_total || 0), 0),
}));

// ──────────────── Create modal ────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

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
		discount_percentage: 0,
		discount_amount: 0,
		warehouse: "",
		availability: null,
		availabilityLoading: false,
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
		delivery_date: today,
		remarks: "",
		items: [blankLine()],
	};
}
const form = ref(blankForm());
const priceLists = ref([]);
const currencies = ref([]);

function lineAmount(line) {
	const qty = Number(line.qty || 0);
	const rate = Number(line.rate || 0);
	const discPct = Number(line.discount_percentage || 0);
	const discAmt = Number(line.discount_amount || 0);
	if (discPct > 0) return qty * Math.max(rate * (1 - discPct / 100), 0);
	if (discAmt > 0) return qty * Math.max(rate - discAmt, 0);
	return qty * rate;
}

function factorFor(line, uom) {
	const entry = (line.uoms || []).find((u) => u.uom === uom);
	return entry ? Number(entry.conversion_factor) || 1 : 1;
}

async function onUomChange(line) {
	line.conversion_factor = factorFor(line, line.uom);
	if (line.item_code) {
		const { rate } = await resolveRate(line.item_code, line.rate, line.uom);
		line.rate = rate;
	}
}

const createTotal = computed(() =>
	form.value.items.reduce((s, r) => s + lineAmount(r), 0)
);

const overAvailableRows = computed(() =>
	form.value.items
		.map((line, i) => ({ line, i }))
		.filter(({ line }) => line.item_code && isOverAvailable(line))
);
const hasOverAvailable = computed(() => overAvailableRows.value.length > 0);

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

function openCreate() {
	form.value = blankForm();
	form.value.set_warehouse = defaultWarehouseName();
	submitError.value = "";
	createOpen.value = true;
	loadPriceLists();
	loadCurrencies();
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

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
		// non-fatal: form stays with empty currency/price_list
	}
}
function clearCustomer() {
	form.value.customer = "";
	form.value.customer_name = "";
	form.value.currency = "";
	form.value.price_list = "";
}

function searchItems(q) {
	return call("stabler.api.inventory.list_items", { search: q, limit: 10 });
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
		line.uom = meta.default_uom || meta.stock_uom || "";
		line.conversion_factor = factorFor(line, line.uom);
		line.rate = Number(meta.price_list_rate || meta.standard_rate || 0);
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

// ────── Per-line availability widget (debounced 200ms) ──────
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
// Line qty is in transaction UOM; availability.free is in stock UOM.
// Multiply by conversion_factor so the comparison is apples-to-apples.
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

watch(
	() => form.value.customer,
	async (customer) => {
		if (!createOpen.value || !customer) return;
		try {
			const defaults = await call("stabler.api.sales.get_customer_defaults", {
				company: activeCompany.value,
				customer,
			});
			form.value.currency = defaults.default_currency || "";
			form.value.price_list = defaults.resolved_price_list || "";
		} catch {
			// non-fatal
		}
		const lines = form.value.items.filter((l) => l.item_code);
		for (const line of lines) {
			const { rate } = await resolveRate(line.item_code, line.rate);
			if (rate) line.rate = rate;
		}
	}
);

// When the header warehouse changes, propagate to lines that haven't been
// individually overridden yet (their warehouse equals the previous header
// value, or is empty).
watch(
	() => form.value.set_warehouse,
	(now, was) => {
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
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		form.value.items[0].warehouse = form.value.set_warehouse;
		return;
	}
	form.value.items.splice(idx, 1);
}

// ──────────────── Submit / cancel / invoice actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(() => !!detail.value && detail.value.docstatus === 1);
const canCreateInvoice = computed(
	() =>
		!!detail.value &&
		detail.value.docstatus === 1 &&
		!(detail.value.sales_invoices && detail.value.sales_invoices.length)
);
const canAmend = computed(() => !!detail.value && detail.value.docstatus === 2);

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.submit_sales_order", { name: detail.value.name });
		lastReservationErrors.value = res?.reservation_errors || [];
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Submit failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(`Cancel sales order ${detail.value.name}? Stock reservations will be released.`)) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.cancel_sales_order", { name: detail.value.name });
		lastReservationErrors.value = [];
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Cancel failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function createInvoice() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.create_sales_invoice", {
			sales_order: detail.value.name,
		});
		if (res?.name) {
			router.push({ path: "/sales/invoices", query: { open: res.name } });
		}
	} catch (err) {
		actionError.value = err?.message || "Failed to create invoice.";
	} finally {
		actionRunning.value = false;
	}
}

async function amendDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.amend_sales_order", { name: detail.value.name });
		await Promise.all([openDetail(res.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Amend failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function submitCreate({ autoSubmit = 1 } = {}) {
	submitError.value = "";
	if (!form.value.customer) {
		submitError.value = "Pick a customer.";
		return;
	}
	if (!form.value.set_warehouse) {
		submitError.value = "Pick a warehouse.";
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
		submitError.value = "Add at least one item line.";
		return;
	}
	for (const [i, r] of lines.entries()) {
		if (!Number(r.qty) || Number(r.qty) <= 0) {
			submitError.value = `Row ${i + 1}: qty must be greater than zero.`;
			return;
		}
	}
	// Ensure availability is loaded for all active lines (covers the race where
	// the user submits before the 200 ms debounce fires).
	await Promise.all(
		form.value.items
			.filter((l) => l.item_code && l.warehouse && !l.availability)
			.map((l) => loadAvailability(l))
	);
	const overRows = form.value.items
		.map((line, i) => ({ line, i }))
		.filter(({ line }) => line.item_code && isOverAvailable(line));
	if (overRows.length) {
		const { line, i } = overRows[0];
		submitError.value =
			`Row ${i + 1} (${line.item_name || line.item_code}): qty exceeds available stock ` +
			`(available ${Number(line.availability.free).toFixed(2)}).`;
		return;
	}
	submitting.value = true;
	try {
		const created = await call("stabler.api.sales.create_sales_order", {
			company: activeCompany.value,
			customer: form.value.customer,
			set_warehouse: form.value.set_warehouse,
			transaction_date: form.value.transaction_date,
			delivery_date: form.value.delivery_date || form.value.transaction_date,
			remarks: form.value.remarks || undefined,
			items: lines,
			auto_submit: autoSubmit,
			currency: form.value.currency || undefined,
			price_list: form.value.price_list || undefined,
		});
		createOpen.value = false;
		await load();
		if (created?.name) {
			lastReservationErrors.value = created.reservation_errors || [];
			await openDetail(created.name);
		}
	} catch (err) {
		submitError.value = err?.message || "Failed to create sales order.";
	} finally {
		submitting.value = false;
	}
}

onMounted(async () => {
	await Promise.all([load(), loadWarehouses()]);
	const openName = route.query?.open;
	if (openName) {
		openDetail(String(openName));
		return;
	}
	const newFor = route.query?.new_for;
	if (newFor) {
		openCreate();
		try {
			const [cdata, defaults] = await Promise.all([
				call("stabler.api.sales.get_customer", { name: String(newFor) }),
				call("stabler.api.sales.get_customer_defaults", {
					company: activeCompany.value,
					customer: String(newFor),
				}),
			]);
			form.value.customer = cdata.name;
			form.value.customer_name = cdata.customer_name;
			form.value.currency = defaults.default_currency || "";
			form.value.price_list = defaults.resolved_price_list || "";
		} catch {
			// non-fatal — form stays open with blank customer
		}
	}
});
watch(activeCompany, async () => {
	await Promise.all([load(), loadWarehouses()]);
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">Sales Orders</div>
			<div class="ms-auto d-flex gap-2 align-items-end flex-wrap">
				<div>
					<label class="form-label small mb-1">From</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">To</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<div style="min-width: 180px">
					<label class="form-label small mb-1">Status</label>
					<select v-model="status" class="form-select form-select-sm">
						<option v-for="s in STATUSES" :key="s" :value="s">{{ s || "All" }}</option>
					</select>
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>Apply
				</button>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>New sales order
				</button>
			</div>
		</div>

		<div v-if="rows.length" class="card-body py-2 border-bottom bg-light">
			<div class="d-flex gap-4 small">
				<div>Count: <strong>{{ totals.count }}</strong></div>
				<div>Total: <strong class="font-monospace">{{ formatMoney(totals.grand, currency, user.language) }}</strong></div>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-clipboard-check"
			accentIcon="ti-plus"
			tone="primary"
			title="No sales orders in this range"
			subtitle="Widen the date range, relax the status filter, or start a new order."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>New sales order
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th class="text-nowrap">Date</th>
						<th>Customer</th>
						<th class="text-end">Total</th>
						<th class="text-end">Delivered</th>
						<th class="text-end">Billed</th>
						<th>Status</th>
						<th>Reserved</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDateTime(r.transaction_date) }}</td>
						<td>
							<div class="fw-semibold">{{ r.customer_name || r.customer }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ Number(r.per_delivered || 0).toFixed(0) }}%</td>
						<td class="text-end font-monospace">{{ Number(r.per_billed || 0).toFixed(0) }}%</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
						<td>
							<span v-if="r.has_reservations" class="badge bg-green-lt">
								<i class="ti ti-lock me-1"></i>Reserved
							</span>
							<span v-else class="text-secondary small">—</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		class="offcanvas offcanvas-end"
		:class="{ show: detailOpen }"
		tabindex="-1"
		style="visibility: visible; width: 640px"
		:style="{ transform: detailOpen ? 'translateX(0)' : 'translateX(100%)' }"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">Sales Order</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center mb-3 gap-3">
					<div>
						<h3 class="m-0 font-monospace">{{ detail.name }}</h3>
						<div class="small text-secondary">{{ detail.customer_name }}</div>
					</div>
					<span v-if="detail.has_reservations" class="badge bg-green-lt">
						<i class="ti ti-lock me-1"></i>Reserved
					</span>
					<span class="badge" :class="statusBadge(detail.status)">{{ detail.status }}</span>
				</div>

				<ul class="steps steps-counter mb-4">
					<li class="step-item active">Quotation</li>
					<li class="step-item active">Sales Order</li>
					<li class="step-item" :class="{ active: pipelineStage(detail.status) >= 2 }">Deliver</li>
					<li class="step-item" :class="{ active: pipelineStage(detail.status) >= 3 }">Invoice</li>
				</ul>

				<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>

				<div v-if="lastReservationErrors.length" class="alert alert-warning">
					<div class="fw-semibold mb-1">
						<i class="ti ti-alert-triangle me-1"></i>Some lines could not be reserved
					</div>
					<ul class="mb-0 ps-3 small">
						<li v-for="(e, i) in lastReservationErrors" :key="i">
							<span v-if="e.item" class="font-monospace">{{ e.item }}</span>
							<span v-if="e.line"> · line {{ e.line }}</span>
							<span v-if="e.error"> — {{ e.error }}</span>
						</li>
					</ul>
				</div>

				<div class="btn-list mb-3">
					<button
						v-if="canSubmit"
						type="button"
						class="btn btn-primary"
						:disabled="actionRunning"
						@click="submitDoc"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>Submit
					</button>
					<button
						v-if="canCreateInvoice"
						type="button"
						class="btn btn-success"
						:disabled="actionRunning"
						@click="createInvoice"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-file-invoice me-1"></i>Create Invoice
					</button>
					<button
						v-if="canCancel"
						type="button"
						class="btn btn-outline-danger ms-auto"
						:disabled="actionRunning"
						@click="cancelDoc"
					>
						<i class="ti ti-ban me-1"></i>Cancel
					</button>
					<button
						v-if="canAmend"
						type="button"
						class="btn btn-outline-secondary"
						:disabled="actionRunning"
						@click="amendDoc"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-copy me-1"></i>Amend
					</button>
				</div>

				<div
					v-if="detail.sales_invoices && detail.sales_invoices.length"
					class="alert alert-info"
				>
					<div class="fw-semibold mb-1"><i class="ti ti-link me-1"></i>Linked invoices</div>
					<div class="small">
						<span
							v-for="si in detail.sales_invoices"
							:key="si.name"
							class="badge bg-blue-lt me-1 font-monospace"
						>{{ si.name }}</span>
					</div>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">Order date</div>
						<div class="datagrid-content">{{ formatDateTime(detail.transaction_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Delivery date</div>
						<div class="datagrid-content">{{ formatDateTime(detail.delivery_date) || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Warehouse</div>
						<div class="datagrid-content font-monospace">{{ detail.set_warehouse || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Currency</div>
						<div class="datagrid-content">{{ detail.currency }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Net total</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.net_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Grand total</div>
						<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(detail.grand_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Advance paid</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.advance_paid, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Delivered</div>
						<div class="datagrid-content font-monospace">{{ Number(detail.per_delivered || 0).toFixed(0) }}%</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Billed</div>
						<div class="datagrid-content font-monospace">{{ Number(detail.per_billed || 0).toFixed(0) }}%</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">Items</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>Item</th>
								<th>Warehouse</th>
								<th class="text-end">Qty</th>
								<th class="text-end">Reserved</th>
								<th class="text-end">Delivered</th>
								<th>UOM</th>
								<th class="text-end">List rate</th>
								<th class="text-end">Disc %</th>
								<th class="text-end">Rate</th>
								<th class="text-end">Amount</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(it, i) in detail.items" :key="i">
								<td>
									<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
									<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
								</td>
								<td class="font-monospace small">{{ it.warehouse || "—" }}</td>
								<td class="text-end font-monospace">{{ it.qty }}</td>
								<td class="text-end font-monospace">
									<span
										v-if="Number(it.reserved_qty || 0) > 0"
										class="badge bg-green-lt"
									>{{ Number(it.reserved_qty).toFixed(2) }}</span>
									<span v-else class="text-secondary">—</span>
								</td>
								<td class="text-end font-monospace">{{ it.delivered_qty || 0 }}</td>
								<td>{{ it.uom || "—" }}</td>
								<td class="text-end font-monospace text-secondary small">
									{{ it.price_list_rate > 0 ? formatMoney(it.price_list_rate, detail.currency, user.language) : "—" }}
								</td>
								<td class="text-end font-monospace small">
									{{ it.discount_percentage > 0 ? it.discount_percentage + "%" : "—" }}
								</td>
								<td class="text-end font-monospace">{{ formatMoney(it.rate, detail.currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.amount, detail.currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div v-if="detail.remarks" class="mt-3 small text-secondary">{{ detail.remarks }}</div>

				<RelatedDocuments doctype="Sales Order" :name="detail.name" />
			</div>
		</div>
	</div>

	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">New sales order</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-3 mb-3">
						<div class="col-md-6">
							<label class="form-label required">Customer</label>
							<Typeahead
								v-model="form.customer"
								:search="searchCustomers"
								:display="form.customer_name"
								placeholder="Search customer name…"
								no-results-text="No customers match that name"
								open-on-focus
								:disabled="submitting"
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
						</div>
						<div class="col-md-3">
							<label class="form-label">Price list</label>
							<select v-model="form.price_list" class="form-select" :disabled="submitting">
								<option value="">— auto from customer —</option>
								<option v-for="pl in priceLists" :key="pl.name" :value="pl.name">
									{{ pl.name }} ({{ pl.currency }})
								</option>
							</select>
						</div>
						<div class="col-md-3">
							<label class="form-label">Currency</label>
							<select v-model="form.currency" class="form-select font-monospace" :disabled="submitting">
								<option value="">— from customer / company —</option>
								<option v-for="c in currencies" :key="c.name" :value="c.name">
									{{ c.name }}{{ c.symbol ? ` (${c.symbol})` : "" }}
								</option>
							</select>
						</div>
						<div class="col-md-6">
							<label class="form-label required">Warehouse</label>
							<select
								v-model="form.set_warehouse"
								class="form-select"
								:disabled="submitting || warehousesLoading"
							>
								<option value="">{{ warehousesLoading ? "Loading warehouses…" : "Pick a warehouse" }}</option>
								<option v-for="w in warehouses" :key="w.name" :value="w.name">
									{{ w.warehouse_name }} ({{ w.name }})
								</option>
							</select>
						</div>
						<div class="col-md-3">
							<label class="form-label">Order date</label>
							<DateInput v-model="form.transaction_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label required">Delivery date</label>
							<DateInput v-model="form.delivery_date" />
						</div>
					</div>

					<h6 class="text-uppercase text-secondary small mb-2">Items</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th style="min-width: 220px">Item</th>
									<th style="width: 80px">Qty</th>
									<th style="width: 120px">UOM</th>
									<th style="width: 140px">Rate</th>
									<th style="width: 70px">%</th>
									<th style="width: 130px">Disc</th>
									<th class="text-end" style="width: 130px">Amount</th>
									<th style="width: 40px"></th>
								</tr>
							</thead>
							<tbody>
								<template v-for="(line, idx) in form.items" :key="idx">
									<tr>
										<td>
											<Typeahead
												:model-value="line.item_code"
												:search="searchItems"
												:display="line.item_name || line.item_code"
												placeholder="Search item…"
												no-results-text="No items match"
												size="sm"
												menu-min-width="280px"
												open-on-focus
												:disabled="submitting"
												@pick="(it) => pickItem(line, it)"
												@clear="clearItem(line)"
											>
												<template #option="{ item: it }">
													<div class="fw-semibold small">{{ it.item_name }}</div>
													<div class="small text-secondary font-monospace">{{ it.item_code }} · {{ it.stock_uom || "—" }}</div>
												</template>
											</Typeahead>
										</td>
										<td>
											<input
												v-model.number="line.qty"
												type="number"
												step="any"
												inputmode="decimal"
												class="form-control form-control-sm font-monospace text-end"
											/>
										</td>
										<td>
											<select
												v-if="line.uoms && line.uoms.length"
												v-model="line.uom"
												class="form-select form-select-sm"
												:disabled="submitting"
												@change="onUomChange(line)"
											>
												<option v-for="u in line.uoms" :key="u.uom" :value="u.uom">{{ u.uom }}</option>
											</select>
											<input
												v-else
												v-model="line.uom"
												type="text"
												class="form-control form-control-sm"
												:disabled="submitting"
											/>
											<div v-if="line.uom && line.stock_uom && line.uom !== line.stock_uom && line.conversion_factor !== 1" class="small text-secondary mt-1">
												1 {{ line.uom }} = {{ line.conversion_factor }} {{ line.stock_uom }}
											</div>
										</td>
										<td><MoneyInput v-model="line.rate" /></td>
										<td>
											<input
												v-model.number="line.discount_percentage"
												type="number"
												step="any"
												min="0"
												max="100"
												inputmode="decimal"
												class="form-control form-control-sm font-monospace text-end"
												placeholder="0"
												:disabled="submitting"
											/>
										</td>
										<td><MoneyInput v-model="line.discount_amount" :disabled="submitting" /></td>
										<td class="text-end font-monospace">
											{{ formatMoney(lineAmount(line), form.currency || currency, user.language) }}
										</td>
										<td>
											<button type="button" class="btn btn-sm btn-icon btn-ghost-danger" @click="removeLine(idx)" :disabled="submitting">
												<i class="ti ti-trash"></i>
											</button>
										</td>
									</tr>
									<tr v-if="line.item_code && line.warehouse">
										<td colspan="8" class="py-1 ps-3 small">
											<span v-if="line.availabilityLoading" class="text-secondary">
												<span class="spinner-border spinner-border-sm me-1"></span>Checking availability…
											</span>
											<span v-else-if="line.availability">
												<span class="badge" :class="availabilityTone(line)">
													Available: {{ Number(line.availability.free).toFixed(2) }}
													(On hand: {{ Number(line.availability.actual).toFixed(2) }},
													Reserved: {{ Number(line.availability.reserved).toFixed(2) }})
													in {{ line.warehouse }}
												</span>
											</span>
										</td>
									</tr>
								</template>
							</tbody>
							<tfoot>
								<tr>
									<td colspan="8">
										<button
											type="button"
											class="btn btn-sm btn-ghost-primary"
											:disabled="submitting"
											@click="addLine"
										>
											<i class="ti ti-plus me-1"></i>Add row
										</button>
									</td>
								</tr>
								<tr>
									<td colspan="6" class="text-end text-uppercase small text-secondary">Net total</td>
									<td class="text-end font-monospace fw-bold">{{ formatMoney(createTotal, form.currency || currency, user.language) }}</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>

					<div class="mt-3">
						<label class="form-label">Terms / remarks</label>
						<textarea v-model="form.remarks" class="form-control" rows="2"></textarea>
					</div>
				</div>
				<div class="modal-footer flex-wrap gap-2">
					<div v-if="hasOverAvailable" class="w-100 small text-danger">
						<i class="ti ti-alert-triangle me-1"></i>One or more lines exceed available stock. Reduce qty or choose a different warehouse.
					</div>
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-outline-primary ms-auto me-2" :disabled="submitting || hasOverAvailable" @click="submitCreate({ autoSubmit: 0 })">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save as draft") }}
					</button>
					<button type="button" class="btn btn-primary" :disabled="submitting || hasOverAvailable" @click="submitCreate({ autoSubmit: 1 })">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Submit & reserve stock") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
