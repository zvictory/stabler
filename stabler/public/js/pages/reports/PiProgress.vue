<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const loading = ref(false);
const error = ref("");
const search = ref("");
const vendor = ref("");
const vendorName = ref("");
const piGroup = ref("");
const status = ref("");
const sortBy = ref("-date");

const rows = ref([]);
const totals = ref({});
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
		const res = await call("stabler.api.reports.get_pi_progress_report", {
			company: activeCompany.value,
			search: search.value || undefined,
			vendor: vendor.value || undefined,
			pi_group: piGroup.value || undefined,
			status: status.value || undefined,
			sort_by: sortBy.value,
		});
		rows.value = res.rows || [];
		totals.value = res.totals || {};
	} catch (err) {
		error.value = err?.message || t("Failed to load PI progress report.");
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
		"PI Number", "Supplier", "PI Group", "Date", "Status",
		"Agreed Total", "Docs Total", "Cash Diff", "Advance Paid", "Advance %",
		"CI Count", "Allocated to CIs", "Allocation %", "70% Paid", "Overall Progress %"
	];
	const csvRows = [headers.join(",")];
	for (const r of rows.value) {
		csvRows.push([
			`"${r.supplier_pi_ref || r.pi_name}"`,
			`"${r.vendor_name || r.vendor}"`,
			`"${r.import_pi_group}"`,
			`"${r.pi_date || ""}"`,
			`"${r.status}"`,
			r.agreed_total,
			r.docs_total,
			r.cash_difference,
			r.total_advance,
			r.advance_pct,
			r.ci_count,
			r.total_allocated,
			r.allocation_pct,
			r.total_70_paid,
			r.overall_pct,
		].join(","));
	}
	const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.setAttribute("href", url);
	link.setAttribute("download", `pi_progress_report_${new Date().toISOString().slice(0, 10)}.csv`);
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
}

onMounted(() => {
	loadRefData();
	loadReport();
});
watch([activeCompany, sortBy], loadReport);
</script>

