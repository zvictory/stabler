<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import Pagination from "../../components/Pagination.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const route = useRoute();
const router = useRouter();

const search = ref("");
const status = ref(String(route.query.status || "").trim());
const variance = ref(route.query.variance ? String(route.query.variance) : "");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

const RECEIPT_STATUSES = ["Pending", "Receiving", "Complete", "Discrepancy"];
const VARIANCE_CATEGORIES = ["NORMAL", "MINOR", "MAJOR", "CRITICAL"];

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...RECEIPT_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);
const varianceOptions = computed(() => [
	{ value: "", label: t("All variance") },
	...VARIANCE_CATEGORIES.map((v) => ({ value: v, label: t(v) })),
]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listGrnChecklists({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			variance_category: variance.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load GRN checklists.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

function openDetail(name) {
	router.push("/imports/grn-checklists/" + name);
}

function pct(v) {
	return Math.max(0, Math.min(100, Number(v || 0)));
}
function progressClass(v) {
	const p = pct(v);
	if (p >= 100) return "bg-green";
	if (p > 0) return "bg-blue";
	return "bg-secondary";
}

onMounted(load);
watch([status, variance], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('GRN, CI or supplier… ⌘K')"
			:count="total"
			@search="reload"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
					<Select v-model="variance" size="sm" :options="varianceOptions" style="width: 150px" />
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-clipboard-check"
			tone="primary"
			:title="t('No GRN checklists')"
			:subtitle="t('A GRN checklist is created from a commercial invoice once cargo is ready to receive.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">{{ t("GRN") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th>{{ t("Warehouse") }}</th>
						<th style="width: 160px">{{ t("Completion") }}</th>
						<th class="text-end">{{ t("Received / expected (kg)") }}</th>
						<th class="text-center">{{ t("Variance") }}</th>
						<th class="text-center">{{ t("Trucks") }}</th>
						<th class="text-center">{{ t("Claim") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="10" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.name }}</td>
						<td class="font-monospace small">{{ r.commercial_invoice || "—" }}</td>
						<td>{{ r.supplier_name || r.supplier || "—" }}</td>
						<td class="small">{{ r.warehouse || "—" }}</td>
						<td>
							<div class="d-flex align-items-center gap-2">
								<div class="progress flex-grow-1" style="height: 6px">
									<div class="progress-bar" :class="progressClass(r.completion_percentage)" :style="{ width: pct(r.completion_percentage) + '%' }"></div>
								</div>
								<span class="small font-monospace text-secondary">{{ pct(r.completion_percentage).toFixed(0) }}%</span>
							</div>
						</td>
						<td class="text-end font-monospace">
							{{ Number(r.received_total_kg || 0).toFixed(0) }} / {{ Number(r.expected_total_kg || 0).toFixed(0) }}
						</td>
						<td class="text-center">
							<StatusBadge v-if="r.variance_category" doctype="GRN Variance Category" :status="r.variance_category" />
							<span v-else class="text-secondary">—</span>
						</td>
						<td class="text-center font-monospace">{{ r.trucks_received_count || 0 }}</td>
						<td class="text-center">
							<i v-if="r.claim_required" class="ti ti-flag text-danger" :title="t('Claim required')"></i>
							<span v-else class="text-secondary">—</span>
						</td>
						<td>
							<StatusBadge doctype="GRN Checklist" :status="r.receipt_status" />
							<StatusBadge v-if="r.docstatus === 1" class="ms-1" doctype="GRN Checklist" :docstatus="1" />
						</td>
					</tr>
				</tbody>
			</table>
		</div>
		<Pagination
			v-if="!error && total > 0"
			v-model:limit-start="limitStart"
			v-model:page-length="pageLength"
			:total="total"
			:page-count="rows.length"
		/>
	</div>
</template>
