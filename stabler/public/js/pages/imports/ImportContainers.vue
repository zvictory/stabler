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
const ciFilter = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

const detail = ref(null);
const detailLoading = ref(false);
const drawerOpen = ref(false);

const CONTAINER_STATUSES = [
	"BOOKED", "STUFFED", "GATE_IN", "ON_BOARD", "IN_TRANSIT",
	"DISCHARGED", "AVAILABLE", "ARRIVED_AT_IRAN", "DELIVERED_TO_UZBEKISTAN", "Cancelled",
];
const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...CONTAINER_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listImportContainers({
			company: activeCompany.value,
			search: search.value || undefined,
			status: status.value || undefined,
			commercial_invoice: ciFilter.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
	} catch (err) {
		error.value = err?.message || t("Failed to load containers.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}
function openForm(name) {
	router.push("/imports/containers/" + name);
}
function openCreate() {
	router.push("/imports/containers/new");
}
function openLedger(name) {
	router.push("/imports/containers/" + name + "/ledger");
}

async function openDrawer(name) {
	drawerOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await importsApi.getImportContainer(name);
	} catch (err) {
		error.value = err?.message || t("Failed to load the container.");
		drawerOpen.value = false;
	} finally {
		detailLoading.value = false;
	}
}
function closeDrawer() {
	drawerOpen.value = false;
	detail.value = null;
}

const masked = (v) => v === null || v === undefined;

onMounted(load);
watch([status, ciFilter], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Container or CI number… ⌘K')"
			:count="total"
			:primary-label="t('New container')"
			primary-icon="ti-plus"
			@search="reload"
			@primary-click="openCreate"
		>
			<template #filters>
				<div class="d-flex align-items-center gap-2">
					<Select v-model="status" size="sm" :options="statusOptions" style="width: 180px" />
					<input v-model="ciFilter" type="search" class="form-control form-control-sm" :placeholder="t('Commercial Invoice')" style="width: 170px" @change="load" />
				</div>
			</template>
		</ListToolbar>

		<div v-if="error" class="card-body"><div class="alert alert-danger m-0">{{ error }}</div></div>
		<EmptyState
			v-else-if="!loading && !rows.length"
			icon="ti-box"
			tone="info"
			:title="t('No containers')"
			:subtitle="t('Relax the filters to see containers.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th class="text-nowrap">{{ t("Container") }}</th>
						<th>{{ t("Type / size") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th class="text-end">{{ t("Boxes") }}</th>
						<th class="text-end">{{ t("Weight (kg)") }}</th>
						<th class="text-end">{{ t("Cost total") }}</th>
						<th class="text-center">{{ t("70% PE") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end" style="width: 48px"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="9" />
				<tbody v-else>
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openForm(r.name)">
						<td class="font-monospace text-primary text-nowrap">{{ r.container_number || r.name }}</td>
						<td>{{ r.container_type }} · {{ r.container_size || "—" }}</td>
						<td class="font-monospace small">{{ r.commercial_invoice || "—" }}</td>
						<td class="text-end font-monospace">{{ r.total_boxes || 0 }}</td>
						<td class="text-end font-monospace">{{ Number(r.total_kg || 0).toFixed(0) }}</td>
						<td class="text-end font-monospace">
							<span v-if="masked(r.cost_lines_total)" class="text-secondary">•••</span>
							<span v-else>{{ formatMoney(r.cost_lines_total, r.currency, user.language) }}</span>
						</td>
						<td class="text-center">
							<i v-if="r.advance_70_payment_entry" class="ti ti-check text-success"></i>
							<span v-else class="text-secondary">—</span>
						</td>
						<td><StatusBadge doctype="Import Container" :status="r.status" /></td>
						<td class="text-end text-nowrap">
							<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Cost ledger')" @click.stop="openLedger(r.name)">
								<i class="ti ti-report-money"></i>
							</button>
							<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" :title="t('Quick view')" @click.stop="openDrawer(r.name)">
								<i class="ti ti-eye"></i>
							</button>
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

	<!-- Detail drawer (read-only) -->
	<div v-if="drawerOpen" class="offcanvas offcanvas-end show d-block" tabindex="-1" style="visibility: visible; width: 460px">
		<div class="offcanvas-header">
			<h2 class="offcanvas-title">{{ detail ? (detail.container_number || detail.name) : t("Container") }}</h2>
			<button type="button" class="btn-close" @click="closeDrawer"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-secondary">{{ t("Loading…") }}</div>
			<template v-else-if="detail">
				<div class="mb-3">
					<StatusBadge doctype="Import Container" :status="detail.status" />
				</div>
				<dl class="row mb-2">
					<dt class="col-5 text-secondary">{{ t("Commercial Invoice") }}</dt><dd class="col-7 font-monospace">{{ detail.commercial_invoice || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Supplier") }}</dt><dd class="col-7">{{ detail.supplier || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Type / size") }}</dt><dd class="col-7">{{ detail.container_type }} · {{ detail.container_size || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Seal number") }}</dt><dd class="col-7 font-monospace">{{ detail.seal_number || "—" }}</dd>
					<dt class="col-5 text-secondary">{{ t("Gate-in date") }}</dt><dd class="col-7">{{ formatDate(detail.gate_in_date) }}</dd>
					<dt class="col-5 text-secondary">{{ t("Total weight (kg)") }}</dt><dd class="col-7 font-monospace">{{ Number(detail.total_kg || 0).toFixed(0) }}</dd>
					<dt class="col-5 text-secondary">{{ t("Cost total") }}</dt>
					<dd class="col-7 font-monospace">
						<span v-if="masked(detail.total_amount)" class="text-secondary">•••</span>
						<span v-else>{{ formatMoney(detail.total_amount, detail.currency, user.language) }}</span>
					</dd>
					<dt class="col-5 text-secondary">{{ t("70% payment") }}</dt><dd class="col-7 font-monospace">{{ detail.advance_70_payment_entry || "—" }}</dd>
				</dl>

				<h4 class="mt-3">{{ t("Items") }}</h4>
				<table class="table table-sm">
					<thead><tr><th>{{ t("Item") }}</th><th class="text-end">{{ t("Boxes") }}</th><th class="text-end">{{ t("Kg") }}</th></tr></thead>
					<tbody>
						<tr v-for="(it, i) in detail.items" :key="i">
							<td class="small">{{ it.item_name || it.item_code }}</td>
							<td class="text-end font-monospace">{{ it.box_qty }}</td>
							<td class="text-end font-monospace">{{ Number(it.total_kg || 0).toFixed(0) }}</td>
						</tr>
						<tr v-if="!detail.items.length"><td colspan="3" class="text-secondary text-center">{{ t("No items.") }}</td></tr>
					</tbody>
				</table>

				<h4 class="mt-3">{{ t("Cost lines") }}</h4>
				<table class="table table-sm">
					<thead><tr><th>{{ t("Component") }}</th><th class="text-end">{{ t("Amount") }}</th></tr></thead>
					<tbody>
						<tr v-for="(cl, i) in detail.cost_lines" :key="i">
							<td class="small">{{ cl.cost_component }}</td>
							<td class="text-end font-monospace">
								<span v-if="masked(cl.amount)" class="text-secondary">•••</span>
								<span v-else>{{ formatMoney(cl.amount, cl.currency, user.language) }}</span>
							</td>
						</tr>
						<tr v-if="!detail.cost_lines.length"><td colspan="2" class="text-secondary text-center">{{ t("No cost lines.") }}</td></tr>
					</tbody>
				</table>
			</template>
		</div>
	</div>
	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
</template>
