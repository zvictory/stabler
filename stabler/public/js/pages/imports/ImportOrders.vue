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
const vendor = ref("");
const piGroup = ref("");
const loading = ref(false);
const error = ref("");
const rows = ref([]);
const kpis = ref(null);
const suppliers = ref([]);
const piGroups = ref([]);
const total = ref(0);
const limitStart = ref(0);
const pageLength = ref(25);

// Derived lifecycle badges (never stored — mirrors rules.PO_LIFECYCLE_STATUSES).
const LIFECYCLE = ["DRAFT", "CONFIRMED", "ADVANCE_PAID", "SHIPPING", "COMPLETED", "CANCELLED"];

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	...LIFECYCLE.map((s) => ({ value: s, label: t(s) })),
]);
const vendorOptions = computed(() => [
	{ value: "", label: t("All vendors") },
	...suppliers.value.map((s) => ({ value: s.name, label: s.supplier_name || s.name })),
]);
const piGroupOptions = computed(() => [
	{ value: "", label: t("All PI groups") },
	...piGroups.value.map((g) => ({ value: g.name, label: g.title || g.name })),
]);

// Money helper honouring the K3 cost mask: a null figure renders as ••• (the
// server nulls docs/diff/advance-$ for users lacking cost visibility).
function money(v, currency) {
	if (v === null || v === undefined) return "•••";
	return formatMoney(v, currency || "USD", user.value.language);
}

