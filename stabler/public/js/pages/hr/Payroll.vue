<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const today = () => new Date().toISOString().slice(0, 10);
const firstOfMonth = () => {
	const d = new Date();
	return new Date(d.getFullYear(), d.getMonth(), 1).toISOString().slice(0, 10);
};
const lastOfMonth = () => {
	const d = new Date();
	return new Date(d.getFullYear(), d.getMonth() + 1, 0).toISOString().slice(0, 10);
};

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const fromDate = ref(firstOfMonth());
const toDate = ref(lastOfMonth());
const statusFilter = ref("");

const currency = computed(
	() => (session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency || "USD"
);
const money = (v, ccy) => formatMoney(v, ccy || currency.value, user.value.language);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr.list_salary_slips", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			status: statusFilter.value,
			limit: 300,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load salary slips.";
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch([activeCompany, fromDate, toDate, statusFilter], load);

// ----- Detail drawer -----
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.hr.salary_slip_detail", { name });
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

// ----- Run payroll modal -----
const runOpen = ref(false);
const running = ref(false);
const runError = ref("");
const runResult = ref(null);

function blankRun() {
	return {
		start_date: firstOfMonth(),
		end_date: lastOfMonth(),
		posting_date: today(),
		payroll_frequency: "Monthly",
	};
}
const runForm = ref(blankRun());

function openRun() {
	runForm.value = blankRun();
	runError.value = "";
	runResult.value = null;
	runOpen.value = true;
}
function closeRun() {
	runOpen.value = false;
}

async function execute(submit) {
	runError.value = "";
	runResult.value = null;
	running.value = true;
	try {
		const res = await call("stabler.api.hr.create_payroll_entry", {
			company: activeCompany.value,
			...runForm.value,
			submit: submit ? 1 : 0,
		});
		runResult.value = res;
		await load();
	} catch (err) {
		runError.value = err?.message || "Payroll run failed.";
	} finally {
		running.value = false;
	}
}

function statusBadge(s, docstatus) {
	if (docstatus === 2) return "bg-secondary-lt";
	if (s === "Submitted" || docstatus === 1) return "bg-success-lt";
	if (s === "Withheld") return "bg-yellow-lt";
	return "bg-azure-lt";
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-end">
				<div class="col-md-2">
					<label class="form-label small">{{ t("From") }}</label>
					<DateInput v-model="fromDate" />
				</div>
				<div class="col-md-2">
					<label class="form-label small">{{ t("To") }}</label>
					<DateInput v-model="toDate" />
				</div>
				<div class="col-md-3">
					<label class="form-label small">{{ t("Status") }}</label>
					<select v-model="statusFilter" class="form-select">
						<option value="">{{ t("All statuses") }}</option>
						<option value="Draft">{{ t("Draft") }}</option>
						<option value="Submitted">{{ t("Submitted") }}</option>
						<option value="Cancelled">{{ t("Cancelled") }}</option>
						<option value="Withheld">{{ t("Withheld") }}</option>
					</select>
				</div>
				<div class="col-md-5 d-flex justify-content-md-end gap-2">
					<button type="button" class="btn btn-ghost-secondary" @click="load">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
					<button type="button" class="btn btn-primary" @click="openRun">
						<i class="ti ti-cash me-1"></i>{{ t("Run payroll") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<EmptyState
		v-if="!loading && !error && !rows.length"
		icon="ti-cash"
		accentIcon="ti-player-play"
		tone="primary"
		:title="t('No salary slips yet')"
		:subtitle="t('Run a payroll cycle to generate salary slips for assigned employees.')"
	/>

	<div v-else-if="loading" class="card-body text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>

	<div v-else class="card">
		<div class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Slip") }}</th>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Period") }}</th>
						<th class="text-end">{{ t("Working") }}</th>
						<th class="text-end">{{ t("Paid days") }}</th>
						<th class="text-end">{{ t("Gross") }}</th>
						<th class="text-end">{{ t("Net") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" class="cursor-pointer" @click="openDetail(r.name)">
						<td class="font-monospace small">{{ r.name }}</td>
						<td>
							<div class="fw-semibold">{{ r.employee_name }}</div>
							<div class="small text-secondary font-monospace">{{ r.employee }}</div>
						</td>
						<td class="font-monospace small">{{ formatDateTime(r.start_date) }} → {{ formatDateTime(r.end_date) }}</td>
						<td class="text-end font-monospace">{{ Number(r.total_working_days || 0).toFixed(1) }}</td>
						<td class="text-end font-monospace">{{ Number(r.payment_days || 0).toFixed(1) }}</td>
						<td class="text-end font-monospace">{{ money(r.gross_pay, r.currency) }}</td>
						<td class="text-end font-monospace fw-bold">{{ money(r.net_pay, r.currency) }}</td>
						<td>
							<span class="badge" :class="statusBadge(r.status, r.docstatus)">
								{{ r.docstatus === 1 ? t("Submitted") : r.docstatus === 2 ? t("Cancelled") : (r.status || t("Draft")) }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div v-if="detailOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 580px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<span v-if="detail?.name" class="font-monospace small">{{ detail.name }}</span>
				<span v-else>{{ t("Salary slip") }}</span>
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5"><div class="spinner-border text-primary"></div></div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="mb-3">
					<div class="h3 m-0">{{ detail.employee_name }}</div>
					<div class="text-secondary font-monospace small">{{ formatDateTime(detail.start_date) }} → {{ formatDateTime(detail.end_date) }}</div>
				</div>
				<div class="row g-2 mb-3">
					<div class="col-6">
						<div class="card">
							<div class="card-body p-2 text-center">
								<div class="text-secondary small">{{ t("Gross pay") }}</div>
								<div class="h2 m-0 font-monospace">{{ money(detail.gross_pay, detail.currency) }}</div>
							</div>
						</div>
					</div>
					<div class="col-6">
						<div class="card bg-primary-lt">
							<div class="card-body p-2 text-center">
								<div class="text-secondary small">{{ t("Net pay") }}</div>
								<div class="h2 m-0 font-monospace fw-bold">{{ money(detail.net_pay, detail.currency) }}</div>
							</div>
						</div>
					</div>
				</div>
				<h5>{{ t("Earnings") }}</h5>
				<table class="table table-sm">
					<tbody>
						<tr v-for="(e, i) in detail.earnings" :key="i">
							<td>{{ e.component }}</td>
							<td class="text-end font-monospace">{{ money(e.amount, detail.currency) }}</td>
						</tr>
						<tr v-if="!detail.earnings.length"><td colspan="2" class="text-secondary">{{ t("No earnings") }}</td></tr>
					</tbody>
				</table>
				<h5 class="mt-3">{{ t("Deductions") }}</h5>
				<table class="table table-sm">
					<tbody>
						<tr v-for="(d, i) in detail.deductions" :key="i">
							<td>{{ d.component }}</td>
							<td class="text-end font-monospace text-danger">{{ money(d.amount, detail.currency) }}</td>
						</tr>
						<tr v-if="!detail.deductions.length"><td colspan="2" class="text-secondary">{{ t("No deductions") }}</td></tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>

	<!-- Run payroll modal -->
	<div v-if="runOpen" class="modal-backdrop fade show"></div>
	<div v-if="runOpen" class="modal modal-blur fade show d-block" tabindex="-1">
		<div class="modal-dialog">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Run payroll") }}</h5>
					<button type="button" class="btn-close" @click="closeRun"></button>
				</div>
				<div class="modal-body">
					<div v-if="runError" class="alert alert-danger">{{ runError }}</div>
					<div v-if="runResult" class="alert alert-success">
						<div>{{ t("Payroll entry") }}: <span class="font-monospace">{{ runResult.name }}</span></div>
						<div v-if="runResult.salary_slips?.length">
							{{ t("Generated salary slips") }}: {{ runResult.salary_slips.length }}
						</div>
						<div v-if="runResult.warning" class="text-warning small mt-1">{{ runResult.warning }}</div>
					</div>
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label">{{ t("Period start") }}</label>
							<DateInput v-model="runForm.start_date" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Period end") }}</label>
							<DateInput v-model="runForm.end_date" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Posting date") }}</label>
							<DateInput v-model="runForm.posting_date" />
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Frequency") }}</label>
							<select v-model="runForm.payroll_frequency" class="form-select">
								<option value="Monthly">{{ t("Monthly") }}</option>
								<option value="Bimonthly">{{ t("Bimonthly") }}</option>
								<option value="Weekly">{{ t("Weekly") }}</option>
								<option value="Daily">{{ t("Daily") }}</option>
							</select>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeRun">{{ t("Close") }}</button>
					<button type="button" class="btn btn-outline-primary" :disabled="running" @click="execute(false)">
						{{ t("Generate drafts") }}
					</button>
					<button type="button" class="btn btn-primary" :disabled="running" @click="execute(true)">
						<i class="ti ti-check me-1"></i>{{ t("Generate and submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