<template>
	<div>
		<!-- Header -->
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-outline-secondary btn-icon me-3" @click="router.push('/reports')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ t("PI Progress Report") }}</h2>
				<div class="text-secondary small">{{ t("Lifecycle tracking and financial progress per proforma invoice") }}</div>
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
						<input v-model="search" type="text" class="form-control form-control-sm" :placeholder="t('Search PI number, supplier, group…')" @keyup.enter="loadReport">
					</div>
					<div class="col-md-3">
						<select v-model="piGroup" class="form-select form-select-sm" @change="loadReport">
							<option value="">— {{ t("All PI Groups") }} —</option>
							<option v-for="g in piGroups" :key="g.name" :value="g.name">{{ g.group_title || g.name }}</option>
						</select>
					</div>
					<div class="col-md-2">
						<select v-model="status" class="form-select form-select-sm" @change="loadReport">
							<option value="">— {{ t("All Statuses") }} —</option>
							<option value="DRAFT">DRAFT</option>
							<option value="CONFIRMED">CONFIRMED</option>
						</select>
					</div>
					<div class="col-md-2">
						<select v-model="sortBy" class="form-select form-select-sm">
							<option value="-date">{{ t("Date (Newest)") }}</option>
							<option value="date">{{ t("Date (Oldest)") }}</option>
							<option value="-agreed_total">{{ t("Agreed Total (High)") }}</option>
							<option value="-overall_pct">{{ t("Progress % (High)") }}</option>
						</select>
					</div>
					<div class="col-md-2 d-flex gap-2">
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
			<div class="col-sm-6 col-lg-2-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Grand Agreed Total") }}</div>
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ fm(totals.grand_agreed) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Grand Advance Paid") }}</div>
						<div class="h3 mb-0 font-monospace text-success fw-bold">{{ fm(totals.grand_advance) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Allocated to CIs") }}</div>
						<div class="h3 mb-0 font-monospace text-azure fw-bold">{{ fm(totals.grand_allocated) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("70% Paid (Transit)") }}</div>
						<div class="h3 mb-0 font-monospace text-info fw-bold">{{ fm(totals.grand_70_paid) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-2-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Grand Remaining") }}</div>
						<div class="h3 mb-0 font-monospace text-warning fw-bold">{{ fm(totals.grand_remaining) }}</div>
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
							<th>{{ t("PI Ref / Number") }}</th>
							<th>{{ t("Supplier") }}</th>
							<th>{{ t("Group") }}</th>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end bg-blue-lt text-blue">{{ t("Agreed Total") }}</th>
							<th class="text-end bg-green-lt text-green">{{ t("Docs Total") }}</th>
							<th class="text-end bg-warning-lt text-warning">{{ t("Cash Diff") }}</th>
							<th class="text-end">{{ t("30% Advance") }}</th>
							<th class="text-end">{{ t("Adv %") }}</th>
							<th class="text-center">{{ t("CIs") }}</th>
							<th class="text-end">{{ t("Allocated") }}</th>
							<th class="text-end">{{ t("70% Paid") }}</th>
							<th style="min-width: 140px">{{ t("Overall Progress") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.pi_name" style="cursor: pointer" @click="router.push('/imports/proformas/' + r.pi_name)">
							<td class="font-monospace fw-bold text-primary">{{ r.supplier_pi_ref || r.pi_name }}</td>
							<td>
								<div class="fw-semibold text-dark">{{ r.vendor_name }}</div>
								<div class="font-monospace text-secondary" style="font-size: 11px">{{ r.vendor }}</div>
							</td>
							<td>
								<span v-if="r.import_pi_group" class="badge bg-secondary-lt font-monospace">{{ r.import_pi_group }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="small text-nowrap">{{ formatDate(r.pi_date) }}</td>
							<td><span class="badge bg-secondary-lt">{{ r.status }}</span></td>
							<td class="text-end font-monospace text-blue bg-blue-lt fw-semibold">{{ fn(r.agreed_total) }}</td>
							<td class="text-end font-monospace text-green bg-green-lt fw-semibold">{{ fn(r.docs_total) }}</td>
							<td class="text-end font-monospace text-warning bg-warning-lt fw-semibold">{{ fn(r.cash_difference) }}</td>
							<td class="text-end font-monospace text-success fw-semibold">{{ fn(r.total_advance) }}</td>
							<td class="text-end font-monospace small">{{ r.advance_pct }}%</td>
							<td class="text-center font-monospace"><span class="badge bg-azure-lt">{{ r.ci_count }}</span></td>
							<td class="text-end font-monospace text-azure">{{ fn(r.total_allocated) }}</td>
							<td class="text-end font-monospace text-info">{{ fn(r.total_70_paid) }}</td>
							<td>
								<div class="d-flex align-items-center gap-2">
									<div class="progress flex-grow-1" style="height: 6px;">
										<div class="progress-bar" :class="r.overall_pct >= 100 ? 'bg-success' : 'bg-primary'" :style="{ width: r.overall_pct + '%' }"></div>
									</div>
									<span class="font-monospace small fw-bold" style="min-width: 38px;">{{ r.overall_pct }}%</span>
								</div>
							</td>
						</tr>
						<tr v-if="!rows.length && !loading">
							<td colspan="14" class="text-center text-secondary py-4">{{ t("No proforma invoices found.") }}</td>
						</tr>
					</tbody>
					<tfoot v-if="rows.length">
						<tr class="fw-bold bg-light">
							<td colspan="5" class="text-end">{{ t("Grand Totals") }} ({{ totals.pi_count }} PIs)</td>
							<td class="text-end font-monospace text-blue bg-blue-lt">{{ fn(totals.grand_agreed) }}</td>
							<td class="text-end font-monospace text-green bg-green-lt">—</td>
							<td class="text-end font-monospace text-warning bg-warning-lt">—</td>
							<td class="text-end font-monospace text-success">{{ fn(totals.grand_advance) }}</td>
							<td class="text-end font-monospace">—</td>
							<td class="text-center font-monospace">—</td>
							<td class="text-end font-monospace text-azure">{{ fn(totals.grand_allocated) }}</td>
							<td class="text-end font-monospace text-info">{{ fn(totals.grand_70_paid) }}</td>
							<td class="font-monospace text-primary">{{ fn(totals.grand_remaining) }} rem</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>
	</div>
</template>
