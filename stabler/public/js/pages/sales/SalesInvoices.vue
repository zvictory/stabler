<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import PaymentModal from "../../components/PaymentModal.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import RelatedDocuments from "../../components/RelatedDocuments.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();

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

// Group totals by transaction currency — UZS and USD must never share a sum.
const totalsByCurrency = computed(() => {
	const m = new Map();
	for (const r of rows.value) {
		const ccy = r.currency || currency.value;
		const bucket = m.get(ccy) || { currency: ccy, count: 0, grand: 0, outstanding: 0 };
		bucket.count += 1;
		bucket.grand += Number(r.grand_total || 0);
		bucket.outstanding += Number(r.outstanding_amount || 0);
		m.set(ccy, bucket);
	}
	return Array.from(m.values());
});
const totalCount = computed(() => rows.value.length);

// ──────────────── Submit / payment / return / amend actions ────────────────
const actionRunning = ref(false);
const actionError = ref("");
const paymentOpen = ref(false);
const PAYABLE_STATUSES = new Set(["Unpaid", "Overdue", "Partly Paid"]);
const canPay = computed(
	() => !!detail.value && detail.value.docstatus === 1 && PAYABLE_STATUSES.has(detail.value.status)
);
const canSubmit = computed(() => !!detail.value && detail.value.docstatus === 0);
const canCancel = computed(() => !!detail.value && detail.value.docstatus === 1);
const canReturn = computed(
	() =>
		!!detail.value &&
		detail.value.docstatus === 1 &&
		!detail.value.is_return &&
		detail.value.status !== "Return"
);
const canAmend = computed(() => !!detail.value && detail.value.docstatus === 2);

// Return modal
const returnOpen = ref(false);
const returnLines = ref([]);
const returnSubmitting = ref(false);
const returnError = ref("");

function openReturn() {
	returnError.value = "";
	returnLines.value = (detail.value?.items || []).map((it) => ({
		item_code: it.item_code,
		item_name: it.item_name || it.item_code,
		max_qty: Number(it.qty || 0),
		return_qty: Number(it.qty || 0),
	}));
	returnOpen.value = true;
}
function closeReturn() {
	if (returnSubmitting.value) return;
	returnOpen.value = false;
}

async function submitReturn() {
	returnError.value = "";
	returnSubmitting.value = true;
	try {
		const item_returns = returnLines.value
			.filter((r) => Number(r.return_qty) > 0)
			.map((r) => ({ item_code: r.item_code, qty: Number(r.return_qty) }));
		if (!item_returns.length) {
			returnError.value = "Enter at least one return qty.";
			return;
		}
		const res = await call("stabler.api.sales.create_sales_return", {
			sales_invoice: detail.value.name,
			posting_date: new Date().toISOString().slice(0, 10),
			item_returns,
			submit: 1,
		});
		returnOpen.value = false;
		await load();
		if (res?.name) router.push({ path: "/sales/invoices", query: { open: res.name } });
	} catch (err) {
		returnError.value = err?.message || "Failed to create return.";
	} finally {
		returnSubmitting.value = false;
	}
}

