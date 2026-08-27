<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso, daysAgoIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { itemSearcher } from "../../composables/items.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { useBackdateGuard } from "../../composables/backdate.js";

const { canBackdate, minPostingDate } = useBackdateGuard();

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
useEscapeBack(() => { if (createOpen.value) { closeCreate(); return true; } if (detailOpen.value) { closeDetail(); return true; } return false; }, "/purchasing"); // ESC → close open pane, else back
const route = useRoute();

const { confirm } = useConfirm();
const toast = useToast();

const today = todayIso();
const monthAgo = daysAgoIso(90);
const fromDate = ref(String(route.query.from_date || monthAgo));
const toDate = ref(String(route.query.to_date || today));
const tenderOnly = computed(() => route.query.tender_only === "1");
const status = ref("");
const supplier = ref("");
const supplierName = ref("");
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

const STATUSES = ["", "Draft", "To Bill", "Completed", "Return Issued", "Closed"];

const statusOptions = computed(() => STATUSES.map((s) => ({ value: s, label: s || t("All") })));

const search = ref("");
const filteredRows = computed(() => {
	const q = search.value.toLowerCase().trim();
	if (!q) return rows.value;
	return rows.value.filter(r => 
		(r.name || "").toLowerCase().includes(q) ||
		(r.supplier || "").toLowerCase().includes(q) ||
		(r.supplier_name || "").toLowerCase().includes(q) ||
		(r.set_warehouse || "").toLowerCase().includes(q)
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
		rows.value = await call("stabler.api.purchasing.list_purchase_receipts", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			supplier: supplier.value || undefined,
			status: status.value || undefined,
			limit: tenderOnly.value ? 5000 : limit.value,
			tender_only: tenderOnly.value ? 1 : undefined,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load purchase receipts.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.purchasing.purchase_receipt_detail", { name });
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

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}
function pickFilterSupplier(s) {
	supplier.value = s.name;
	supplierName.value = s.supplier_name;
}
function clearFilterSupplier() {
	supplier.value = "";
	supplierName.value = "";
}

// Multi-currency bucket totals (purchasing convention — receipts can be foreign-currency)
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

// ──────────────── Submit / cancel / bill actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(() => !!detail.value && detail.value.docstatus === 1);
const canCreateBill = computed(
	() =>
		!!detail.value &&
		detail.value.docstatus === 1 &&
		!(detail.value.purchase_invoices && detail.value.purchase_invoices.length)
);

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.submit_purchase_receipt", { name: detail.value.name });
		toast.success(t("Purchase Receipt submitted."));
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Submit failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	const ok = await confirm({
		title: t("Cancel Purchase Receipt"),
		body: t("Cancel purchase receipt {0}?", [detail.value.name]),
		confirmLabel: t("Cancel Document"),
		cancelLabel: t("Close"),
		danger: true,
	});
	if (!ok) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.purchasing.cancel_purchase_receipt", { name: detail.value.name });
		toast.success(t("Purchase Receipt cancelled."));
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Cancel failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function createBill() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.purchasing.create_purchase_invoice_from_pr", {
			name: detail.value.name,
		});
		if (res?.name) {
			router.push({ path: "/purchasing/invoices", query: { open: res.name } });
		}
	} catch (err) {
		actionError.value = err?.message || "Failed to create bill.";
	} finally {
		actionRunning.value = false;
	}
}

// ──────────────── Create modal (direct receipt, no PO) ────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

function blankLine() {
	return { item_code: "", item_name: "", uom: "", qty: 1, rate: 0 };
}
function blankForm() {
	return {
		supplier: "",
		supplier_name: "",
		currency: "",
		set_warehouse: "",
		posting_date: today,
		remarks: "",
		items: [blankLine()],
	};
}
const form = ref(blankForm());

function lineAmount(line) {
	return Number(line.qty || 0) * Number(line.rate || 0);
}
const createTotal = computed(() => form.value.items.reduce((s, r) => s + lineAmount(r), 0));

