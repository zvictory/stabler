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
const startDate = ref("");
const endDate = ref("");
const customerName = ref("");
const customerType = ref("child");
const account = ref("");

const rows = ref([]);
const totals = ref({});

const fn = (v) => {
	if (v === null || v === undefined || isNaN(v)) return "0.00";
	const localeCode = user.value?.language === "en" ? "en-US" : "ru-RU";
	return new Intl.NumberFormat(localeCode, {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
		useGrouping: true,
	}).format(Number(v) || 0);
};

const fm = (v, ccy) => formatMoney(v, ccy || "UZS", user.value?.language || "en");

async function loadReport() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.reports.get_payments_register_report", {
			company: activeCompany.value,
			start_date: startDate.value || undefined,
			end_date: endDate.value || undefined,
			customer_name: customerName.value || undefined,
			customer_type: customerType.value,
			account: account.value || undefined,
		});
		rows.value = res.rows || [];
		totals.value = res.totals || {};
	} catch (err) {
		error.value = err?.message || t("Failed to load payments register.");
	} finally {
		loading.value = false;
	}
}

function exportCsv() {
	if (!rows.value.length) return;
	const headers = [
		"Date", "Payment #", "Reference No", "Amount (UZS)", "Counterparty",
		"Parent Customer", "Method", "Account Paid To", "Remarks", "Category",
		"Allocated Invoices", "FX Rate", "USD Equivalent ($)"
	];
	const csvRows = [headers.join(",")];
	for (const r of rows.value) {
		csvRows.push([
			`"${r.posting_date || ""}"`,
			`"${r.name}"`,
			`"${r.reference_no || ""}"`,
			r.uzs_amount,
			`"${r.counterparty}"`,
			`"${r.parent_customer || ""}"`,
			`"${r.method}"`,
			`"${r.paid_to}"`,
			`"${r.remarks || ""}"`,
			`"${r.category}"`,
			`"${(r.allocated_invoices || []).join("; ")}"`,
			r.fx_rate,
			r.usd_amount,
		].join(","));
	}
	const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
	const url = URL.createObjectURL(blob);
	const link = document.createElement("a");
	link.setAttribute("href", url);
	link.setAttribute("download", `payments_register_${new Date().toISOString().slice(0, 10)}.csv`);
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
}

onMounted(loadReport);
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
				<h2 class="page-title mb-0">{{ t("Payments Register") }}</h2>
				<div class="text-secondary small">{{ t("Submitted receive payment entries with counterparty, account breakdown, and USD equivalents") }}</div>
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
						<DateInput v-model="startDate" :placeholder="t('Start Date')" size="sm" />
					</div>
					<div class="col-md-3">
						<DateInput v-model="endDate" :placeholder="t('End Date')" size="sm" />
					</div>
					<div class="col-md-3">
						<input v-model="customerName" type="text" class="form-control form-control-sm" :placeholder="t('Counterparty / Customer name…')" @keyup.enter="loadReport">
					</div>
					<div class="col-md-3 d-flex gap-2">
						<select v-model="customerType" class="form-select form-select-sm" @change="loadReport">
							<option value="child">{{ t("Child Customer") }}</option>
							<option value="parent">{{ t("Parent Group") }}</option>
						</select>
						<button type="button" class="btn btn-secondary btn-sm" @click="loadReport">
							<i class="ti ti-search"></i>
						</button>
					</div>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- KPI Metric Strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total Payments Count") }}</div>
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ totals.row_count || 0 }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total UZS Received") }}</div>
						<div class="h3 mb-0 font-monospace text-success fw-bold">{{ fm(totals.uzs_total, 'UZS') }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Total USD Equivalent") }}</div>
						<div class="h3 mb-0 font-monospace text-azure fw-bold">{{ fm(totals.usd_total, 'USD') }}</div>
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
							<th>{{ t("Date") }}</th>
							<th>{{ t("Payment #") }}</th>
							<th>{{ t("Reference No") }}</th>
							<th class="text-end bg-green-lt text-green">{{ t("Amount (UZS)") }}</th>
							<th>{{ t("Counterparty") }}</th>
							<th>{{ t("Parent Customer") }}</th>
							<th>{{ t("Method") }}</th>
							<th>{{ t("Account Paid To") }}</th>
							<th>{{ t("Allocated Invoices") }}</th>
							<th class="text-end font-monospace">{{ t("FX Rate") }}</th>
							<th class="text-end bg-azure-lt text-azure">{{ t("USD Equivalent") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.name">
							<td class="small text-nowrap">{{ formatDate(r.posting_date) }}</td>
							<td class="font-monospace fw-bold text-primary">{{ r.name }}</td>
							<td class="font-monospace small">{{ r.reference_no || "—" }}</td>
							<td class="text-end font-monospace text-success bg-green-lt fw-bold">{{ fn(r.uzs_amount) }}</td>
							<td class="fw-semibold text-dark">{{ r.counterparty }}</td>
							<td>
								<span v-if="r.parent_customer" class="badge bg-secondary-lt">{{ r.parent_customer }}</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td><span class="badge bg-secondary-lt">{{ r.method }}</span></td>
							<td class="small text-secondary">{{ r.paid_to }}</td>
							<td>
								<div v-if="r.allocated_invoices && r.allocated_invoices.length" class="d-flex flex-wrap gap-1">
									<span v-for="inv in r.allocated_invoices" :key="inv" class="badge bg-azure-lt font-monospace" style="font-size: 11px">{{ inv }}</span>
								</div>
								<span v-else class="text-secondary small italic">—</span>
							</td>
							<td class="text-end font-monospace small text-secondary">{{ fn(r.fx_rate) }}</td>
							<td class="text-end font-monospace text-azure bg-azure-lt fw-bold">{{ fm(r.usd_amount, 'USD') }}</td>
						</tr>
						<tr v-if="!rows.length && !loading">
							<td colspan="11" class="text-center text-secondary py-4">{{ t("No payment register entries found.") }}</td>
						</tr>
					</tbody>
					<tfoot v-if="rows.length">
						<tr class="fw-bold bg-light">
							<td colspan="3" class="text-end">{{ t("Grand Totals") }} ({{ totals.row_count }} payments)</td>
							<td class="text-end font-monospace text-success bg-green-lt">{{ fn(totals.uzs_total) }} UZS</td>
							<td colspan="6"></td>
							<td class="text-end font-monospace text-azure bg-azure-lt">{{ fm(totals.usd_total, 'USD') }}</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>
	</div>
</template>