const kpiAgreedSub = computed(() => {
	if (!kpis.value) return "";
	return `${t("Docs")}: ${money(kpis.value.docs_total)} · ${t("Diff")}: ${money(kpis.value.diff)}`;
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await importsApi.listImportOrders({
			company: activeCompany.value,
			search: search.value || undefined,
			vendor: vendor.value || undefined,
			status: status.value || undefined,
			pi_group: piGroup.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		rows.value = res.rows || [];
		total.value = res.total_count || 0;
		kpis.value = res.kpis || null;
	} catch (err) {
		error.value = err?.message || t("Failed to load import orders.");
	} finally {
		loading.value = false;
	}
}

function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

async function loadRefData() {
	if (!activeCompany.value) return;
	try {
		suppliers.value = await call("stabler.api.purchasing.list_suppliers", {
			company: activeCompany.value,
			limit: 300,
		});
	} catch (_) {
		suppliers.value = [];
	}
	try {
		piGroups.value = await importsApi.listPiGroups(activeCompany.value);
	} catch (_) {
		piGroups.value = [];
	}
}

function openDetail(name) {
	router.push("/imports/orders/" + name);
}
function openCreate() {
	router.push("/imports/orders/new");
}

onMounted(() => {
	loadRefData();
	load();
});
watch([status, vendor, piGroup], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, () => {
	loadRefData();
	reload();
});
</script>

<template>
	<div>
		<!-- KPI strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Agreed total") }}</div>
						<div class="h2 mb-0 font-monospace">
							<span v-if="loading" class="placeholder col-5">&nbsp;</span>
							<span v-else>{{ money(kpis && kpis.agreed_total) }}</span>
						</div>
						<div v-if="!loading" class="text-secondary small mt-1">{{ kpiAgreedSub }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Physical") }}</div>
						<div class="h2 mb-0 font-monospace">
							<span v-if="loading" class="placeholder col-5">&nbsp;</span>
							<span v-else>{{ Number(kpis ? kpis.total_boxes : 0).toLocaleString() }} {{ t("boxes") }}</span>
						</div>
						<div v-if="!loading" class="text-secondary small mt-1 font-monospace">
							{{ Number(kpis ? kpis.total_kg : 0).toFixed(0) }} {{ t("kg") }}
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-4">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Invoices") }}</div>
						<div class="h2 mb-0 font-monospace">
							<span v-if="loading" class="placeholder col-3">&nbsp;</span>
							<span v-else>{{ kpis ? kpis.invoices_total : 0 }}</span>
						</div>
						<div v-if="!loading" class="text-secondary small mt-1">
							{{ kpis ? kpis.invoices_pending : 0 }} {{ t("pending") }} ·
							{{ kpis ? kpis.invoices_done : 0 }} {{ t("done") }}
						</div>
					</div>
				</div>
			</div>
		</div>

		<div class="card">
			<ListToolbar
				v-model="search"
				:placeholder="t('PI number, vendor or group… ⌘K')"
				:count="total"
				:primary-label="t('New import order')"
				primary-icon="ti-plus"
				@search="reload"
				@primary-click="openCreate"
			>
				<template #filters>
					<div class="d-flex align-items-center gap-2 flex-wrap">
						<Select v-model="vendor" size="sm" :options="vendorOptions" style="width: 190px" />
						<Select v-model="status" size="sm" :options="statusOptions" style="width: 160px" />
						<Select v-model="piGroup" size="sm" :options="piGroupOptions" style="width: 170px" />
					</div>
				</template>
			</ListToolbar>

			<div v-if="error" class="card-body">
				<div class="alert alert-danger m-0">{{ error }}</div>
			</div>
			<EmptyState
				v-else-if="!loading && !rows.length"
				icon="ti-clipboard-list"
				accentIcon="ti-plus"
				tone="primary"
				:title="t('No import orders')"
				:subtitle="t('Relax the filters or create a new import order.')"
			/>
			<div v-else class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th>{{ t("PI & Exporter") }}</th>
							<th class="text-nowrap">{{ t("Date") }}</th>
							<th class="text-center">{{ t("Products") }}</th>
							<th class="text-end">{{ t("Physical") }}</th>
							<th class="text-end">{{ t("Pricing") }}</th>
							<th style="min-width: 130px">{{ t("Invoiced") }}</th>
							<th>{{ t("Payment") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end"></th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :rows="6" :cols="9" />
					<tbody v-else>
						<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openDetail(r.name)">
							<td>
								<div class="font-monospace text-primary">{{ r.name }}</div>
								<div class="small text-secondary">{{ r.supplier_name || r.supplier }}</div>
								<span v-if="r.pi_group" class="badge bg-azure-lt mt-1">{{ r.pi_group }}</span>
							</td>
							<td class="text-nowrap">{{ formatDate(r.transaction_date) }}</td>
							<td class="text-center font-monospace">{{ r.item_count || 0 }}</td>
							<td class="text-end font-monospace small">
								<div>{{ Number(r.total_boxes || 0).toLocaleString() }} {{ t("boxes") }}</div>
								<div class="text-secondary">{{ Number(r.total_kg || 0).toFixed(0) }} {{ t("kg") }}</div>
							</td>
							<td class="text-end font-monospace small">
								<div>{{ money(r.agreed_total, r.currency) }}</div>
								<div class="text-secondary">{{ t("Docs") }}: {{ money(r.docs_total, r.currency) }}</div>
								<span
									v-if="r.cash_difference === null || Number(r.cash_difference) !== 0"
									class="badge bg-yellow-lt mt-1"
								>
									<template v-if="r.cash_difference === null">•••</template>
									<template v-else>+{{ money(r.cash_difference, r.currency) }}</template>
								</span>
							</td>
							<td>
								<div class="progress" style="height: 6px">
									<div
										class="progress-bar bg-primary"
										:style="{ width: Math.min(r.invoiced_pct || 0, 100) + '%' }"
									></div>
								</div>
								<div class="small text-secondary mt-1 font-monospace">
									{{ Number(r.invoiced_pct || 0).toFixed(0) }}% · {{ r.ci_count || 0 }} {{ t("CI") }}
								</div>
							</td>
							<td>
								<StatusBadge doctype="Import Order Payment" :status="r.payment_badge" />
								<div class="small text-secondary mt-1 font-monospace">
									{{ Number(r.payment_pct || 0).toFixed(0) }}% · {{ money(r.payment_amount, r.currency) }}
								</div>
							</td>
							<td><StatusBadge doctype="Import Order" :status="r.lifecycle" /></td>
							<td class="text-end" @click.stop>
								<button
									type="button"
									class="btn btn-ghost-secondary btn-icon btn-sm"
									:title="t('Open')"
									@click="openDetail(r.name)"
								>
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
	</div>
</template>