const warehouseOptions = computed(() => [
	{ name: "", warehouse_name: warehousesLoading.value ? t("Loading warehouses…") : t("— pick a warehouse —") },
	...warehouses.value,
]);

function openCreate() {
	form.value = blankForm();
	submitError.value = "";
	createOpen.value = true;
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
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
}

const searchItems = itemSearcher("purchase");
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
}

function addLine() {
	form.value.items.push(blankLine());
}
function onRowTab(idx, field, event) {
	if (field !== "rate") return;
	if (idx !== form.value.items.length - 1) return;
	event.preventDefault();
	addLine();
	nextTick(() => {
		const trs = document.querySelectorAll("tr.pr-line-row");
		trs[trs.length - 1]?.querySelector("input")?.focus();
	});
}
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		return;
	}
	form.value.items.splice(idx, 1);
}

async function submitCreate({ autoSubmit = 0 } = {}) {
	submitError.value = "";
	if (!form.value.supplier) {
		submitError.value = "Pick a supplier.";
		return;
	}
	if (!form.value.set_warehouse) {
		submitError.value = t("Pick a warehouse to receive stock into.");
		return;
	}
	const lines = form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({ item_code: r.item_code, qty: r.qty, rate: r.rate, uom: r.uom }));
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
		const created = await call("stabler.api.purchasing.create_purchase_receipt", {
			company: activeCompany.value,
			supplier: form.value.supplier,
			set_warehouse: form.value.set_warehouse,
			posting_date: form.value.posting_date,
			remarks: form.value.remarks || undefined,
			items: lines,
			currency: form.value.currency || undefined,
		});
		if (created?.name && autoSubmit) {
			await call("stabler.api.purchasing.submit_purchase_receipt", { name: created.name });
		}
		createOpen.value = false;
		await load();
		if (created?.name) {
			await openDetail(created.name);
		}
	} catch (err) {
		submitError.value = err?.message || "Failed to create purchase receipt.";
	} finally {
		submitting.value = false;
	}
}

