<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import PaymentModal from "../../components/PaymentModal.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
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

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const STATUSES = ["", "Paid", "Unpaid", "Overdue", "Partly Paid", "Return", "Credit Note Issued", "Draft"];

const statusBadge = (s) => {
	const m = {
		Paid: "bg-green-lt",
		Unpaid: "bg-yellow-lt",
		Overdue: "bg-red-lt",
		Return: "bg-secondary-lt",
		"Credit Note Issued": "bg-purple-lt",
		"Partly Paid": "bg-blue-lt",
		Draft: "bg-secondary-lt",
	};
	return m[s] || "bg-secondary-lt";
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sales.list_sales_invoices", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: status.value || undefined,
			limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load invoices.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.sales.sales_invoice_detail", { name });
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

const totals = computed(() => ({
	count: rows.value.length,
	grand: rows.value.reduce((s, r) => s + Number(r.grand_total || 0), 0),
	outstanding: rows.value.reduce((s, r) => s + Number(r.outstanding_amount || 0), 0),
}));

// ──────────────── Submit / payment actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const paymentOpen = ref(false);
const PAYABLE_STATUSES = new Set(["Unpaid", "Overdue", "Partly Paid"]);
const canPay = computed(
	() => !!detail.value && detail.value.docstatus === 1 && PAYABLE_STATUSES.has(detail.value.status)
);
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(() => !!detail.value && detail.value.docstatus === 1);

async function submitDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.submit_sales_invoice", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Submit failed.";
	} finally {
		actionRunning.value = false;
	}
}

async function cancelDoc() {
	if (!detail.value?.name) return;
	if (!window.confirm(`Cancel invoice ${detail.value.name}? This is reversible only by amendment.`)) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		await call("stabler.api.sales.cancel_sales_invoice", { name: detail.value.name });
		await Promise.all([openDetail(detail.value.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Cancel failed.";
	} finally {
		actionRunning.value = false;
	}
}

function openPayment() {
	actionError.value = "";
	paymentOpen.value = true;
}
async function onPaid() {
	paymentOpen.value = false;
	if (detail.value?.name) await Promise.all([openDetail(detail.value.name), load()]);
}

onMounted(async () => {
	await load();
	const openName = route.query?.open;
	if (openName) openDetail(String(openName));
});
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">Sales Invoices</div>
			<div class="ms-auto d-flex gap-2 align-items-end flex-wrap">
				<div>
					<label class="form-label small mb-1">From</label>
					<input v-model="fromDate" type="date" class="form-control form-control-sm" />
				</div>
				<div>
					<label class="form-label small mb-1">To</label>
					<input v-model="toDate" type="date" class="form-control form-control-sm" />
				</div>
				<div style="min-width: 150px">
					<label class="form-label small mb-1">Status</label>
					<select v-model="status" class="form-select form-select-sm">
						<option v-for="s in STATUSES" :key="s" :value="s">{{ s || "All" }}</option>
					</select>
				</div>
				<button type="button" class="btn btn-sm btn-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>Apply
				</button>
			</div>
		</div>

		<div v-if="rows.length" class="card-body py-2 border-bottom bg-light">
			<div class="d-flex gap-4 small">
				<div>Count: <strong>{{ totals.count }}</strong></div>
				<div>Total: <strong class="font-monospace">{{ formatMoney(totals.grand, currency, user.language) }}</strong></div>
				<div>Outstanding: <strong class="text-red font-monospace">{{ formatMoney(totals.outstanding, currency, user.language) }}</strong></div>
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
			icon="ti-file-invoice"
			accentIcon="ti-arrow-right"
			tone="primary"
			title="No invoices in this range"
			subtitle="Sales Invoices are created from submitted Sales Orders. Open a Sales Order and use 'Create Invoice'."
		>
			<template #actions>
				<router-link to="/sales/orders" class="btn btn-primary">
					<i class="ti ti-clipboard-check me-1"></i>Go to Sales Orders
				</router-link>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>Date</th>
						<th>Due</th>
						<th>Customer</th>
						<th class="text-end">Total</th>
						<th class="text-end">Outstanding</th>
						<th>Status</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ r.posting_date }}</td>
						<td>{{ r.due_date }}</td>
						<td>
							<div class="fw-semibold">{{ r.customer_name || r.customer }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatMoney(r.grand_total, r.currency || currency, user.language) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.outstanding_amount, r.currency || currency, user.language) }}</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ r.status }}</span></td>
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
			<h5 class="offcanvas-title">Sales Invoice</h5>
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
					<span class="badge ms-auto" :class="statusBadge(detail.status)">{{ detail.status }}</span>
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
						<i v-else class="ti ti-check me-1"></i>Submit
					</button>
					<button
						v-if="canPay"
						type="button"
						class="btn btn-success"
						:disabled="actionRunning"
						@click="openPayment"
					>
						<i class="ti ti-cash me-1"></i>Receive payment
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
				</div>

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">Posting date</div>
						<div class="datagrid-content">{{ detail.posting_date }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Due date</div>
						<div class="datagrid-content">{{ detail.due_date || "—" }}</div>
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
						<div class="datagrid-title">Taxes</div>
						<div class="datagrid-content font-monospace">{{ formatMoney(detail.total_taxes_and_charges, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Grand total</div>
						<div class="datagrid-content font-monospace fw-bold">{{ formatMoney(detail.grand_total, detail.currency, user.language) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Outstanding</div>
						<div class="datagrid-content font-monospace text-red">{{ formatMoney(detail.outstanding_amount, detail.currency, user.language) }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">Items</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>Item</th>
								<th class="text-end">Qty</th>
								<th>UOM</th>
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
								<td class="text-end font-monospace">{{ it.qty }}</td>
								<td>{{ it.uom || "—" }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.rate, detail.currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(it.amount, detail.currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div v-if="detail.remarks" class="mt-3 small text-secondary">{{ detail.remarks }}</div>

				<div v-if="detail.taxes?.length" class="mt-3">
					<h6 class="text-uppercase text-secondary small mb-2">Taxes</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>Description</th>
									<th class="text-end">Rate</th>
									<th class="text-end">Amount</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(t, i) in detail.taxes" :key="i">
									<td>{{ t.description }}</td>
									<td class="text-end font-monospace">{{ t.rate }}%</td>
									<td class="text-end font-monospace">{{ formatMoney(t.tax_amount, detail.currency, user.language) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	</div>

	<PaymentModal
		:open="paymentOpen"
		invoice-type="Sales Invoice"
		:invoice-name="detail?.name || ''"
		@close="paymentOpen = false"
		@paid="onPaid"
	/>
</template>