async function amendDoc() {
	if (!detail.value?.name) return;
	actionError.value = "";
	actionRunning.value = true;
	try {
		const res = await call("stabler.api.sales.amend_sales_invoice", { name: detail.value.name });
		await Promise.all([openDetail(res.name), load()]);
	} catch (err) {
		actionError.value = err?.message || "Amend failed.";
	} finally {
		actionRunning.value = false;
	}
}

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
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">To</label>
					<DateInput v-model="toDate" size="sm" />
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
			<div class="d-flex gap-4 small flex-wrap align-items-center">
				<div>Count: <strong>{{ totalCount }}</strong></div>
				<div v-for="b in totalsByCurrency" :key="b.currency" class="d-flex gap-3 align-items-center">
					<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
					<span>Total: <strong class="font-monospace">{{ formatMoney(b.grand, b.currency, user.language) }}</strong></span>
					<span>Outstanding: <strong class="text-red font-monospace">{{ formatMoney(b.outstanding, b.currency, user.language) }}</strong></span>
				</div>
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
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td>{{ formatDateTime(r.due_date) }}</td>
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
				<div class="d-flex align-items-center mb-3 gap-3 flex-wrap">
					<div>
						<h3 class="m-0 font-monospace">{{ detail.name }}</h3>
						<div class="small text-secondary">{{ detail.customer_name }}</div>
					</div>
					<span v-if="detail.is_return" class="badge bg-secondary-lt">Return</span>
					<span class="badge ms-auto" :class="statusBadge(detail.status)">{{ detail.status }}</span>
				</div>

				<div v-if="detail.return_against" class="alert alert-info py-2 small">
					<i class="ti ti-corner-down-left me-1"></i>
					Credit note for
					<button
						type="button"
						class="badge bg-blue-lt font-monospace border-0"
						style="cursor:pointer"
						@click="openDetail(detail.return_against)"
					>{{ detail.return_against }}</button>
				</div>

				<div v-if="detail.credit_notes?.length" class="alert alert-light py-2 small">
					<i class="ti ti-receipt-refund me-1"></i>
					Credit notes:
					<button
						v-for="cn in detail.credit_notes"
						:key="cn.name"
						type="button"
						class="badge bg-secondary-lt font-monospace ms-1 border-0"
						style="cursor:pointer"
						@click="openDetail(cn.name)"
					>{{ cn.name }}</button>
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
						v-if="canReturn"
						type="button"
						class="btn btn-outline-warning"
						:disabled="actionRunning"
						@click="openReturn"
					>
						<i class="ti ti-receipt-refund me-1"></i>Issue credit note
					</button>
					<router-link
						:to="'/sales/invoices/' + detail.name + '/print'"
						class="btn btn-outline-secondary"
					>
						<i class="ti ti-printer me-1"></i>Print
					</router-link>
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

				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">Posting date</div>
						<div class="datagrid-content">{{ formatDateTime(detail.posting_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">Due date</div>
						<div class="datagrid-content">{{ formatDateTime(detail.due_date) || "—" }}</div>
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
								<td class="text-end font-monospace">{{ it.qty }}</td>
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

				<RelatedDocuments doctype="Sales Invoice" :name="detail.name" />
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

	<!-- Return / credit note modal -->
	<div v-if="returnOpen" class="modal-backdrop fade show" @click="closeReturn"></div>
	<div v-if="returnOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeReturn">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">Issue credit note</h5>
					<button type="button" class="btn-close" @click="closeReturn" :disabled="returnSubmitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="returnError" class="alert alert-danger">{{ returnError }}</div>
					<p class="small text-secondary">Enter the quantity to return for each line. Leave 0 to exclude a line.</p>
					<table class="table table-sm table-no-stripe">
						<thead>
							<tr>
								<th>Item</th>
								<th class="text-end">Original qty</th>
								<th class="text-end" style="width:110px">Return qty</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(r, i) in returnLines" :key="i">
								<td>
									<div class="fw-semibold small">{{ r.item_name }}</div>
									<div class="small text-secondary font-monospace">{{ r.item_code }}</div>
								</td>
								<td class="text-end font-monospace">{{ r.max_qty }}</td>
								<td>
									<input
										v-model.number="r.return_qty"
										type="number"
										step="any"
										inputmode="decimal"
										:min="0"
										:max="r.max_qty"
										class="form-control form-control-sm font-monospace text-end"
										:disabled="returnSubmitting"
									/>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeReturn" :disabled="returnSubmitting">
						{{ t("Cancel") }}
					</button>
					<button type="button" class="btn btn-warning ms-auto" @click="submitReturn" :disabled="returnSubmitting">
						<span v-if="returnSubmitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-receipt-refund me-1"></i>Create credit note
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
