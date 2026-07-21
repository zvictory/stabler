<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const loading = ref(false);
const error = ref("");
const piGroup = ref("");
const vendor = ref("");
const dateFrom = ref("");
const dateTo = ref("");
const status = ref("");

const rows = ref([]);
const totals = ref({ grand_buckets: {} });
const piGroups = ref([]);

const fn = (v) => {
	if (v === null || v === undefined || isNaN(v)) return "0.00";
	const localeCode = user.value?.language === "en" ? "en-US" : "ru-RU";
	return new Intl.NumberFormat(localeCode, {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
		useGrouping: true,
	}).format(Number(v) || 0);
};

const fm = (v, ccy) => formatMoney(v, ccy || "USD", user.value?.language || "en");

async function loadReport() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.reports.get_pi_group_container_status_report", {
			company: activeCompany.value,
			pi_group: piGroup.value || undefined,
			vendor: vendor.value || undefined,
			date_from: dateFrom.value || undefined,
			date_to: dateTo.value || undefined,
			status: status.value || undefined,
		});
		rows.value = res.rows || [];
		totals.value = res.totals || { grand_buckets: {} };
	} catch (err) {
		error.value = err?.message || t("Failed to load PI group container status report.");
	} finally {
		loading.value = false;
	}
}

async function loadRefData() {
	try {
		const groups = await call("stabler.api.imports.list_pi_groups", { company: activeCompany.value, limit_page_length: 200 });
		piGroups.value = groups.rows || [];
	} catch (_) {
		piGroups.value = [];
	}
}

function exportCsv() {
	if (!rows.value.length) return;
	const headers = [
		"Group Code", "Group Title", "Vendor", "PI Count", "CI Count",
		"Date From", "Date To", "Planned FCL", "Pending Containers",
		"Origin", "Transit", "Destination", "Delivered", "Total Containers", "Agreed Total", "Pending Amount"
	];
	const csvRows = [headers.join(",")];
	for (const r of rows.value) {
		const b = r.buckets || {};
		csvRows.push([
			`"${r.group_code}"`,
			`"${r.group_title}"`,
			`"${r.vendor_name}"`,
			r.pi_count,
			r.ci_count,
			`"${r.date_min || ""}"`,
			`"${r.date_max || ""}"`,
			r.planned_fcl,
			r.pending_containers,
			b.ORIGIN || 0,
			b.TRANSIT || 0,
			b.DESTINATION || 0,
			b.DELIVERED || 0,
			r.container_total,
			r.agreed_total,
			r.pending_amount,
		].join(","));
	}
	const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.setAttribute("href", url);
	link.setAttribute("download", `pi_group_container_status_${new Date().toISOString().slice(0, 10)}.csv`);
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
}

onMounted(() => {
	loadRefData();
	loadReport();
});
watch(activeCompany, loadReport);
</script>

