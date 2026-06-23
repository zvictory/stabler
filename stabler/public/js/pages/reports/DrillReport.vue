<script setup>
// Generic Report Center page, configured entirely by route meta.report:
//   { title, summaryApi, detailApi, drillKey, detailParam, docPrefix, exportName }
// Renders Summary → Detail → Document on the shared engine. Adding a report is
// now just a backend endpoint + a route entry — no new page code.
import { computed, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ReportFilters from "../../components/ReportFilters.vue";
import ReportTable from "../../components/ReportTable.vue";

const session = useSession();
const route = useRoute();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);

const cfg = computed(() => route.meta.report || {});
const lang = () => user.value?.language || "en";

// Excel export: the registry key is the summary function's last path segment
// (e.g. "stabler.api.reports.sales_by_customer" → "sales_by_customer").
const summaryReportKey = computed(() => (cfg.value.summaryApi || "").split(".").pop() || "");
const exportFilters = computed(() => ({
	company: activeCompany.value,
	from_date: range.value?.from_date,
	to_date: range.value?.to_date,
}));

const range = ref(null);
const loading = ref(false);
const error = ref("");
const summary = ref(null);
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

async function loadSummary(r) {
	range.value = r;
	detailOpen.value = false;
	summary.value = null;
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		summary.value = await call(cfg.value.summaryApi, {
			company: activeCompany.value,
			from_date: r.from_date,
			to_date: r.to_date,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

async function onSummaryDrill({ row }) {
	if (!cfg.value.detailApi) return;
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call(cfg.value.detailApi, {
			company: activeCompany.value,
			from_date: range.value.from_date,
			to_date: range.value.to_date,
			[cfg.value.detailParam]: row[cfg.value.drillKey],
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load detail.");
	} finally {
		detailLoading.value = false;
	}
}

function onDetailDrill({ row, col }) {
	if (col.doctype && cfg.value.docPrefix) router.push(cfg.value.docPrefix + row.name);
}

// Reset when navigating between report routes that reuse this component.
watch(() => route.fullPath, () => {
	summary.value = null;
	detail.value = null;
	detailOpen.value = false;
});
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Reports") }}</div>
		<h2 class="page-title">{{ t(cfg.title) }}</h2>
	</div>

	<ReportFilters @apply="loadSummary" />
	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="summary" class="card mb-3">
		<div class="card-body">
			<div v-if="summary.meta?.counts" class="d-flex gap-2 flex-wrap mb-2">
				<span class="badge bg-green-lt">{{ t("Class") }} A: {{ summary.meta.counts.A || 0 }}</span>
				<span class="badge bg-yellow-lt">{{ t("Class") }} B: {{ summary.meta.counts.B || 0 }}</span>
				<span class="badge bg-secondary-lt">{{ t("Class") }} C: {{ summary.meta.counts.C || 0 }}</span>
				<span class="text-secondary small ms-auto align-self-center">{{ summary.meta.note }}</span>
			</div>
			<div v-else-if="summary.meta" class="text-secondary small mb-2">
				{{ summary.meta.basis }} · {{ summary.meta.note }}
			</div>
			<ReportTable
				:columns="summary.columns"
				:rows="summary.rows"
				:totals="summary.totals"
				:currency="summary.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="loading"
				:export-name="cfg.exportName || 'report'"
				:report-key="summaryReportKey"
				:export-filters="exportFilters"
				@drill="onSummaryDrill"
			/>
		</div>
	</div>

	<div v-if="detailOpen" class="card">
		<div class="card-header">
			<div class="card-title"><i class="ti ti-receipt me-1"></i>{{ t("Details") }} · {{ detail?.meta?.title }}</div>
			<button type="button" class="btn btn-sm btn-ghost-secondary ms-auto" @click="detailOpen = false"><i class="ti ti-x"></i></button>
		</div>
		<div class="card-body">
			<ReportTable
				v-if="detail"
				:columns="detail.columns"
				:rows="detail.rows"
				:totals="detail.totals"
				:currency="detail.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="detailLoading"
				export-name="detail"
				@drill="onDetailDrill"
			/>
			<div v-else-if="detailLoading" class="text-center py-3"><span class="spinner-border spinner-border-sm"></span></div>
		</div>
	</div>
</template>
