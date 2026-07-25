<script setup>
import { onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ReportTable from "../../components/ReportTable.vue";
import MultiSelectPicker from "../../components/MultiSelectPicker.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const onlyWithBalance = ref(1);
const customers = ref([]);
const report = ref(null);
const loading = ref(false);
const error = ref("");
const detail = ref(null);
const detailCustomer = ref("");

const lang = () => user.value?.language || "en";

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		report.value = await call("stabler.api.reports.agreement_receivables", {
			company: activeCompany.value,
			only_with_balance: onlyWithBalance.value,
			customers: customers.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load report.");
	} finally {
		loading.value = false;
	}
}

async function onDrill({ row }) {
	detailCustomer.value = row.customer;
	try {
		detail.value = await call("stabler.api.reports.customer_balance_detail", {
			company: activeCompany.value,
			customer: row.customer,
		});
	} catch (err) {
		detail.value = null;
		error.value = err?.message || t("Failed to load detail.");
	}
}

onMounted(load);
</script>

<template>
	<div class="page-header mb-3">
		<div class="page-pretitle">{{ t("Sales") }}</div>
		<h2 class="page-title">{{ t("Receivables by agreement") }}</h2>
	</div>

	<div class="d-flex align-items-center gap-2 flex-wrap mb-3">
		<label class="form-check form-switch m-0">
			<input class="form-check-input" type="checkbox" :checked="onlyWithBalance === 1" @change="onlyWithBalance = $event.target.checked ? 1 : 0; load()" />
			<span class="form-check-label">{{ t("Only with balance") }}</span>
		</label>
		<MultiSelectPicker
			v-model="customers"
			search-api="stabler.api.sales.list_customers"
			:extra-params="{ company: activeCompany }"
			id-key="name"
			:display="(r) => r.customer_name || r.name"
			:placeholder="t('Customers')"
			:title="t('Customers')"
			size="sm"
			@update:model-value="load"
		/>
		<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="loading" @click="load">
			<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
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
				:currency="report.meta?.currency || 'USD'"
				:language="lang()"
				:loading="loading"
				export-name="agreement_receivables"
				report-key="agreement_receivables"
				:export-filters="{ company: activeCompany, only_with_balance: onlyWithBalance, customers }"
				@drill="onDrill"
			/>
		</div>
	</div>
	<div v-if="detail" class="card mt-3">
		<div class="card-header"><div class="card-title"><i class="ti ti-list me-1"></i>{{ t("Ledger") }} · {{ detail.meta?.title || detailCustomer }}</div></div>
		<div class="card-body">
			<ReportTable :columns="detail.columns" :rows="detail.rows" :totals="detail.totals" :currency="detail.meta?.currency || 'USD'" :language="lang()" />
		</div>
	</div>
</template>
