<script setup>
/* Logistician window — logistics role queue (Task C4).
 *
 * Displays tender shipments and POs grouped into 6 derived swimlanes (R1):
 *  1. Planning (planning): Logistics document requirements pending files/waiver or booking needed.
 *  2. Booking (booking): Freight Booking booked / pickup scheduled.
 *  3. In Transit (transit): Shipment in transit.
 *  4. Border Crossed (border): Border crossed or customs cleared at border.
 *  5. Delivered (delivered): Delivered to destination warehouse.
 *  6. Accepted (accepted): Goods 100% received and accepted (per_received >= 100).
 *
 * READ-ONLY PROJECTION (R3). Moving a card across lanes is driven by actual shipment updates,
 * container tracking, or goods receipts — never by dragging cards around.
 */
import { computed, onMounted, ref, watch } from "vue";
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
		data.value = await call("stabler.api.tender.logist_board", { company: activeCompany.value });
	} catch (err) {
		toast.error(err?.message || t("Could not load the logistics board."));
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
		key: "planning",
		label: t("Planning"),
		icon: "ti ti-clipboard-list",
		headerClass: "bg-red-lt text-red",
		badgeClass: "bg-red text-white",
	},
	{
		key: "booking",
		label: t("Booking"),
		icon: "ti ti-calendar-event",
		headerClass: "bg-yellow-lt text-warning",
		badgeClass: "bg-warning text-white",
	},
	{
		key: "transit",
		label: t("In Transit"),
		icon: "ti ti-truck-delivery",
		headerClass: "bg-blue-lt text-blue",
		badgeClass: "bg-blue text-white",
	},
	{
		key: "border",
		label: t("Border Crossed"),
		icon: "ti ti-flag",
		headerClass: "bg-purple-lt text-purple",
		badgeClass: "bg-purple text-white",
	},
	{
		key: "delivered",
		label: t("Delivered"),
		icon: "ti ti-building-warehouse",
		headerClass: "bg-cyan-lt text-cyan",
		badgeClass: "bg-info text-white",
	},
	{
		key: "accepted",
		label: t("Accepted"),
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
		accepted: "bg-green-lt text-green",
		delivered: "bg-cyan-lt text-cyan",
		border: "bg-purple-lt text-purple",
		transit: "bg-blue-lt text-blue",
		booking: "bg-yellow-lt text-warning",
		planning: "bg-red-lt text-red",
	}[s] || "bg-secondary-lt");

const stLabel = (s) =>
	({
		accepted: t("Accepted"),
		delivered: t("Delivered"),
		border: t("Border Crossed"),
		transit: t("In Transit"),
		booking: t("Booking"),
		planning: t("Planning"),
	}[s] || s);

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
	<TenderPage :label="t('Tender')" :title="t('Logistics')">
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
			<SkeletonRows :cols="6" :rows="4" />
		</div>

		<!-- Empty State (R5) -->
		<div v-else-if="!totalCount" class="card card-body text-center py-5">
			<EmptyState
				icon="ti-truck-delivery"
				:title="t('No active shipments or won lots in the pipeline.')"
			/>
			<p class="text-secondary small mt-2">
				{{ t("When a tender deal is awarded or a purchase order is raised, shipment requirements will appear here.") }}
			</p>
		</div>

		<!-- Swimlane Board View (Default) -->
		<div v-else-if="viewMode === 'lanes'" class="row g-3 logistics-lanes">
			<div v-for="lane in filteredLanes" :key="lane.key" class="col-12 col-md-6 col-lg">
				<div class="card h-100 lane-card shadow-sm border">
					<div class="card-header d-flex justify-content-between align-items-center py-2 px-3" :class="lane.headerClass">
						<div class="d-flex align-items-center gap-2">
							<i :class="lane.icon" class="fs-4"></i>
							<span class="fw-bold text-truncate" style="max-width: 110px;" :title="lane.label">{{ lane.label }}</span>
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
								<span v-if="item.missing_logistics_docs_count > 0" class="badge bg-red-lt text-red ms-1">
									{{ item.missing_logistics_docs_count }} {{ t("docs missing") }}
								</span>
								<span v-else-if="item.freight_booking" class="badge bg-blue-lt text-blue ms-1" :title="item.freight_booking_status">
									{{ item.freight_booking }}
								</span>
							</div>

							<!-- Vendor -->
							<div class="small text-muted text-truncate mb-2" :title="item.supplier_name">
								<i class="ti ti-building me-1"></i>{{ item.supplier_name || "—" }}
							</div>

							<!-- Metrics Panel -->
							<div class="p-2 rounded border-0 bg-light small mb-2">
								<div v-if="item.transport" class="d-flex justify-content-between mb-1">
									<span class="text-secondary">{{ t("Transport") }}:</span>
									<span class="font-monospace fw-semibold ms-2">{{ fm(item.transport) }}</span>
								</div>
								<div v-if="item.eta" class="d-flex justify-content-between mb-1">
									<span class="text-secondary">{{ t("PO ETA") }}:</span>
									<span class="ms-2 fw-semibold">{{ formatDate(item.eta) }}</span>
								</div>
								<div v-if="item.delivery" class="d-flex justify-content-between">
									<span class="text-secondary">{{ t("Deadline") }}:</span>
									<span class="ms-2" :class="item.risk === 'risk' ? 'text-red fw-bold' : ''">
										{{ formatDate(item.delivery) }}
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
							<th class="text-end">{{ t("Transport") }}</th>
							<th class="text-nowrap">{{ t("PO ETA") }}</th>
							<th class="text-nowrap">{{ t("Delivery deadline") }}</th>
							<th>{{ t("Stage") }}</th>
							<th class="text-end">{{ t("Actions") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in filteredRows" :key="r.po" style="cursor: pointer" @click="openPo(r.po)">
							<td class="fw-semibold">{{ r.po }}</td>
							<td>{{ r.supplier_name }}</td>
							<td class="text-secondary">{{ r.deal_label || "—" }}</td>
							<td class="text-end font-monospace">{{ r.transport ? fm(r.transport) : "—" }}</td>
							<td class="text-nowrap">{{ r.eta ? formatDate(r.eta) : "—" }}</td>
							<td class="text-nowrap" :class="r.risk === 'risk' ? 'text-red' : ''">
								{{ r.delivery ? formatDate(r.delivery) : "—" }}
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
