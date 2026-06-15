<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const currency = computed(
	() => (session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency || "UZS",
);
const lang = computed(() => user.value?.language || "en");

const today = todayIso();
const yearStart = `${today.slice(0, 4)}-01-01`;
const fromDate = ref(yearStart);
const toDate = ref(today);

const loading = ref(false);
const error = ref("");
const report = ref(null);

function money(v) {
	return formatMoney(Number(v || 0), currency.value, lang.value);
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.crm.crm_report", {
			from_date: fromDate.value,
			to_date: toDate.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

const summaryTiles = computed(() => {
	const s = report.value?.summary;
	if (!s) return [];
	return [
		{ label: t("New outlets"), value: s.new_outlets || 0 },
		{ label: t("Open pipeline") + " /" + t("mo"), value: money(s.run_rate), mono: true },
		{ label: t("Cohort sales"), value: money(s.sales), mono: true },
		{ label: t("Reorder rate"), value: (s.reorder_rate || 0) + "%" },
		{ label: t("Avg time to first order"), value: s.avg_ttfo == null ? "—" : s.avg_ttfo + " " + t("days") },
		{ label: t("Freezer ROI"), value: s.freezer_roi == null ? "—" : "×" + s.freezer_roi },
	];
});

onMounted(load);
</script>

<template>
	<div class="page-header d-print-none mb-3">
		<div class="d-flex align-items-end gap-2 flex-wrap">
			<div>
				<div class="page-pretitle">{{ t("CRM") }}</div>
				<h2 class="page-title">{{ t("Acquisition report") }}</h2>
			</div>
			<div class="ms-auto d-flex align-items-end gap-2">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<button type="button" class="btn btn-sm btn-primary" :disabled="loading" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
			</div>
		</div>
	</div>

	<div v-if="loading" class="text-center py-5"><div class="spinner-border text-primary"></div></div>
	<div v-else-if="error" class="alert alert-danger">{{ error }}</div>
	<template v-else-if="report">
		<!-- Summary -->
		<div class="row g-2 mb-3">
			<div v-for="s in summaryTiles" :key="s.label" class="col-6 col-md-2">
				<div class="card card-sm">
					<div class="card-body py-2 px-3">
						<div class="text-secondary small text-truncate">{{ s.label }}</div>
						<div class="fw-bold" :class="{ 'font-monospace': s.mono }">{{ s.value }}</div>
					</div>
				</div>
			</div>
		</div>

		<div class="row g-3">
			<!-- By rep -->
			<div class="col-12 col-lg-6">
				<div class="card">
					<div class="card-header"><div class="card-title">{{ t("By rep") }}</div></div>
					<div class="table-responsive">
						<table class="table table-vcenter card-table">
							<thead>
								<tr>
									<th>{{ t("Rep") }}</th>
									<th class="text-end">{{ t("Outlets") }}</th>
									<th class="text-end">{{ t("Run-rate") }}</th>
									<th class="text-end">{{ t("Sales") }}</th>
									<th class="text-end">{{ t("Reorder") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="r in report.by_rep" :key="r.key">
									<td class="text-truncate" style="max-width: 180px">{{ r.key }}</td>
									<td class="text-end">{{ r.outlets }}</td>
									<td class="text-end font-monospace">{{ money(r.run_rate) }}</td>
									<td class="text-end font-monospace">{{ money(r.sales) }}</td>
									<td class="text-end">{{ r.reorder_rate }}%</td>
								</tr>
								<tr v-if="!report.by_rep.length"><td colspan="5" class="text-secondary text-center py-3">{{ t("No data") }}</td></tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>

			<!-- By region -->
			<div class="col-12 col-lg-6">
				<div class="card">
					<div class="card-header"><div class="card-title">{{ t("By region") }}</div></div>
					<div class="table-responsive">
						<table class="table table-vcenter card-table">
							<thead>
								<tr>
									<th>{{ t("Region / Route") }}</th>
									<th class="text-end">{{ t("Outlets") }}</th>
									<th class="text-end">{{ t("Run-rate") }}</th>
									<th class="text-end">{{ t("Sales") }}</th>
									<th class="text-end">{{ t("Reorder") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="r in report.by_region" :key="r.key">
									<td class="text-truncate" style="max-width: 180px">{{ r.key }}</td>
									<td class="text-end">{{ r.outlets }}</td>
									<td class="text-end font-monospace">{{ money(r.run_rate) }}</td>
									<td class="text-end font-monospace">{{ money(r.sales) }}</td>
									<td class="text-end">{{ r.reorder_rate }}%</td>
								</tr>
								<tr v-if="!report.by_region.length"><td colspan="5" class="text-secondary text-center py-3">{{ t("No data") }}</td></tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
