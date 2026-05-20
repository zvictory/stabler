<script setup>
import { onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const osaBadge = (pct) => {
	if (pct >= 90) return "bg-success-lt";
	if (pct >= 70) return "bg-warning-lt";
	return "bg-danger-lt";
};

const fmtPct = (v) => (v == null ? "—" : `${Number(v).toFixed(1)}%`);

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_osa_audits", {
			company: activeCompany.value,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<h3 class="card-title mb-0">{{ t("OSA Audits") }}</h3>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-checkup-list"
			:title="t('No OSA audits yet')"
			:description="t('On-Shelf-Availability audits compare expected vs actual facings during visits.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Outlet") }}</th>
						<th>{{ t("Audited At") }}</th>
						<th class="text-end">{{ t("Total SKUs") }}</th>
						<th class="text-end">{{ t("Present SKUs") }}</th>
						<th>{{ t("OSA %") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.name }}</td>
						<td>{{ r.outlet }}</td>
						<td>{{ r.audited_at || "—" }}</td>
						<td class="text-end">{{ r.total_skus ?? 0 }}</td>
						<td class="text-end">{{ r.present_skus ?? 0 }}</td>
						<td>
							<span class="badge" :class="osaBadge(r.osa_pct ?? 0)">
								{{ fmtPct(r.osa_pct) }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
