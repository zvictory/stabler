<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
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
const route = useRoute();
const router = useRouter();

const search = ref("");
const status = ref(route.query.status ? String(route.query.status) : "");
const supplier = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const suppliers = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

const CI_STATUSES = [
	"BOOKED",
	"STUFFED",
	"GATE_IN",
	"ON_BOARD",
	"IN_TRANSIT",
	"DISCHARGED",
	"AVAILABLE",
	"ARRIVED_AT_IRAN",
	"DELIVERED_TO_UZBEKISTAN",
	"Cancelled",
];

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...CI_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);
const supplierOptions = computed(() => [
	{ value: "", label: t("All suppliers") },
	...suppliers.value.map((s) => ({ value: s.name, label: s.supplier_name || s.name })),
]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listCommercialInvoices({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			supplier: supplier.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load commercial invoices.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

async function loadSuppliers() {
	if (!activeCompany.value) return;
	try {
		suppliers.value = await call("stabler.api.purchasing.list_suppliers", {
			company: activeCompany.value,
			limit: 300,
		});
	} catch (_) {
		suppliers.value = [];
	}
}

function openDetail(name) {
	router.push("/imports/commercial-invoices/" + name);
}
function openCreate() {
	router.push("/imports/commercial-invoices/new");
}

onMounted(() => {
	loadSuppliers();
	load();
});
watch([status, supplier], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, () => {
	loadSuppliers();
	reload();
});
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('CI number or supplier… ⌘K')"
			:count="total"
			:primary-label="t('New commercial invoice')"
			primary-icon="ti-plus"
			@search="reload"
			@primary-click="openCreate"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 180px" />
					<Select v-model="supplier" size="sm" :options="supplierOptions" style="width: 200px" />
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-file-invoice"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No commercial invoices')"
			:subtitle="t('Relax the filters or create a new commercial invoice.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">#</th>
						<th>{{ t("Supplier") }}</th>
						<th class="text-nowrap">{{ t("Date") }}</th>
						<th>{{ t("Incoterm") }}</th>
						<th class="text-nowrap">{{ t("Transit ETA") }}</th>
						<th class="text-end">{{ t("Boxes") }}</th>
						<th class="text-end">{{ t("Weight (kg)") }}</th>
						<th class="text-end">{{ t("Agreed total") }}</th>
						<th class="text-end">{{ t("Docs total") }}</th>
						<th class="text-end">{{ t("Cash difference") }}</th>
						<th class="text-center">{{ t("Containers") }}</th>
						<th class="text-center">{{ t("GRN") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="13" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.ci_number || r.name }}</td>
						<td>{{ r.supplier_name || r.supplier }}</td>
						<td class="text-nowrap">{{ formatDate(r.ci_date) }}</td>
						<td>{{ r.incoterm || "—" }}</td>
						<td class="text-nowrap">{{ formatDate(r.eta_transit_port) }}</td>
						<td class="text-end font-monospace">{{ r.total_boxes || 0 }}</td>
						<td class="text-end font-monospace">{{ Number(r.total_kg || 0).toFixed(0) }}</td>
						<td class="text-end font-monospace">{{ formatMoney(r.agreed_total, r.currency, user.language) }}</td>
						<td class="text-end font-monospace">
							<span v-if="r.docs_total === null" class="text-secondary">•••</span>
							<span v-else>{{ formatMoney(r.docs_total, r.currency, user.language) }}</span>
						</td>
						<td class="text-end font-monospace">
							<span v-if="r.cash_difference === null" class="text-secondary">•••</span>
							<span v-else>{{ formatMoney(r.cash_difference, r.currency, user.language) }}</span>
						</td>
						<td class="text-center">{{ r.container_count || 0 }}</td>
						<td class="text-center">
							<i v-if="r.has_grn" class="ti ti-check text-success"></i>
							<span v-else class="text-secondary">—</span>
						</td>
						<td><StatusBadge doctype="Commercial Invoice" :status="r.status" /></td>
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
