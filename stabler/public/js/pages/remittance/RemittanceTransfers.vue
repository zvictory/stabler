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

const loading = ref(false);
const error = ref("");
const transfers = ref([]);

const fromDate = ref("");
const toDate = ref("");

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);
const detailError = ref("");

async function load() {
	if (!company.value) return;
	loading.value = true;
	error.value = "";
	try {
		transfers.value = await call("stabler.api.remittance.list_remittances", {
			company: company.value,
			from_date: fromDate.value || undefined,
			to_date: toDate.value || undefined,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load transfers.");
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
		detail.value = await call("stabler.api.remittance.remittance_detail", { name });
	} catch (err) {
		detailError.value = err?.message || t("Failed to load transfer detail.");
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
		<div class="card-header">
			<div class="card-title">{{ t("Transfers") }}</div>
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
			v-else-if="!transfers.length"
			icon="ti-send"
			title="No transfers found"
			subtitle="Create a new transfer to get started."
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Corridor / Memo") }}</th>
						<th class="text-end">{{ t("Amount sent") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="tr in transfers"
						:key="tr.name"
						style="cursor: pointer"
						@click="openDetail(tr.name)"
					>
						<td>{{ formatDate(tr.posting_date) }}</td>
						<td class="text-secondary small">{{ tr.cheque_no }}</td>
						<td class="text-truncate" style="max-width: 260px">{{ tr.user_remark }}</td>
						<td class="text-end font-monospace">
							{{ formatMoney(tr.send_amount, tr.send_currency) }}
						</td>
						<td>
							<span class="badge" :class="docstatusClass(tr.docstatus)">
								{{ docstatusLabel(tr.docstatus) }}
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
		style="visibility: visible; width: 560px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-send me-1"></i>{{ t("Transfer detail") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detailError" class="alert alert-danger">{{ detailError }}</div>
			<div v-else-if="detail">
				<div class="mb-3">
					<div class="text-secondary small">{{ t("Reference") }}</div>
					<div class="fw-semibold">{{ detail.name }}</div>
				</div>
				<div class="mb-3">
					<div class="text-secondary small">{{ t("Date") }}</div>
					<div>{{ formatDate(detail.posting_date) }}</div>
				</div>
				<div class="mb-3">
					<div class="text-secondary small">{{ t("Memo") }}</div>
					<div>{{ detail.user_remark || "—" }}</div>
				</div>
				<div class="mb-3">
					<div class="text-secondary small">{{ t("Status") }}</div>
					<span class="badge" :class="docstatusClass(detail.docstatus)">
						{{ docstatusLabel(detail.docstatus) }}
					</span>
				</div>

				<!-- JE accounts table -->
				<div class="mt-3">
					<div class="text-secondary small mb-1">{{ t("Journal Entry legs") }}</div>
					<table class="table table-sm table-no-stripe">
						<thead>
							<tr>
								<th>{{ t("Account") }}</th>
								<th class="text-end">{{ t("Debit") }}</th>
								<th class="text-end">{{ t("Credit") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="acc in detail.accounts" :key="acc.account">
								<td class="small">{{ acc.account_name || acc.account }}</td>
								<td class="text-end font-monospace small">
									<template v-if="acc.debit_in_account_currency > 0">
										{{ formatMoney(acc.debit_in_account_currency, acc.account_currency) }}
									</template>
									<template v-else>—</template>
								</td>
								<td class="text-end font-monospace small">
									<template v-if="acc.credit_in_account_currency > 0">
										{{ formatMoney(acc.credit_in_account_currency, acc.account_currency) }}
									</template>
									<template v-else>—</template>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>
</template>