<template>
	<div>
		<!-- Header -->
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-outline-secondary btn-icon me-3" @click="router.push('/reports')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ t("PI Group Container Status Report") }}</h2>
				<div class="text-secondary small">{{ t("Per-PIGroup planned FCL and container shipment lifecycle tracking") }}</div>
			</div>
			<div class="ms-auto d-flex gap-2">
				<button type="button" class="btn btn-outline-secondary btn-sm" :disabled="loading || !rows.length" @click="exportCsv">
					<i class="ti ti-file-spreadsheet me-1"></i>{{ t("Export CSV") }}
				</button>
				<button type="button" class="btn btn-primary btn-sm" :disabled="loading" @click="loadReport">
					<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
				</button>
			</div>
		</div>

		<!-- Filter Bar -->
		<div class="card mb-3">
			<div class="card-body py-2">
				<div class="row g-2 align-items-center">
					<div class="col-md-3">
						<select v-model="piGroup" class="form-select form-select-sm" @change="loadReport">
							<option value="">— {{ t("All PI Groups") }} —</option>
							<option v-for="g in piGroups" :key="g.name" :value="g.name">{{ g.group_title || g.name }}</option>
						</select>
					</div>
					<div class="col-md-3">
						<DateInput v-model="dateFrom" :placeholder="t('Date From')" size="sm" />
					</div>
					<div class="col-md-3">
						<DateInput v-model="dateTo" :placeholder="t('Date To')" size="sm" />
					</div>
					<div class="col-md-3 d-flex gap-2">
						<button type="button" class="btn btn-secondary btn-sm w-100" @click="loadReport">
							<i class="ti ti-search me-1"></i>{{ t("Filter") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- KPI Metric Strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-2">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total Groups") }}</div>
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ totals.group_count || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Planned FCL") }}</div>
						<div class="h3 mb-0 font-monospace text-azure fw-bold">{{ totals.grand_fcl || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("In Transit") }}</div>
						<div class="h3 mb-0 font-monospace text-info fw-bold">{{ (totals.grand_buckets || {}).TRANSIT || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Delivered") }}</div>
						<div class="h3 mb-0 font-monospace text-success fw-bold">{{ (totals.grand_buckets || {}).DELIVERED || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total Containers") }}</div>
						<div class="h3 mb-0 font-monospace text-dark fw-bold">{{ totals.grand_containers || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Grand Agreed") }}</div>
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ fm(totals.grand_agreed_total) }}</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Data Table -->
		<div class="card mb-3">
			<div class="table-responsive" style="max-height: 620px; overflow-y: auto;">
				<table class="table table-sm table-hover align-middle mb-0">
					<thead style="position: sticky; top: 0; z-index: 1">
						<tr>
							<th>{{ t("Group Code / Title") }}</th>
							<th>{{ t("Supplier") }}</th>
							<th class="text-center">{{ t("PIs") }}</th>
							<th class="text-center">{{ t("CIs") }}</th>
							<th>{{ t("Date Range") }}</th>
							<th class="text-end bg-azure-lt text-azure">{{ t("Planned FCL") }}</th>
							<th class="text-end bg-warning-lt text-warning">{{ t("Pending Cont.") }}</th>
							<th class="text-center bg-orange-lt text-orange">{{ t("Origin") }}</th>
							<th class="text-center bg-info-lt text-info">{{ t("In Transit") }}</th>
							<th class="text-center bg-purple-lt text-purple">{{ t("Destination") }}</th>
							<th class="text-center bg-green-lt text-green">{{ t("Delivered") }}</th>
							<th class="text-end fw-bold">{{ t("Total Cont.") }}</th>
							<th class="text-end bg-blue-lt text-blue">{{ t("Agreed Amount") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.group_code">
							<td class="font-monospace fw-bold text-primary">
								{{ r.group_code }}
								<div class="small text-secondary fw-normal">{{ r.group_title }}</div>
							</td>
							<td class="fw-semibold text-dark">{{ r.vendor_name }}</td>
							<td class="text-center font-monospace"><span class="badge bg-secondary-lt">{{ r.pi_count }}</span></td>
							<td class="text-center font-monospace"><span class="badge bg-azure-lt">{{ r.ci_count }}</span></td>
							<td class="small font-monospace">{{ formatDate(r.date_min) }} … {{ formatDate(r.date_max) }}</td>
							<td class="text-end font-monospace text-azure bg-azure-lt fw-semibold">{{ r.planned_fcl }}</td>
							<td class="text-end font-monospace text-warning bg-warning-lt fw-semibold">{{ r.pending_containers }}</td>
							<td class="text-center font-monospace text-orange bg-orange-lt">{{ (r.buckets || {}).ORIGIN || 0 }}</td>
							<td class="text-center font-monospace text-info bg-info-lt">{{ (r.buckets || {}).TRANSIT || 0 }}</td>
							<td class="text-center font-monospace text-purple bg-purple-lt">{{ (r.buckets || {}).DESTINATION || 0 }}</td>
							<td class="text-center font-monospace text-green bg-green-lt fw-bold">{{ (r.buckets || {}).DELIVERED || 0 }}</td>
							<td class="text-end font-monospace fw-bold">{{ r.container_total }}</td>
							<td class="text-end font-monospace text-blue bg-blue-lt fw-semibold">{{ fm(r.agreed_total) }}</td>
						</tr>
						<tr v-if="!rows.length && !loading">
							<td colspan="13" class="text-center text-secondary py-4">{{ t("No PI group container records found.") }}</td>
						</tr>
					</tbody>
					<tfoot v-if="rows.length">
						<tr class="fw-bold bg-light">
							<td colspan="5" class="text-end">{{ t("Grand Totals") }} ({{ totals.group_count }} Groups)</td>
							<td class="text-end font-monospace text-azure bg-azure-lt">{{ totals.grand_fcl }}</td>
							<td class="text-end font-monospace text-warning bg-warning-lt">{{ totals.grand_pending }}</td>
							<td class="text-center font-monospace text-orange bg-orange-lt">{{ (totals.grand_buckets || {}).ORIGIN || 0 }}</td>
							<td class="text-center font-monospace text-info bg-info-lt">{{ (totals.grand_buckets || {}).TRANSIT || 0 }}</td>
							<td class="text-center font-monospace text-purple bg-purple-lt">{{ (totals.grand_buckets || {}).DESTINATION || 0 }}</td>
							<td class="text-center font-monospace text-green bg-green-lt">{{ (totals.grand_buckets || {}).DELIVERED || 0 }}</td>
							<td class="text-end font-monospace fw-bold">{{ totals.grand_containers }}</td>
							<td class="text-end font-monospace text-blue bg-blue-lt">{{ fm(totals.grand_agreed_total) }}</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>
	</div>
</template>
