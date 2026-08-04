<script setup>
/* Declarant window — customs role queue (Task C3).
 *
 * Displays tender POs and deals grouped into 5 derived swimlanes (R1):
 *  1. Document missing (missing_docs): Customs document requirements pending files/waiver.
 *  2. Ready for GTD (ready): Customs docs complete, awaiting declaration.
 *  3. Declared (declared): Customs Declaration created (Draft / Submitted).
 *  4. Under Inspection (inspection): Declaration under review or red/yellow channel.
 *  5. Released (released): Declaration approved/released or goods fully received.
 *
 * READ-ONLY PROJECTION (R3). Moving a card across lanes is driven by uploading actual
 * documents or creating a GTD declaration, never by dragging cards around.
 */
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useAutoRefresh } from "../../composables/useAutoRefresh.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { activeTenderFilters, filterTenderRows, tenderRouteFilters } from "../../composables/tenderBoardFilters.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderPage from "./TenderPage.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
useEscapeBack(null, "/tender/board");

const loading = ref(false);
const viewMode = ref("lanes"); // "lanes" (default) or "table"
const data = ref({ rows: [], lanes: {}, currency: "" });

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.tender.declarant_queue", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the customs queue."));
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, (newVal) => {
	if (newVal) load();
});
useAutoRefresh(load);

const ccy = computed(() => data.value?.currency || "");
const rows = computed(() => data.value?.rows || []);
const rawLanes = computed(() => data.value?.lanes || {});
const filters = computed(() => tenderRouteFilters(route.query));
const filterSummary = computed(() => activeTenderFilters(filters.value).map(([key, value]) => `${key}: ${value}`));

const filteredRows = computed(() => filterTenderRows(rows.value, filters.value));

const LANE_CONFIGS = [
	{
		key: "missing_docs",
		label: t("Document Missing"),
		icon: "ti ti-file-alert",
		headerClass: "bg-red-lt text-red",
		badgeClass: "bg-red text-white",
	},
	{
		key: "ready",
		label: t("Ready for GTD"),
		icon: "ti ti-file-check",
		headerClass: "bg-blue-lt text-blue",
		badgeClass: "bg-blue text-white",
	},
	{
		key: "declared",
		label: t("Declared"),
		icon: "ti ti-file-invoice",
		headerClass: "bg-yellow-lt text-warning",
		badgeClass: "bg-warning text-white",
	},
	{
		key: "inspection",
		label: t("Under Inspection"),
		icon: "ti ti-search",
		headerClass: "bg-purple-lt text-purple",
		badgeClass: "bg-purple text-white",
	},
	{
		key: "released",
		label: t("Released"),
		icon: "ti ti-circle-check",
		headerClass: "bg-green-lt text-green",
		badgeClass: "bg-success text-white",
	},
];

const filteredLanes = computed(() => {
	const result = [];
	for (const cfg of LANE_CONFIGS) {
		const laneData = rawLanes.value[cfg.key] || { count: 0, items: [] };
		const items = filterTenderRows(laneData.items || [], filters.value);
		result.push({
			...cfg,
			count: items.length,
			items,
		});
	}
	return result;
});

const totalCount = computed(() => filteredRows.value.length);

const fm = (v) => formatMoney(v, ccy.value, user.value?.language || "en");
const stBadge = (s) =>
	({
		released: "bg-green-lt text-green",
		inspection: "bg-purple-lt text-purple",
		declared: "bg-yellow-lt text-warning",
		ready: "bg-blue-lt text-blue",
		missing_docs: "bg-red-lt text-red",
	}[s] || "bg-secondary-lt");

const stLabel = (s) =>
	({
		released: t("Released"),
		inspection: t("Under Inspection"),
		declared: t("Declared"),
		ready: t("Ready for GTD"),
		missing_docs: t("Document Missing"),
	}[s] || s);

function etaText(r) {
	if (r.days_left == null) return "—";
	if (r.days_left < 0) return `${-r.days_left} ${t("days late")}`;
	if (r.days_left === 0) return t("today");
	return `${r.days_left} ${t("days left")}`;
}

