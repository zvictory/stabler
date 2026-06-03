<script setup>
import { computed, onMounted, ref } from "vue";
import { call } from "../../api/client.js";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";

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
	} catch (err) {
		detailError.value = err?.message || t("Failed to load contract.");
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

const docstatusLabel = (s) =>
	s === 0 ? t("Draft") : s === 1 ? t("Submitted") : t("Cancelled");
const docstatusClass = (s) =>
	s === 0 ? "bg-yellow-lt" : s === 1 ? "bg-green-lt" : "bg-red-lt";

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
								<td class="text-secondary small">{{ row.description }}</td>
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
