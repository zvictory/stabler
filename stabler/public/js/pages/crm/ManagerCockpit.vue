<script setup>
/* Manager Cockpit Dashboard View (/crm/cockpit).
 *
 * Displays drillable weighted forecast, commit / best-case totals,
 * stage aging, sales rep workload, and incoming email triage queue.
 */
import { onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();

const metrics = ref(null);
const loading = ref(false);

const triageRows = ref([]);
const triageLoading = ref(false);

async function loadMetrics() {
	loading.value = true;
	try {
		metrics.value = await call("stabler.api.crm_analytics.get_manager_cockpit_metrics", {
			company: activeCompany.value,
		});
	} catch (err) {
		toast.error(err?.message || t("Could not load cockpit metrics."));
	} finally {
		loading.value = false;
	}
}

async function loadTriageQueue() {
	triageLoading.value = true;
	try {
		const res = await call("stabler.api.crm_email.list_email_triage_queue", {
			company: activeCompany.value,
		});
		triageRows.value = res?.rows || [];
	} catch {
		triageRows.value = [];
	} finally {
		triageLoading.value = false;
	}
}

onMounted(() => {
	loadMetrics();
	loadTriageQueue();
});
</script>

<template>
	<div class="manager-cockpit container-xl py-3">
		<header class="d-flex justify-content-between align-items-center mb-3">
			<div>
				<h2 class="mb-0">{{ t("Manager Cockpit & Pipeline Intelligence") }}</h2>
				<span class="text-secondary small">{{ activeCompany }}</span>
			</div>
		</header>

		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>

		<div v-else-if="metrics" class="row g-3 mb-4">
			<div class="col-md-3">
				<div class="card p-3">
					<div class="text-secondary small mb-1">{{ t("Total Pipeline Value") }}</div>
					<MoneyInput v-model="metrics.total_value" size="sm" readonly />
				</div>
			</div>
			<div class="col-md-3">
				<div class="card p-3">
					<div class="text-secondary small mb-1">{{ t("Weighted Forecast") }}</div>
					<MoneyInput v-model="metrics.weighted_forecast" size="sm" readonly />
				</div>
			</div>
			<div class="col-md-3">
				<div class="card p-3">
					<div class="text-secondary small mb-1">{{ t("Commit Total") }}</div>
					<MoneyInput v-model="metrics.commit_total" size="sm" readonly />
				</div>
			</div>
			<div class="col-md-3">
				<div class="card p-3">
					<div class="text-secondary small mb-1">{{ t("Win Rate") }}</div>
					<div class="h3 mb-0 font-monospace text-success">{{ metrics.win_rate_pct }}%</div>
				</div>
			</div>
		</div>

		<!-- Triage Queue Panel -->
		<div class="card">
			<div class="card-header py-2 fw-semibold d-flex justify-content-between align-items-center">
				<span><i class="ti ti-mail-forward me-1"></i>{{ t("Incoming Email Triage Queue") }}</span>
				<span class="badge bg-secondary-lt text-secondary">{{ triageRows.length }}</span>
			</div>
			<div class="card-body p-0">
				<table v-if="triageRows.length" class="table card-table align-middle">
					<thead>
						<tr>
							<th>{{ t("Subject") }}</th>
							<th>{{ t("Sender") }}</th>
							<th>{{ t("Recipients") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in triageRows" :key="r.name">
							<td class="fw-semibold">{{ r.subject }}</td>
							<td class="font-monospace text-secondary">{{ r.sender }}</td>
							<td class="text-secondary">{{ r.recipients }}</td>
						</tr>
					</tbody>
				</table>
				<EmptyState
					v-else-if="!triageLoading"
					icon="ti-check"
					:title="t('Triage queue clear.')"
					:subtitle="t('All incoming emails are matched to active CRM deals.')"
				/>
			</div>
		</div>
	</div>
</template>
