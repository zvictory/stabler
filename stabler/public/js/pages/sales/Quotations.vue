<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { t } from "../../composables/i18n.js";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Typeahead from "../../components/Typeahead.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { getStatusBadgeClass } from "../../composables/status.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

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

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const STATUSES = ["", "Draft", "Open", "Ordered", "Lost", "Expired", "Cancelled"];

const statusOptions = computed(() =>
	STATUSES.map((s) => ({ value: s, label: s ? t(s) : t("All") }))
);

const search = ref("");
const filteredRows = computed(() => {
	const q = search.value.toLowerCase().trim();
	if (!q) return rows.value;
	return rows.value.filter(r => 
		(r.name || "").toLowerCase().includes(q) ||
		(r.customer || "").toLowerCase().includes(q) ||
		(r.customer_name || "").toLowerCase().includes(q)
	);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sales.list_quotations", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load quotations.");
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.sales.quotation_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || t("Failed to load.") };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

const totals = computed(() => ({
	count: filteredRows.value.length,
	grand: filteredRows.value.reduce((s, r) => s + Number(r.grand_total || 0), 0),
}));

// ──────────────── Create modal ────────────────
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

function blankLine() {
	return { item_code: "", item_name: "", uom: "", qty: 1, rate: 0 };
}
function blankForm() {
	return {
		customer: "",
		customer_name: "",
		transaction_date: today,
		valid_till: "",
		remarks: "",
		items: [blankLine()],
	};
}
const form = ref(blankForm());

const createTotal = computed(() =>
	form.value.items.reduce((s, r) => s + Number(r.qty || 0) * Number(r.rate || 0), 0)
);

function openCreate() {
	form.value = blankForm();
	submitError.value = "";
	createOpen.value = true;
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
function pickCustomer(c) {
	form.value.customer = c.name;
	form.value.customer_name = c.customer_name;
}
function clearCustomer() {
	form.value.customer = "";
	form.value.customer_name = "";
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
}
function addLine() {
	form.value.items.push(blankLine());
}
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		return;
	}
	form.value.items.splice(idx, 1);
}

// ──────────────── Submit / cancel actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(
	() => !!detail.value && detail.value.docstatus === 1 && detail.value.status !== "Ordered"
);

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.submit_quotation", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || t("Submit failed.");
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Cancel quotation {name}?", { name: detail.value.name }))) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.cancel_quotation", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || t("Cancel failed.");
	} finally {
		actionRunning.value = false;
	}
}

async function submitCreate() {
	submitError.value = "";
	if (!form.value.customer) {
		submitError.value = t("Pick a customer.");
		return;
	}
	const lines = form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({ item_code: r.item_code, qty: r.qty, rate: r.rate, uom: r.uom }));
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
	submitting.value = true;
	try {
		const created = await call("stabler.api.sales.create_quotation", {
			company: activeCompany.value,
			customer: form.value.customer,
			transaction_date: form.value.transaction_date,
			valid_till: form.value.valid_till || undefined,
			remarks: form.value.remarks || undefined,
			items: lines,
		});
		createOpen.value = false;
		await load();
		if (created?.name) await openDetail(created.name);
	} catch (err) {
		submitError.value = err?.message || t("Failed to create quotation.");
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
			:placeholder="t('Quotation number or customer…')"
			:count="totals.count"
			:total-label="t('Total')"
			:total-value="formatMoney(totals.grand, currency, user.language)"
			:primary-label="t('New quotation')"
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
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !filteredRows.length"
			icon="ti-file-text"
			accentIcon="ti-plus"
			tone="info"
			:title="t('No quotations in this range')"
			:subtitle="t('Widen the date range, relax the status filter, or send a new proposal.')"
		>
			<template #actions>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New quotation") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Valid till") }}</th>
						<th>{{ t("Customer") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="6" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ formatDateTime(r.transaction_date) }}</td>
						<td>{{ formatDateTime(r.valid_till) }}</td>
						<td>
							<div class="fw-semibold">{{ r.customer_name || r.customer }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td><span class="badge" :class="getStatusBadgeClass('Quotation', r.status)">{{ t(r.status) }}</span></td>
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
			<h5 class="offcanvas-title">{{ t("Quotation") }}</h5>
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
					<span class="badge ms-auto" :class="getStatusBadgeClass('Quotation', detail.status)">{{ t(detail.status) }}</span>
				</div>

				<!-- Pipeline steps: Quotation → Sales Order → Sales Invoice -->
				<ul class="steps steps-counter mb-4">
					<li class="step-item active">{{ t("Quotation") }}</li>
					<li class="step-item" :class="{ active: detail.status === 'Ordered' }">{{ t("Sales Order") }}</li>
					<li class="step-item">{{ t("Invoice") }}</li>
				</ul>

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
						v-if="canCancel"
						type="button"
						class="btn btn-outline-secondary ms-auto"
						:disabled="actionRunning"
						@click="cancelDoc"
					>
						<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
					</button>
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Date") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.transaction_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Valid till") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.valid_till) || "—" }}</div>
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
								</td>
								<td class="text-end font-monospace">{{ it.qty }}</td>
								<td>{{ it.uom || "—" }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.rate, detail.currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.amount, detail.currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div v-if="detail.remarks" class="mt-3 small text-secondary">{{ detail.remarks }}</div>
			</div>
		</div>
	</div>

	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-xl modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New quotation") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-3 mb-3">
						<div class="col-md-6">
							<label class="form-label required">{{ t("Customer") }}</label>
							<Typeahead
								v-model="form.customer"
								:search="searchCustomers"
								:display="form.customer_name"
								:placeholder="t('Search customer name…')"
								:no-results-text="t('No customers match that name')"
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
							<label class="form-label">{{ t("Date") }}</label>
							<DateInput v-model="form.transaction_date" />
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Valid till") }}</label>
							<DateInput v-model="form.valid_till" />
						</div>
					</div>

					<h6 class="text-uppercase text-secondary small mb-2">{{ t("Items") }}</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th style="min-width: 240px">{{ t("Item") }}</th>
									<th style="width: 110px">{{ t("Qty") }}</th>
									<th style="width: 90px">{{ t("UOM") }}</th>
									<th style="width: 160px">{{ t("Rate") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Amount") }}</th>
									<th style="width: 40px"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(line, idx) in form.items" :key="idx">
									<td>
										<Typeahead
											:model-value="line.item_code"
											:search="searchItems"
											:display="line.item_name || line.item_code"
											:placeholder="t('Search item…')"
											:no-results-text="t('No items match')"
											size="sm"
											menu-min-width="280px"
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
									<td><input v-model="line.uom" type="text" class="form-control form-control-sm" /></td>
									<td><MoneyInput v-model="line.rate" /></td>
									<td class="text-end font-monospace">
										{{ formatMoney(Number(line.qty || 0) * Number(line.rate || 0), currency, user.language) }}
									</td>
									<td>
										<button type="button" class="btn btn-sm btn-icon btn-ghost-danger" @click="removeLine(idx)" :disabled="submitting">
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
							<tfoot>
								<tr>
									<td colspan="6">
										<button type="button" class="btn btn-sm btn-ghost-primary" @click="addLine">
											<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
										</button>
									</td>
								</tr>
								<tr>
									<td colspan="4" class="text-end text-uppercase small text-secondary">{{ t("Net total") }}</td>
									<td class="text-end font-monospace fw-bold">{{ formatMoney(createTotal, currency, user.language) }}</td>
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
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitCreate">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save as draft") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
