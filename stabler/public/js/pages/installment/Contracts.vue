<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import MoneyInput from "../../components/MoneyInput.vue";

const session = useSession();
const company = computed(() => session.activeCompany);

const side = ref("sell");
const fromDate = ref("");
const toDate = ref("");

const loading = ref(false);
const error = ref("");
const contracts = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const detailError = ref("");
const paymentDefaults = ref(null);
const modesOfPayment = ref([]);
const collection = ref({
	amount: null,
	mode_of_payment: "",
	bank_account: "",
	posting_date: new Date().toISOString().slice(0, 10),
});
const collectionPreview = ref(null);
const collectionLoading = ref(false);
const collectionError = ref("");

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		contracts.value = await call("stabler.api.installment.list_contracts", {
			company: company.value,
			side: side.value,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load contracts.");
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	detailError.value = "";
	try {
		detail.value = await call("stabler.api.installment.contract_detail", {
			name,
			side: side.value,
		});
		await loadCollectionDefaults();
	} catch (err) {
		detailError.value = err?.message || t("Failed to load contract.");
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
	collectionPreview.value = null;
	collectionError.value = "";
}

async function loadCollectionDefaults() {
	if (!detail.value) return;
	const invoiceType = side.value === "sell" ? "Sales Invoice" : "Purchase Invoice";
	const [defaults, modes] = await Promise.all([
		call("stabler.api.money.payment_defaults_for_invoice", {
			company: company.value,
			invoice_type: invoiceType,
			invoice_name: detail.value.name,
		}),
		call("stabler.api.money.list_modes_of_payment", { limit: 100 }),
	]);
	paymentDefaults.value = defaults;
	modesOfPayment.value = modes || [];
	collection.value = {
		amount: null,
		mode_of_payment: modesOfPayment.value[0]?.name || "",
		bank_account: defaults.suggested_cash_bank_account || "",
		posting_date: new Date().toISOString().slice(0, 10),
	};
	collectionPreview.value = null;
	collectionError.value = "";
}

async function previewCollection() {
	if (!detail.value || !collection.value.amount) return;
	collectionLoading.value = true;
	collectionError.value = "";
	try {
		collectionPreview.value = await call("stabler.api.installment.collect_payment", {
			contract: detail.value.name,
			side: side.value,
			amount: collection.value.amount,
			posting_date: collection.value.posting_date,
			dry_run: 1,
		});
	} catch (err) {
		collectionPreview.value = null;
		collectionError.value = err?.message || t("Failed to preview collection.");
	} finally {
		collectionLoading.value = false;
	}
}

async function submitCollection() {
	if (!detail.value) return;
	collectionLoading.value = true;
	collectionError.value = "";
	try {
		await call("stabler.api.installment.collect_payment", {
			contract: detail.value.name,
			side: side.value,
			amount: collection.value.amount,
			mode_of_payment: collection.value.mode_of_payment,
			bank_account: collection.value.bank_account,
			posting_date: collection.value.posting_date,
			dry_run: 0,
		});
		await openDetail(detail.value.name);
		await load();
	} catch (err) {
		collectionError.value = err?.message || t("Failed to collect payment.");
	} finally {
		collectionLoading.value = false;
	}
}

const docstatusLabel = (s) =>
	s === 0 ? t("Draft") : s === 1 ? t("Submitted") : t("Cancelled");
const docstatusClass = (s) =>
	s === 0 ? "bg-yellow-lt" : s === 1 ? "bg-green-lt" : "bg-red-lt";

function scheduleStateClass(state) {
	return {
		paid: "bg-green-lt",
		partial: "bg-yellow-lt",
		overdue: "bg-red-lt",
		upcoming: "bg-blue-lt",
	}[state || "upcoming"];
}

function progressPercent(contract) {
	const total = Number(contract?.grand_total || 0);
	const outstanding = Number(contract?.outstanding_amount || 0);
	if (!total) return 0;
	return Math.max(0, Math.min(100, Math.round(((total - outstanding) / total) * 100)));
}

onMounted(load);
</script>

<template>
	<div class="card">
		<div class="card-header flex-wrap gap-2">
			<div class="card-title">{{ t("Contracts") }}</div>

			<!-- Sell / Buy pills -->
			<div class="btn-group" role="group">
				<input id="side-sell" v-model="side" type="radio" class="btn-check" value="sell" @change="load" />
				<label class="btn btn-outline-primary btn-sm" for="side-sell">{{ t("Sell") }}</label>
				<input id="side-buy" v-model="side" type="radio" class="btn-check" value="buy" @change="load" />
				<label class="btn btn-outline-primary btn-sm" for="side-buy">{{ t("Buy") }}</label>
			</div>

			<div class="ms-auto d-flex gap-2 align-items-end flex-wrap">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" />
				</div>
				<button type="button" class="btn btn-sm btn-outline-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!contracts.length"
			icon="ti-file-invoice"
			title="No contracts found"
			subtitle="Create a new Murabaha contract to get started."
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Date") }}</th>
						<th>{{ side === "sell" ? t("Customer") : t("Supplier") }}</th>
						<th class="text-end">{{ t("Total") }}</th>
						<th class="text-end">{{ t("Outstanding") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="c in contracts"
						:key="c.name"
						style="cursor: pointer"
						@click="openDetail(c.name)"
					>
						<td>{{ formatDate(c.posting_date) }}</td>
						<td>{{ c.party }}</td>
						<td class="text-end font-monospace">
							{{ formatMoney(c.grand_total, c.currency) }}
						</td>
						<td class="text-end font-monospace">
							{{ formatMoney(c.outstanding_amount, c.currency) }}
						</td>
						<td>
							<span class="badge" :class="docstatusClass(c.docstatus)">
								{{ docstatusLabel(c.docstatus) }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail offcanvas -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 600px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-file-invoice me-1"></i>{{ t("Contract detail") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detailError" class="alert alert-danger">{{ detailError }}</div>
			<div v-else-if="detail">
				<dl class="row mb-3">
					<dt class="col-5 text-secondary">{{ t("Contract") }}</dt>
					<dd class="col-7">{{ detail.name }}</dd>
					<dt class="col-5 text-secondary">{{ detail.side === "sell" ? t("Customer") : t("Supplier") }}</dt>
					<dd class="col-7">{{ detail.party }}</dd>
					<dt class="col-5 text-secondary">{{ t("Date") }}</dt>
					<dd class="col-7">{{ formatDate(detail.posting_date) }}</dd>
					<dt class="col-5 text-secondary">{{ t("Total") }}</dt>
					<dd class="col-7 font-monospace fw-semibold">
						{{ formatMoney(detail.grand_total, detail.currency) }}
					</dd>
					<dt class="col-5 text-secondary">{{ t("Outstanding") }}</dt>
					<dd class="col-7 font-monospace">
						{{ formatMoney(detail.outstanding_amount, detail.currency) }}
					</dd>
					<dt class="col-5 text-secondary">{{ t("Remarks") }}</dt>
					<dd class="col-7 text-secondary small">{{ detail.remarks || "—" }}</dd>
				</dl>
				<div class="mb-3">
					<div class="d-flex justify-content-between small text-secondary mb-1">
						<span>{{ t("Collection progress") }}</span>
						<span>{{ progressPercent(detail) }}%</span>
					</div>
					<div class="progress progress-sm">
						<div class="progress-bar" :style="{ width: `${progressPercent(detail)}%` }"></div>
					</div>
				</div>

				<div v-if="detail.docstatus === 1 && detail.outstanding_amount > 0" class="border rounded p-3 mb-3">
					<div class="d-flex align-items-center justify-content-between mb-2">
						<div class="fw-semibold">{{ t("Collect payment") }}</div>
						<span class="badge bg-blue-lt">{{ formatMoney(detail.outstanding_amount, detail.currency) }}</span>
					</div>
					<div v-if="collectionError" class="alert alert-danger py-2">{{ collectionError }}</div>
					<div class="row g-2">
						<div class="col-md-6">
							<label class="form-label">{{ t("Amount") }}</label>
							<MoneyInput
								v-model="collection.amount"
								:currency="detail.currency"
								:disabled="collectionLoading"
								@blur="previewCollection"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Posting date") }}</label>
							<DateInput v-model="collection.posting_date" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Mode of payment") }}</label>
							<select v-model="collection.mode_of_payment" class="form-select" :disabled="collectionLoading">
								<option v-for="mode in modesOfPayment" :key="mode.name" :value="mode.name">
									{{ mode.name }}
								</option>
							</select>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Cash/bank account") }}</label>
							<select v-model="collection.bank_account" class="form-select" :disabled="collectionLoading">
								<option v-for="account in paymentDefaults?.cash_bank_accounts || []" :key="account.name" :value="account.name">
									{{ account.name }}
								</option>
							</select>
						</div>
					</div>
					<div class="mt-2 d-flex gap-2 justify-content-end">
						<button type="button" class="btn btn-outline-secondary btn-sm" :disabled="collectionLoading || !collection.amount" @click="previewCollection">
							<i class="ti ti-list-check me-1"></i>{{ t("Preview") }}
						</button>
						<button
							type="button"
							class="btn btn-primary btn-sm"
							:disabled="collectionLoading || !collectionPreview || !collection.mode_of_payment || !collection.bank_account"
							@click="submitCollection"
						>
							<span v-if="collectionLoading" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-cash me-1"></i>{{ t("Collect") }}
						</button>
					</div>
					<div v-if="collectionPreview" class="mt-3">
						<div class="small text-secondary mb-1">
							{{ t("Allocation preview") }} · {{ t("Remaining") }}:
							<span class="font-monospace">{{ formatMoney(collectionPreview.remaining_balance, detail.currency) }}</span>
						</div>
						<table class="table table-sm table-vcenter table-no-stripe mb-0">
							<thead>
								<tr>
									<th>{{ t("Due date") }}</th>
									<th class="text-end">{{ t("Allocated") }}</th>
									<th class="text-end">{{ t("Remaining") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="row in collectionPreview.allocations" :key="`${row.row_index}-${row.due_date}`">
									<td>
										<div>{{ formatDate(row.due_date) }}</div>
										<div class="small text-secondary">{{ row.description }}</div>
									</td>
									<td class="text-end font-monospace">{{ formatMoney(row.allocated_amount, detail.currency) }}</td>
									<td class="text-end font-monospace">{{ formatMoney(row.outstanding, detail.currency) }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>

				<!-- Payment schedule -->
				<div class="fw-semibold small mb-2">{{ t("Payment schedule") }}</div>
				<div style="max-height: 420px; overflow: auto">
					<table class="table table-sm table-vcenter table-no-stripe">
						<thead>
							<tr>
								<th>#</th>
								<th>{{ t("Due date") }}</th>
								<th>{{ t("Description") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
								<th class="text-end">{{ t("Paid") }}</th>
								<th class="text-end">{{ t("Outstanding") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(row, idx) in detail.payment_schedule" :key="idx">
								<td class="text-secondary small">{{ idx }}</td>
								<td>{{ formatDate(row.due_date) }}</td>
								<td class="text-secondary small">
									<div>{{ row.description }}</div>
									<span class="badge" :class="scheduleStateClass(row.state)">
										{{ t(row.state || "upcoming") }}
									</span>
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(row.payment_amount, detail.currency) }}
								</td>
								<td class="text-end font-monospace text-success">
									{{ formatMoney(row.paid_amount, detail.currency) }}
								</td>
								<td class="text-end font-monospace">
									{{ formatMoney(row.outstanding, detail.currency) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>
</template>
