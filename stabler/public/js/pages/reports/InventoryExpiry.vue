<script setup>
// Report Center: Batch Expiry — on-hand batches at risk (perishable / ice-cream).
// Uses a future "within N days" horizon rather than a past date range.
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ReportTable from "../../components/ReportTable.vue";
import MultiSelectPicker from "../../components/MultiSelectPicker.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const horizon = ref(60);
const items = ref([]);
const loading = ref(false);
const error = ref("");
const report = ref(null);
const lang = () => user.value?.language || "en";

const exportFilters = computed(() => ({
	company: activeCompany.value,
	horizon_days: horizon.value,
	items: items.value,
}));

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.inventory_expiry", {
			company: activeCompany.value,
			horizon_days: horizon.value,
			items: items.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Reports") }}</div>
		<h2 class="page-title">{{ t("Batch Expiry") }}</h2>
	</div>

	<div class="d-flex align-items-end gap-2 flex-wrap mb-3">
		<div>
			<label class="form-label small mb-1">{{ t("Expiring within") }}</label>
			<select v-model.number="horizon" class="form-select form-select-sm" style="max-width: 160px" @change="load">
				<option :value="30">30 {{ t("days") }}</option>
				<option :value="60">60 {{ t("days") }}</option>
				<option :value="90">90 {{ t("days") }}</option>
			</select>
		</div>
		<MultiSelectPicker
			v-model="items"
			search-api="stabler.api.inventory.list_items"
			id-key="item_code"
			:display="(r) => r.item_name || r.item_code"
			:placeholder="t('Items')"
			:title="t('Items')"
			size="sm"
			@update:model-value="load"
		/>
		<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="loading" @click="load">
			<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div v-if="report" class="card">
		<div class="card-body">
			<div v-if="report.meta?.note" class="text-secondary small mb-2">{{ report.meta.note }}</div>
			<ReportTable
				:columns="report.columns"
				:rows="report.rows"
				:totals="report.totals"
				:currency="report.meta?.currency || 'UZS'"
				:language="lang()"
				:loading="loading"
				export-name="batch_expiry"
				report-key="inventory_expiry"
				:export-filters="exportFilters"
			/>
		</div>
	</div>
</template>