function openPo(name) {
	if (!name) return;
	router.push({ name: "purchasing-order", params: { name }, query: { ...route.query } });
}

function openDocCenter(deal) {
	if (!deal) return;
	router.push({ name: "tender-documents", query: { deal, ...route.query } });
}

function clearFilters() {
	router.replace({ query: {} });
}
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('Customs queue')">
		<template v-if="filterSummary.length" #meta>
			<span>{{ filterSummary.join(" · ") }}</span>
		</template>
		<template #actions>
			<span class="btn-group btn-group-sm" role="group">
				<button
					type="button"
					class="btn"
					:class="viewMode === 'lanes' ? 'btn-primary' : 'btn-outline-secondary'"
					@click="viewMode = 'lanes'"
				>
					<i class="ti ti-layout-kanban me-1"></i>{{ t("Lanes") }}
				</button>
				<button
					type="button"
					class="btn"
					:class="viewMode === 'table' ? 'btn-primary' : 'btn-outline-secondary'"
					@click="viewMode = 'table'"
				>
					<i class="ti ti-list me-1"></i>{{ t("Table") }}
				</button>
			</span>
			<button v-if="filterSummary.length" type="button" class="btn btn-sm btn-secondary" @click="clearFilters">
				{{ t("Clear filters") }}
			</button>
		</template>

		<!-- Skeleton Loading -->
		<div v-if="loading" class="card card-body">
			<SkeletonRows :cols="5" :rows="4" />
		</div>

		<!-- Empty State (R5) -->
		<div v-else-if="!totalCount" class="card card-body text-center py-5">
			<EmptyState
				icon="ti-file-invoice"
				:title="t('No active customs declarations or won lots in the pipeline.')"
			/>
			<p class="text-secondary small mt-2">
				{{ t("When a tender deal is awarded or a purchase order is raised, customs requirements will appear here.") }}
			</p>
		</div>

		<!-- Swimlane Board View (Default) -->
		<div v-else-if="viewMode === 'lanes'" class="row g-3 declarant-lanes">
			<div v-for="lane in filteredLanes" :key="lane.key" class="col-12 col-md-6 col-lg">
				<div class="card h-100 lane-card shadow-sm border">
					<div class="card-header d-flex justify-content-between align-items-center py-2 px-3" :class="lane.headerClass">
						<div class="d-flex align-items-center gap-2">
							<i :class="lane.icon" class="fs-4"></i>
							<span class="fw-bold">{{ lane.label }}</span>
						</div>
						<span class="badge rounded-pill" :class="lane.badgeClass">{{ lane.count }}</span>
					</div>

					<div class="card-body p-2 d-flex flex-column gap-2 lane-body" style="min-height: 220px; background-color: var(--tblr-bg-surface-tertiary, #f8fafc);">
						<div v-if="!lane.items.length" class="text-muted text-center py-4 small border border-dashed rounded bg-white my-auto">
							{{ t("No items in this stage") }}
						</div>

						<div
							v-for="item in lane.items"
							:key="item.po"
							class="card border shadow-xs item-card p-2 bg-white"
						>
							<!-- Header: PO and Lot/Deal -->
							<div class="d-flex justify-content-between align-items-start mb-1">
								<div>
									<span class="fw-bold text-primary text-decoration-none cursor-pointer" @click="openPo(item.po)">
										{{ item.po }}
									</span>
									<div v-if="item.deal_label" class="text-secondary small text-truncate" style="max-width: 140px;" :title="item.deal_label">
										{{ item.deal_label }}
									</div>
								</div>
								<span v-if="item.missing_customs_docs_count > 0" class="badge bg-red-lt text-red ms-1">
									{{ item.missing_customs_docs_count }} {{ t("docs missing") }}
								</span>
								<span v-else-if="item.customs_declaration" class="badge bg-blue-lt text-blue ms-1" :title="item.customs_declaration_status">
									{{ item.customs_declaration }}
								</span>
							</div>

							<!-- Vendor -->
							<div class="small text-muted text-truncate mb-2" :title="item.supplier_name">
								<i class="ti ti-building me-1"></i>{{ item.supplier_name || "—" }}
							</div>

							<!-- Metrics Panel -->
							<div class="p-2 rounded border-0 bg-light small mb-2">
								<div v-if="item.tnved" class="d-flex justify-content-between mb-1">
									<span class="text-secondary">{{ t("HS code") }}:</span>
									<span class="font-monospace fw-semibold ms-2">{{ item.tnved }}</span>
								</div>
								<div v-if="item.customs_total" class="d-flex justify-content-between mb-1">
									<span class="text-secondary">{{ t("Customs charges") }}:</span>
									<span class="font-monospace fw-semibold ms-2">{{ fm(item.customs_total) }}</span>
								</div>
								<div v-if="item.eta" class="d-flex justify-content-between">
									<span class="text-secondary">{{ t("ETA") }}:</span>
									<span
										class="ms-2"
										:class="item.days_left != null && item.days_left < 0 ? 'text-red fw-bold' : (item.days_left != null && item.days_left <= 7 ? 'text-warning fw-semibold' : '')"
									>
										{{ formatDate(item.eta) }} ({{ etaText(item) }})
									</span>
								</div>
							</div>

							<!-- Actions (R3: Open views, no dragging) -->
							<div class="d-flex gap-1 justify-content-end mt-auto pt-1 border-top">
								<button
									v-if="item.deal"
									type="button"
									class="btn btn-xs btn-outline-secondary"
									:title="t('Doc Center')"
									@click="openDocCenter(item.deal)"
								>
									<i class="ti ti-files me-1"></i>{{ t("Doc Center") }}
								</button>
								<button
									type="button"
									class="btn btn-xs btn-outline-primary"
									:title="t('Open PO')"
									@click="openPo(item.po)"
								>
									<i class="ti ti-file-text me-1"></i>{{ t("PO") }}
								</button>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Table View (Alternative) -->
		<div v-else class="card">
			<div class="card-body p-0">
				<table class="table card-table">
					<thead>
						<tr>
							<th>{{ t("PO") }}</th>
							<th>{{ t("Vendor") }}</th>
							<th>{{ t("Tender") }}</th>
							<th>{{ t("HS code (ТН ВЭД)") }}</th>
							<th class="text-end">{{ t("Customs") }}</th>
							<th class="text-nowrap">{{ t("PO ETA") }}</th>
							<th class="text-nowrap">{{ t("Days left") }}</th>
							<th>{{ t("Stage") }}</th>
							<th class="text-end">{{ t("Actions") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in filteredRows" :key="r.po" style="cursor: pointer" @click="openPo(r.po)">
							<td class="fw-semibold">{{ r.po }}</td>
							<td>{{ r.supplier_name }}</td>
							<td class="text-secondary">{{ r.deal_label || "—" }}</td>
							<td class="font-monospace">{{ r.tnved || "—" }}</td>
							<td class="text-end font-monospace">{{ r.customs_total ? fm(r.customs_total) : "—" }}</td>
							<td class="text-nowrap">{{ r.eta ? formatDate(r.eta) : "—" }}</td>
							<td
								class="text-nowrap"
								:class="r.days_left != null && r.days_left < 0 ? 'text-red' : (r.days_left != null && r.days_left <= 7 ? 'text-warning' : '')"
							>
								{{ etaText(r) }}
							</td>
							<td>
								<span class="badge" :class="stBadge(r.stage)">{{ stLabel(r.stage) }}</span>
							</td>
							<td class="text-end" @click.stop>
								<button
									v-if="r.deal"
									type="button"
									class="btn btn-xs btn-ghost-secondary me-1"
									@click="openDocCenter(r.deal)"
								>
									{{ t("Doc Center") }}
								</button>
								<button type="button" class="btn btn-xs btn-ghost-primary" @click="openPo(r.po)">
									{{ t("PO") }}
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</TenderPage>
</template>
