<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { getStatusBadgeClass } from "../../composables/status.js";

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
	"To Receive and Bill",
	"To Bill",
	"To Receive",
	"Completed",
	"Cancelled",
	"Closed",
	"On Hold",
];

const statusOptions = computed(() => STATUSES.map((s) => ({ value: s, label: s || t("All") })));

const search = ref("");
const filteredRows = computed(() => {
	const q = search.value.toLowerCase().trim();
	if (!q) return rows.value;
	return rows.value.filter(r => 
		(r.name || "").toLowerCase().includes(q) ||
		(r.supplier || "").toLowerCase().includes(q) ||
		(r.supplier_name || "").toLowerCase().includes(q)
	);
});

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

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.purchasing.list_purchase_orders", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load purchase orders.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.purchasing.purchase_order_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || "Failed to load." };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

// Multi-currency bucket totals (purchasing convention — POs can be foreign-currency)
const totalsByCurrency = computed(() => {
	const m = new Map();
	for (const r of filteredRows.value) {
		const ccy = r.currency || currency.value;
		const bucket = m.get(ccy) || { currency: ccy, count: 0, grand: 0 };
		bucket.count += 1;
		bucket.grand += Number(r.grand_total || 0);
		m.set(ccy, bucket);
	}
	return Array.from(m.values());
});

// ──────────────── Create modal ────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

function blankLine() {
	return {
		item_code: "",
		item_name: "",
		uom: "",
		qty: 1,
		rate: 0,
		discount_percentage: 0,
		discount_amount: 0,
	};
}
function blankForm() {
	return {
		supplier: "",
		supplier_name: "",
		currency: "",
		price_list: "",
		set_warehouse: "",
		transaction_date: today,
		schedule_date: today,
		remarks: "",
		items: [blankLine()],
	};
}
const form = ref(blankForm());
const priceLists = ref([]);
const currencies = ref([]);

const currencySymbol = computed(() => {
	const code = form.value.currency || currency.value;
	return (currencies.value.find((c) => c.name === code) || {}).symbol || "";
});

const showDiscounts = ref(false);

function lineAmount(line) {
	const qty = Number(line.qty || 0);
	const rate = Number(line.rate || 0);
	const discPct = Number(line.discount_percentage || 0);
	const discAmt = Number(line.discount_amount || 0);
	if (discPct > 0) return qty * Math.max(rate * (1 - discPct / 100), 0);
	if (discAmt > 0) return qty * Math.max(rate - discAmt, 0);
	return qty * rate;
}

const createTotal = computed(() => form.value.items.reduce((s, r) => s + lineAmount(r), 0));

const warehouseOptions = computed(() => [
	{ name: "", warehouse_name: warehousesLoading.value ? t("Loading warehouses…") : t("— none —") },
	...warehouses.value,
]);

const priceListOptions = computed(() => [
	{ name: "", _label: t("— auto from supplier —") },
	...priceLists.value.map((pl) => ({ ...pl, _label: `${pl.name} (${pl.currency})` })),
]);

const totalsByUom = computed(() => {
	const map = new Map();
	for (const line of form.value.items) {
		if (!line.qty || !line.uom) continue;
		map.set(line.uom, (map.get(line.uom) || 0) + Number(line.qty));
	}
	return [...map.entries()];
});

async function loadPriceLists() {
	try {
		priceLists.value = await call("stabler.api.sales.list_price_lists", { buying_only: 1 });
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
	submitError.value = "";
	createOpen.value = true;
	loadPriceLists();
	loadCurrencies();
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}
async function pickSupplier(s) {
	form.value.supplier = s.name;
	form.value.supplier_name = s.supplier_name;
	if (s.default_currency) form.value.currency = s.default_currency;
}
function clearSupplier() {
	form.value.supplier = "";
	form.value.supplier_name = "";
	form.value.currency = "";
	form.value.price_list = "";
}

function searchItems(q) {
	return call("stabler.api.inventory.list_items", { search: q, limit: 10 });
}
function pickItem(line, item) {
	line.item_code = item.item_code || item.name;
	line.item_name = item.item_name;
	line.uom = item.stock_uom || "";
	line.rate = Number(item.standard_rate || 0);
}
function clearItem(line) {
	line.item_code = "";
	line.item_name = "";
	line.uom = "";
	line.rate = 0;
	line.discount_percentage = 0;
	line.discount_amount = 0;
}

function addLine() {
	form.value.items.push(blankLine());
}
function onRowTab(idx, field, event) {
	const lastField = showDiscounts.value ? "disc" : "rate";
	if (field !== lastField) return;
	if (idx !== form.value.items.length - 1) return;
	event.preventDefault();
	addLine();
	nextTick(() => {
		const rows = document.querySelectorAll("tr.po-line-row");
		rows[rows.length - 1]?.querySelector("input")?.focus();
	});
}
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		return;
	}
	form.value.items.splice(idx, 1);
}

