<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import Pagination from "../../components/Pagination.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

const search = ref("");
const status = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

const STATUSES = ["Draft", "Submitted", "Under Review", "Approved", "Rejected"];
const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listCustomsDeclarations({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load customs declarations.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}
function openForm(name) {
	router.push("/imports/customs/" + name);
}
function openCreate() {
	router.push("/imports/customs/new");
}

onMounted(load);
watch(status, reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('GTD, CI or office… ⌘K')"
			:count="total"
			:primary-label="t('New declaration')"
			primary-icon="ti-plus"
			@search="reload"
			@primary-click="openCreate"
		>
			<template #filters>
				<Select v-model="status" size="sm" :options="statusOptions" style="width: 170px" />
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-file-certificate"
			tone="primary"
			:title="t('No customs declarations')"
			:subtitle="t('Register a customs declaration (GTD) for an import to clear it.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">{{ t("GTD number") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th class="text-nowrap">{{ t("Declared") }}</th>
						<th>{{ t("Customs office") }}</th>
						<th class="text-end">{{ t("Duty") }}</th>
						<th class="text-end">{{ t("VAT") }}</th>
						<th class="text-end">{{ t("Excise") }}</th>
						<th class="text-nowrap">{{ t("Cleared") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="9" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openForm(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.gtd_number || r.name }}</td>
						<td class="font-monospace small">{{ r.commercial_invoice || "—" }}</td>
						<td class="text-nowrap">{{ formatDate(r.declaration_date) }}</td>
						<td class="small">{{ r.customs_office || "—" }}</td>
						<td class="text-end font-monospace">{{ Number(r.duty_amount || 0).toFixed(0) }}</td>
						<td class="text-end font-monospace">{{ Number(r.vat_amount || 0).toFixed(0) }}</td>
						<td class="text-end font-monospace">{{ Number(r.excise_amount || 0).toFixed(0) }}</td>
						<td class="text-nowrap">{{ formatDate(r.cleared_date) }}</td>
						<td><StatusBadge doctype="Customs Declaration" :status="r.status" /></td>
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