onMounted(async () => {
	await Promise.all([load(), loadWarehouses()]);
	const openName = route.query?.open;
	if (openName) openDetail(String(openName));
});
watch([fromDate, toDate, supplier, status], load);
watch(activeCompany, async () => {
	await Promise.all([load(), loadWarehouses()]);
});
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Receipt number or supplier…')"
			:count="filteredRows.length"
			:primary-label="t('New receipt')"
			primary-icon="ti-plus"
			@search="load"
			@primary-click="openCreate"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<DateInput v-model="fromDate" size="sm" style="width: 110px" />
					<span class="text-secondary small">—</span>
					<DateInput v-model="toDate" size="sm" style="width: 110px" />
					<div style="width: 180px">
						<Typeahead
							v-model="supplier"
							:search="searchSuppliers"
							:display="supplierName"
							:placeholder="t('All suppliers')"
							size="sm"
							open-on-focus
							@pick="pickFilterSupplier"
							@clear="clearFilterSupplier"
						>
							<template #option="{ item }">
								<div class="fw-semibold small">{{ item.supplier_name }}</div>
								<div class="small text-secondary font-monospace">{{ item.name }}</div>
							</template>
						</Typeahead>
					</div>
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
					<span v-if="tenderOnly" class="badge bg-blue-lt text-blue">{{ t("Tender records") }}</span>
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
			icon="ti-package-import"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No purchase receipts in this range')"
			:subtitle="t('Widen the date range, relax the filters, or log a direct receipt.')"
		>
			<template #actions>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New receipt") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th class="text-nowrap">{{ t("Date") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th>{{ t("Warehouse") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Billed") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="7" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="text-nowrap">{{ formatDate(r.posting_date) }}</td>
						<td>
							<div class="fw-semibold">{{ r.supplier_name || r.supplier }}</div>
						</td>
						<td class="font-monospace small">{{ r.set_warehouse || "—" }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ Number(r.per_billed || 0).toFixed(0) }}%</td>
						<td><span class="badge" :class="getStatusBadgeClass('Purchase Receipt', r.status)">{{ t(r.status) }}</span></td>
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
			<h5 class="offcanvas-title">{{ t("Purchase Receipt") }}</h5>
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
					<span class="badge" :class="getStatusBadgeClass('Purchase Receipt', detail.status)">{{ t(detail.status) }}</span>
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
						v-if="canCreateBill"
						type="button"
						class="btn btn-outline-secondary"
						:disabled="actionRunning"
						@click="createBill"
					>
						<span v-if="actionRunning" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-file-invoice me-1"></i>{{ t("Create Bill") }}
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
				</div>

				<div
					v-if="detail.purchase_invoices && detail.purchase_invoices.length"
					class="alert alert-info"
				>
					<div class="fw-semibold mb-1"><i class="ti ti-link me-1"></i>{{ t("Linked invoices") }}</div>
					<div class="small">
						<router-link
							v-for="pi in detail.purchase_invoices"
							:key="pi.name"
							:to="{ path: '/purchasing/invoices', query: { open: pi.name } }"
							class="badge bg-blue-lt me-1 font-monospace"
						>{{ pi.name }}</router-link>
					</div>
				</div>

				<div
					v-if="detail.landed_cost_vouchers && detail.landed_cost_vouchers.length"
					class="alert alert-info"
				>
					<div class="fw-semibold mb-1"><i class="ti ti-anchor me-1"></i>{{ t("Landed cost vouchers") }}</div>
					<div class="small">
						<span
							v-for="lcv in detail.landed_cost_vouchers"
							:key="lcv.name"
							class="badge bg-purple-lt me-1 font-monospace"
						>{{ lcv.name }}</span>
					</div>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Date") }}</div>
						<div class="datagrid-content">{{ formatDate(detail.posting_date) }}</div>
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
								<th>{{ t("UOM") }}</th>
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
									<router-link
										v-if="it.purchase_order"
										:to="{ path: '/purchasing/orders', query: { open: it.purchase_order } }"
										class="small font-monospace"
									>{{ it.purchase_order }}</router-link>
								</td>
								<td class="text-end font-monospace">
									{{ it.qty }}
									<span v-if="Number(it.rejected_qty || 0) > 0" class="badge bg-red-lt ms-1">−{{ it.rejected_qty }}</span>
								</td>
								<td>{{ it.uom || "—" }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.rate, detail.currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.amount, detail.currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div v-if="detail.remarks" class="mt-3 small text-secondary">{{ detail.remarks }}</div>

				<RelatedDocuments doctype="Purchase Receipt" :name="detail.name" />
			</div>
		</div>
	</div>

	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New receipt") }}</h5>
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
						<div class="col-md-3">
							<label class="form-label required">{{ t("Warehouse") }}</label>
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
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="form.posting_date" :min="minPostingDate" />
							<div v-if="!canBackdate" class="form-hint">
								{{ t("Only an administrator can post to an earlier date.") }}
							</div>
						</div>
					</div>

					<h6 class="text-uppercase text-secondary small mb-2">{{ t("Items") }}</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th class="text-end text-secondary" style="width: 36px">#</th>
									<th style="min-width: 220px">{{ t("Item") }}</th>
									<th style="width: 80px">{{ t("Qty") }}</th>
									<th style="width: 100px">{{ t("UOM") }}</th>
									<th style="width: 140px">{{ t("Rate") }}</th>
									<th class="text-end" style="width: 130px">{{ t("Amount") }}</th>
									<th style="width: 40px"></th>
								</tr>
							</thead>
							<tbody>
								<template v-for="(line, idx) in form.items" :key="idx">
									<tr class="pr-line-row">
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
									<td colspan="7">
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
									<td colspan="4" class="align-middle">
										<span class="badge bg-secondary-lt">{{ form.items.length }} {{ form.items.length === 1 ? t("item") : t("items") }}</span>
									</td>
									<td class="text-end text-uppercase small text-secondary">{{ t("Net total") }}</td>
									<td class="text-end font-monospace fw-bold">{{ formatMoney(createTotal, form.currency || currency, user.language) }}</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>

					<div class="mt-3">
						<label class="form-label">{{ t("Remarks") }}</label>
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
</template>