// ──────────────── Submit / cancel / invoice / amend actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(() => !!detail.value && detail.value.docstatus === 1);
const canCreateInvoice = computed(
	() =>
		!!detail.value &&
		detail.value.docstatus === 1 &&
		!(detail.value.purchase_invoices && detail.value.purchase_invoices.length)
);
const canAmend = computed(() => !!detail.value && detail.value.docstatus === 2);
const canReceive = computed(
	() =>
		!!detail.value &&
		detail.value.docstatus === 1 &&
		Number(detail.value.per_received || 0) < 100
);

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.submit_purchase_order", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Submit failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(`Cancel purchase order ${detail.value.name}?`)) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.cancel_purchase_order", { name: detail.value.name });
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
		const res = await call("stabler.api.purchasing.create_purchase_invoice_from_po", {
			name: detail.value.name,
		});
		if (res?.name) {
			router.push({ path: "/purchasing/invoices", query: { open: res.name } });
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
		const res = await call("stabler.api.purchasing.amend_purchase_order", {
			name: detail.value.name,
		});
		await Promise.all([openDetail(res.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Amend failed.";
	} finally {
		actionRunning.value = false;
	}
}

// ──────────────── Receive (PO → Purchase Receipt) ────────────────
const receiveOpen = ref(false);
const receiving = ref(false);
const receiveError = ref("");
const receiveRows = ref([]);

function openReceive() {
	if (!detail.value?.items) return;
	receiveRows.value = detail.value.items
		.map((it) => ({
			po_detail: it.name,
			item_code: it.item_code,
			item_name: it.item_name,
			uom: it.uom,
			pending: Math.max(Number(it.qty || 0) - Number(it.received_qty || 0), 0),
		}))
		.filter((r) => r.pending > 0)
		.map((r) => ({ ...r, qty: r.pending }));
	receiveError.value = "";
	receiveOpen.value = true;
}
function closeReceive() {
	if (receiving.value) return;
	receiveOpen.value = false;
}

async function submitReceive() {
	receiveError.value = "";
	const lines = receiveRows.value
		.filter((r) => Number(r.qty) > 0)
		.map((r) => ({ po_detail: r.po_detail, qty: Math.min(Number(r.qty), r.pending) }));
	if (!lines.length) {
		receiveError.value = t("Enter a quantity for at least one row.");
		return;
	}
	receiving.value = true;
	try {
		const res = await call("stabler.api.purchasing.create_purchase_receipt_from_po", {
			name: detail.value.name,
			items: lines,
		});
		receiveOpen.value = false;
		if (res?.name) {
			router.push({ path: "/purchasing/receipts", query: { open: res.name } });
		}
	} catch (err) {
		receiveError.value = err?.message || t("Failed to create receipt.");
	} finally {
		receiving.value = false;
	}
}

async function submitCreate({ autoSubmit = 1 } = {}) {
	submitError.value = "";
	if (!form.value.supplier) {
		submitError.value = "Pick a supplier.";
		return;
	}
	const lines = form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			qty: r.qty,
			rate: r.rate,
			uom: r.uom,
			discount_percentage: r.discount_percentage || 0,
			discount_amount: r.discount_amount || 0,
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
	submitting.value = true;
	try {
		const created = await call("stabler.api.purchasing.create_purchase_order", {
			company: activeCompany.value,
			supplier: form.value.supplier,
			set_warehouse: form.value.set_warehouse || undefined,
			transaction_date: form.value.transaction_date,
			schedule_date: form.value.schedule_date,
			remarks: form.value.remarks || undefined,
			items: lines,
			auto_submit: autoSubmit,
			currency: form.value.currency || undefined,
			price_list: form.value.price_list || undefined,
		});
		createOpen.value = false;
		await load();
		if (created?.name) {
			await openDetail(created.name);
		}
	} catch (err) {
		submitError.value = err?.message || "Failed to create purchase order.";
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch([fromDate, toDate, status], load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Order number or supplier…')"
			:count="filteredRows.length"
			:primary-label="t('New purchase order')"
			primary-icon="ti-plus"
			@search="load"
			@primary-click="openCreate"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<DateInput v-model="fromDate" size="sm" style="width: 110px" />
					<span class="text-secondary small">—</span>
					<DateInput v-model="toDate" size="sm" style="width: 110px" />
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
				</div>
			</template>

			<template #summary>
				<div class="d-flex gap-3 small text-secondary align-items-center flex-wrap">
					<div>{{ t("Count") }}: <strong class="font-monospace text-body">{{ filteredRows.length }}</strong></div>
					<div v-for="b in totalsByCurrency" :key="b.currency" class="d-flex gap-2 align-items-center">
						<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
						<span>{{ t("Total") }}: <strong class="font-monospace text-body">{{ formatMoney(b.grand, b.currency, user.language) }}</strong></span>
					</div>
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !filteredRows.length"
			icon="ti-clipboard-list"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No purchase orders in this range')"
			:subtitle="t('Widen the date range, relax the status filter, or create a new order.')"
		>
			<template #actions>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New purchase order") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th class="text-nowrap">{{ t("Order Date") }}</th>
						<th class="text-nowrap">{{ t("Schedule") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Received") }}</th>
						<th class="text-end">{{ t("Billed") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="8" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDate(r.transaction_date) }}</td>
						<td class="text-nowrap">{{ formatDate(r.schedule_date) || "—" }}</td>
						<td>
							<div class="fw-semibold">{{ r.supplier_name || r.supplier }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ Number(r.per_received || 0).toFixed(0) }}%</td>
						<td class="text-end font-monospace">{{ Number(r.per_billed || 0).toFixed(0) }}%</td>
						<td><span class="badge" :class="getStatusBadgeClass('Purchase Order', r.status)">{{ t(r.status) }}</span></td>
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
			<h5 class="offcanvas-title">{{ t("Purchase Order") }}</h5>
			<button type="button" class="btn-close" @click="closeDetail" aria-label="Close"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="d-flex align-items-center mb-3 gap-3 flex-wrap">
					<div>
						<h3 class="m-0 font-monospace">{{ detail.name }}</h3>
						<div class="small text-secondary">{{ detail.supplier_name }}</div>
					</div>
					<div v-if="detail.amended_from" class="small text-secondary">
						{{ t("Amend of") }} <span class="font-monospace">{{ detail.amended_from }}</span>
					</div>
					<span class="badge" :class="getStatusBadgeClass('Purchase Order', detail.status)">{{ t(detail.status) }}</span>
				</div>

				<div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>

				<div class="btn-list mb-3">
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
						v-if="canReceive"
						type="button"
						class="btn btn-outline-secondary"
						:disabled="actionRunning"
						@click="openReceive"
					>
						<i class="ti ti-package-import me-1"></i>{{ t("Receive") }}
					</button>
					<button
						v-if="canCreateInvoice"
						type="button"
						class="btn btn-outline-secondary"
						:disabled="actionRunning"
						@click="createInvoice"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-file-invoice me-1"></i>{{ t("Create Invoice") }}
					</button>
					<button
						v-if="canCancel"
						type="button"
						class="btn btn-outline-secondary ms-auto"
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
				</div>

				<div
					v-if="detail.purchase_invoices && detail.purchase_invoices.length"
					class="alert alert-info"
				>
					<div class="fw-semibold mb-1"><i class="ti ti-link me-1"></i>{{ t("Linked invoices") }}</div>
					<div class="small">
						<span
							v-for="pi in detail.purchase_invoices"
							:key="pi.name"
							class="badge bg-blue-lt me-1 font-monospace"
						>{{ pi.name }}</span>
					</div>
				</div>

				<div
					v-if="detail.purchase_receipts && detail.purchase_receipts.length"
					class="alert alert-info"
				>
					<div class="fw-semibold mb-1"><i class="ti ti-package-import me-1"></i>{{ t("Linked receipts") }}</div>
					<div class="small">
						<router-link
							v-for="pr in detail.purchase_receipts"
							:key="pr.name"
							:to="{ path: '/purchasing/receipts', query: { open: pr.name } }"
							class="badge bg-green-lt me-1 font-monospace"
						>{{ pr.name }}</router-link>
					</div>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Order date") }}</div>
						<div class="datagrid-content">{{ formatDate(detail.transaction_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Schedule date") }}</div>
						<div class="datagrid-content">{{ formatDate(detail.schedule_date) || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Warehouse") }}</div>
						<div class="datagrid-content font-monospace">{{ detail.set_warehouse || "—" }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Currency") }}</div>
						<div class="datagrid-content">{{ detail.currency }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Net total") }}</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.net_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Grand total") }}</div>
						<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(detail.grand_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Received") }}</div>
						<div class="datagrid-content font-monospace">{{ Number(detail.per_received || 0).toFixed(0) }}%</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Billed") }}</div>
						<div class="datagrid-content font-monospace">{{ Number(detail.per_billed || 0).toFixed(0) }}%</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Items") }}</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Qty") }}</th>
								<th class="text-end">{{ t("Received") }}</th>
								<th>{{ t("UOM") }}</th>
								<th class="text-end">{{ t("List rate") }}</th>
								<th class="text-end">{{ t("Disc %") }}</th>
								<th class="text-end">{{ t("Rate") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(it, i) in detail.items" :key="i">
								<td>
									<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
									<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
									<div v-if="it.warehouse" class="small text-secondary">{{ it.warehouse }}</div>
								</td>
								<td class="text-end font-monospace">{{ it.qty }}</td>
								<td class="text-end font-monospace">
									<span
										v-if="Number(it.received_qty || 0) > 0"
										class="badge bg-blue-lt"
									>{{ Number(it.received_qty).toFixed(2) }}</span>
									<span v-else class="text-secondary">—</span>
								</td>
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

				<RelatedDocuments doctype="Purchase Order" :name="detail.name" />
			</div>
		</div>
	</div>

	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New purchase order") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-3 mb-3">
						<div class="col-md-6">
							<label class="form-label required">{{ t("Supplier") }}</label>
							<Typeahead
								v-model="form.supplier"
								:search="searchSuppliers"
								:display="form.supplier_name"
								:placeholder="t('Search supplier name…')"
								:no-results-text="t('No suppliers match that name')"
								open-on-focus
								:disabled="submitting"
								@pick="pickSupplier"
								@clear="clearSupplier"
							>
								<template #option="{ item }">
									<div class="d-flex align-items-center gap-2">
										<span class="avatar avatar-xs bg-orange-lt">{{ (item.supplier_name || item.name).charAt(0).toUpperCase() }}</span>
										<div>
											<div class="fw-semibold">{{ item.supplier_name }}</div>
											<div class="small text-secondary">{{ item.name }} · {{ item.supplier_group || "—" }}</div>
										</div>
									</div>
								</template>
							</Typeahead>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Warehouse") }} <span class="text-secondary small">({{ t("optional") }})</span></label>
							<Select
								v-model="form.set_warehouse"
								:options="warehouseOptions"
								value-key="name"
								:disabled="submitting || warehousesLoading"
							>
								<template #option="{ option: w }">
									<span v-if="w.name">{{ w.warehouse_name }} ({{ w.name }})</span>
									<span v-else>{{ w.warehouse_name }}</span>
								</template>
								<template #selected="{ option: w }">
									<span v-if="w.name">{{ w.warehouse_name }} ({{ w.name }})</span>
									<span v-else>{{ w.warehouse_name }}</span>
								</template>
							</Select>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Order date") }}</label>
							<DateInput v-model="form.transaction_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Schedule date") }}</label>
							<DateInput v-model="form.schedule_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Price list") }}</label>
							<Select
								v-model="form.price_list"
								:options="priceListOptions"
								value-key="name"
								label-key="_label"
								:disabled="submitting"
							/>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Currency") }}</label>
							<div class="form-control-plaintext font-monospace fw-semibold py-1">
								{{ form.currency || currency }}
								<span v-if="currencySymbol" class="text-secondary fw-normal">({{ currencySymbol }})</span>
							</div>
						</div>
					</div>

					<div class="d-flex align-items-center mb-2">
						<h6 class="text-uppercase text-secondary small mb-0">{{ t("Items") }}</h6>
						<div class="form-check form-switch ms-auto mb-0">
							<input class="form-check-input" type="checkbox" id="poShowDisc" v-model="showDiscounts" />
							<label class="form-check-label small text-secondary" for="poShowDisc">{{ t("Show discounts") }}</label>
						</div>
					</div>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th class="text-end text-secondary" style="width: 36px">#</th>
									<th style="min-width: 220px">{{ t("Item") }}</th>
									<th style="width: 80px">{{ t("Qty") }}</th>
									<th style="width: 100px">{{ t("UOM") }}</th>
									<th style="width: 140px">{{ t("Rate") }}</th>
									<th v-if="showDiscounts" style="width: 70px">%</th>
									<th v-if="showDiscounts" style="width: 130px">{{ t("Disc") }}</th>
									<th class="text-end" style="width: 130px">{{ t("Amount") }}</th>
									<th style="width: 40px"></th>
								</tr>
							</thead>
							<tbody>
								<template v-for="(line, idx) in form.items" :key="idx">
									<tr class="po-line-row">
										<td class="align-top text-end text-secondary font-monospace small">{{ idx + 1 }}</td>
										<td class="align-top">
											<Typeahead
												:model-value="line.item_code"
												:search="searchItems"
												:display="line.item_name || line.item_code"
												:placeholder="t('Search item…')"
												:no-results-text="t('No items match')"
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
										<td class="align-top">
											<input
												v-model.number="line.qty"
												type="number"
												step="any"
												inputmode="decimal"
												class="form-control form-control-sm font-monospace text-end"
											/>
										</td>
										<td class="align-top">
											<input
												v-model="line.uom"
												type="text"
												class="form-control form-control-sm"
												:disabled="submitting"
											/>
										</td>
										<td class="align-top"><MoneyInput v-model="line.rate" size="sm" @keydown.tab.exact="onRowTab(idx, 'rate', $event)" /></td>
										<td v-if="showDiscounts" class="align-top">
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
										<td v-if="showDiscounts" class="align-top"><MoneyInput v-model="line.discount_amount" size="sm" :disabled="submitting" @keydown.tab.exact="onRowTab(idx, 'disc', $event)" /></td>
										<td class="align-top text-end font-monospace">
											{{ formatMoney(lineAmount(line), form.currency || currency, user.language) }}
										</td>
										<td class="align-top">
											<button type="button" class="btn btn-sm btn-icon btn-ghost-danger" @click="removeLine(idx)" :disabled="submitting">
												<i class="ti ti-trash"></i>
											</button>
										</td>
									</tr>
								</template>
							</tbody>
							<tfoot>
								<tr>
									<td :colspan="showDiscounts ? 9 : 7">
										<button
											type="button"
											class="btn btn-sm btn-ghost-primary"
											:disabled="submitting"
											@click="addLine"
										>
											<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
										</button>
									</td>
								</tr>
								<tr>
									<td colspan="2" class="align-middle">
										<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t("item") : t("items") }}</span>
										<span v-for="[uom, qty] in totalsByUom" :key="uom" class="badge bg-blue-lt ms-1 font-monospace">{{ qty }} {{ uom }}</span>
									</td>
									<td :colspan="showDiscounts ? 5 : 3" class="text-end text-uppercase small text-secondary">{{ t("Net total") }}</td>
									<td class="text-end font-monospace fw-bold">{{ formatMoney(createTotal, form.currency || currency, user.language) }}</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>

					<div class="mt-3">
						<label class="form-label">{{ t("Terms / remarks") }}</label>
						<textarea v-model="form.remarks" class="form-control" rows="2"></textarea>
					</div>
				</div>
				<div class="modal-footer flex-wrap gap-2">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-outline-primary ms-auto me-2" :disabled="submitting" @click="submitCreate({ autoSubmit: 0 })">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save as draft") }}
					</button>
					<button type="button" class="btn btn-primary" :disabled="submitting" @click="submitCreate({ autoSubmit: 1 })">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="receiveOpen" class="modal-backdrop fade show" @click="closeReceive"></div>
	<div v-if="receiveOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeReceive">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Receive goods") }} — <span class="font-monospace">{{ detail?.name }}</span></h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeReceive" :disabled="receiving"></button>
				</div>
				<div class="modal-body">
					<div v-if="receiveError" class="alert alert-danger">{{ receiveError }}</div>
					<p class="text-secondary small mb-2">
						{{ t("Adjust quantities for a partial receipt. Rows left at zero are skipped.") }}
					</p>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("Item") }}</th>
									<th class="text-end">{{ t("Pending") }}</th>
									<th>{{ t("UOM") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Receive now") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="r in receiveRows" :key="r.po_detail">
									<td>
										<div class="fw-semibold">{{ r.item_name || r.item_code }}</div>
										<div class="small text-secondary font-monospace">{{ r.item_code }}</div>
									</td>
									<td class="text-end font-monospace">{{ r.pending }}</td>
									<td>{{ r.uom || "—" }}</td>
									<td>
										<input
											v-model.number="r.qty"
											type="number"
											step="any"
											min="0"
											:max="r.pending"
											inputmode="decimal"
											class="form-control form-control-sm font-monospace text-end"
											:disabled="receiving"
										/>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="receiving" @click="closeReceive">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-success" :disabled="receiving" @click="submitReceive">
						<span v-if="receiving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-package-import me-1"></i>{{ t("Create receipt") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
