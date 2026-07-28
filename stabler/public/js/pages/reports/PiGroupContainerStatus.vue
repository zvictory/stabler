<script setup>
import { onMounted, ref, watch } from "vue";
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
// Which groups have their real PI/CI numbers unfolded. Keyed by the ERPNext
// name — the only value guaranteed unique.
const expanded = ref({});
const toggle = (k) => { expanded.value[k] = !expanded.value[k]; };

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
		"Origin", "Transit", "Destination", "Delivered", "Total Containers", "Agreed Total", "Pending Amount",
		// Appended, never inserted: the amounts row below carries a run of five
		// blanks whose alignment a mid-list column would silently shift.
		"PI Numbers", "CI Numbers"
	];
	const csvRows = [headers.join(",")];
	for (const r of rows.value) {
		const b = r.buckets || {};
		const a = r.amounts || {};
		// Row 1: container counts. Row 2: the money in those exact columns —
		// the spec's dual-row grid, mirrored into the export.
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
			`"${(r.pis || []).join('; ')}"`,
			`"${(r.cis || []).join('; ')}"`,
		].join(","));
		csvRows.push([
			`"${r.group_code}"`,
			`"${t("Amounts")} (${r.currency || "USD"})"`,
			"", "", "", "", "",
			r.agreed_total,
			r.pending_amount,
			a.ORIGIN || 0,
			a.TRANSIT || 0,
			a.DESTINATION || 0,
			a.DELIVERED || 0,
			r.ci_agreed_total || 0,
			"", "",
			"", "",
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
							<!-- list_pi_groups returns code/title (imports.py); the old
							     `group_title` was never a field, so every option fell
							     through to the IPG- autoname. -->
							<option v-for="g in piGroups" :key="g.name" :value="g.name">{{ g.code || g.title || g.name }}</option>
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
						<div class="font-weight-medium text-secondary small">{{ t("Origin") }}</div>
						<div class="h3 mb-0 font-monospace text-orange fw-bold">{{ (totals.grand_buckets || {}).ORIGIN || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("At Destination") }}</div>
						<div class="h3 mb-0 font-monospace text-purple fw-bold">{{ (totals.grand_buckets || {}).DESTINATION || 0 }}</div>
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
						</tr>
					</thead>
					<tbody>
						<template v-for="r in rows" :key="r.group_name">
							<!-- Row 1: container counts -->
							<tr>
								<td rowspan="2" class="font-monospace fw-bold text-primary align-top" :title="r.group_name">
									<router-link :to="{ path: '/imports/pi-groups', query: { group: r.group_name } }" class="text-primary text-decoration-none">{{ r.group_code }}</router-link>
									<div v-if="r.group_title && r.group_title !== r.group_code" class="small text-secondary fw-normal">{{ r.group_title }}</div>
								</td>
								<td rowspan="2" class="fw-semibold text-dark align-top">{{ r.vendor_name }}</td>
								<td rowspan="2" class="text-center font-monospace align-top">
									<button type="button" class="badge bg-secondary-lt border-0" :disabled="!r.pi_count" @click="toggle(r.group_name)">
										{{ r.pi_count }}<i v-if="r.pi_count" class="ti ms-1" :class="expanded[r.group_name] ? 'ti-chevron-up' : 'ti-chevron-down'"></i>
									</button>
								</td>
								<td rowspan="2" class="text-center font-monospace align-top">
									<button type="button" class="badge bg-azure-lt border-0" :disabled="!r.ci_count" @click="toggle(r.group_name)">
										{{ r.ci_count }}<i v-if="r.ci_count" class="ti ms-1" :class="expanded[r.group_name] ? 'ti-chevron-up' : 'ti-chevron-down'"></i>
									</button>
								</td>
								<td rowspan="2" class="small font-monospace align-top">{{ formatDate(r.date_min) }} … {{ formatDate(r.date_max) }}</td>
								<td class="text-end font-monospace text-azure bg-azure-lt fw-semibold">{{ r.planned_fcl }}</td>
								<td class="text-end font-monospace fw-semibold" :class="r.pending_containers < 0 ? 'text-danger bg-red-lt' : 'text-warning bg-warning-lt'">{{ r.pending_containers }}</td>
								<td class="text-center font-monospace text-orange bg-orange-lt">{{ (r.buckets || {}).ORIGIN || 0 }}</td>
								<td class="text-center font-monospace text-info bg-info-lt">{{ (r.buckets || {}).TRANSIT || 0 }}</td>
								<td class="text-center font-monospace text-purple bg-purple-lt">{{ (r.buckets || {}).DESTINATION || 0 }}</td>
								<td class="text-center font-monospace text-green bg-green-lt fw-bold">{{ (r.buckets || {}).DELIVERED || 0 }}</td>
								<td class="text-end font-monospace fw-bold">{{ r.container_total }}</td>
							</tr>
							<!-- Row 2: the money in those exact columns (spec's dual-row grid) -->
							<tr class="pgr-amounts">
								<td class="text-end font-monospace small">{{ fm(r.agreed_total, r.currency) }}</td>
								<td class="text-end font-monospace small" :class="{ 'text-danger': r.pending_amount < 0 }">{{ fm(r.pending_amount, r.currency) }}</td>
								<td class="text-end font-monospace small">{{ fm((r.amounts || {}).ORIGIN, r.currency) }}</td>
								<td class="text-end font-monospace small">{{ fm((r.amounts || {}).TRANSIT, r.currency) }}</td>
								<td class="text-end font-monospace small">{{ fm((r.amounts || {}).DESTINATION, r.currency) }}</td>
								<td class="text-end font-monospace small">{{ fm((r.amounts || {}).DELIVERED, r.currency) }}</td>
								<td class="text-end font-monospace small fw-semibold">{{ fm(r.ci_agreed_total, r.currency) }}</td>
							</tr>
							<!-- Row 3 (on demand): the numbers the business actually
							     quotes — supplier PI refs and CI numbers, never autonames. -->
							<tr v-if="expanded[r.group_name]" class="pgr-numbers">
								<td colspan="12">
									<div class="mb-1">
										<span class="text-secondary small me-2">{{ t("PIs") }}:</span>
										<span v-for="p in (r.pis || [])" :key="p" class="badge bg-secondary-lt font-monospace me-1 mb-1">{{ p }}</span>
										<span v-if="!(r.pis || []).length" class="text-secondary">—</span>
									</div>
									<div>
										<span class="text-secondary small me-2">{{ t("CIs") }}:</span>
										<span v-for="c in (r.cis || [])" :key="c" class="badge bg-azure-lt font-monospace me-1 mb-1">{{ c }}</span>
										<span v-if="!(r.cis || []).length" class="text-secondary">—</span>
									</div>
								</td>
							</tr>
						</template>
						<tr v-if="!rows.length && !loading">
							<td colspan="12" class="text-center text-secondary py-4">{{ t("No PI group container records found.") }}</td>
						</tr>
					</tbody>
					<tfoot v-if="rows.length">
						<tr class="fw-bold bg-light">
							<td colspan="5" class="text-end">{{ t("Grand Totals") }} · {{ totals.group_count }}</td>
							<td class="text-end font-monospace text-azure bg-azure-lt">{{ totals.grand_fcl }}</td>
							<td class="text-end font-monospace" :class="totals.grand_pending < 0 ? 'text-danger bg-red-lt' : 'text-warning bg-warning-lt'">{{ totals.grand_pending }}</td>
							<td class="text-center font-monospace text-orange bg-orange-lt">{{ (totals.grand_buckets || {}).ORIGIN || 0 }}</td>
							<td class="text-center font-monospace text-info bg-info-lt">{{ (totals.grand_buckets || {}).TRANSIT || 0 }}</td>
							<td class="text-center font-monospace text-purple bg-purple-lt">{{ (totals.grand_buckets || {}).DESTINATION || 0 }}</td>
							<td class="text-center font-monospace text-green bg-green-lt">{{ (totals.grand_buckets || {}).DELIVERED || 0 }}</td>
							<td class="text-end font-monospace fw-bold">{{ totals.grand_containers }}</td>
						</tr>
						<tr class="pgr-amounts fw-semibold">
							<td colspan="5" class="text-end small text-secondary">{{ t("Amounts") }}</td>
							<td class="text-end font-monospace small">{{ fm(totals.grand_agreed_total) }}</td>
							<td class="text-end font-monospace small" :class="{ 'text-danger': totals.grand_pending_amount < 0 }">{{ fm(totals.grand_pending_amount) }}</td>
							<td class="text-end font-monospace small">{{ fm((totals.grand_amounts || {}).ORIGIN) }}</td>
							<td class="text-end font-monospace small">{{ fm((totals.grand_amounts || {}).TRANSIT) }}</td>
							<td class="text-end font-monospace small">{{ fm((totals.grand_amounts || {}).DESTINATION) }}</td>
							<td class="text-end font-monospace small">{{ fm((totals.grand_amounts || {}).DELIVERED) }}</td>
							<td class="text-end font-monospace small">{{ fm(totals.grand_ci_agreed_total) }}</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>
	</div>
</template>

<style scoped>
.pgr-amounts td { background: var(--tblr-bg-surface-secondary, #f6f8fb); border-top: 0; }
.pgr-numbers td { background: var(--tblr-bg-surface-secondary, #f6f8fb); border-top: 0; }
</style>
