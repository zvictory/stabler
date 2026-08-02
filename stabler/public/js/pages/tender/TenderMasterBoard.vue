<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import TenderPage from "./TenderPage.vue";
import TenderMasterDrawer from "../../components/TenderMasterDrawer.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const toast = useToast();

useEscapeBack(() => {
	// Root level: Esc has nowhere higher to go, so remain on page
});

const loading = ref(false);
const records = ref([]);
const totalCount = ref(0);
const orphanData = ref({ count: 0, lots: [] });

const drawerOpen = ref(false);
const editingTender = ref(null);
const selectedOrphanLot = ref(null);

const LANES = [
	{ key: "Preparation", label: t("Preparation"), tone: "ink" },
	{ key: "Active", label: t("Active"), tone: "blue" },
	{ key: "Awaiting Result", label: t("Awaiting Result"), tone: "warn" },
	{ key: "Partial Result", label: t("Partial Result"), tone: "soon" },
	{ key: "Completed", label: t("Completed"), tone: "ok" },
];

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		const [resMaster, resOrphans] = await Promise.all([
			call("stabler.api.tender_master.list_tender_masters", {
				company: activeCompany.value,
				page_length: 100,
			}),
			call("stabler.api.tender_master.orphan_tender_lots", {
				company: activeCompany.value,
			}),
		]);
		records.value = resMaster?.records || [];
		totalCount.value = resMaster?.total || 0;
		orphanData.value = resOrphans || { count: 0, lots: [] };
	} catch (err) {
		toast.error(err?.message || t("Could not load tender board"));
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

const totalLots = computed(() =>
	records.value.reduce((sum, r) => sum + (r.lot_count || 0), 0)
);
const totalValue = computed(() =>
	records.value.reduce((sum, r) => sum + (r.lot_estimated_total || r.estimated_total || 0), 0)
);

const lanesWithRecords = computed(() => {
	const map = {};
	for (const lane of LANES) {
		map[lane.key] = [];
	}
	for (const rec of records.value) {
		const laneKey = rec.stage || "Preparation";
		if (!map[laneKey]) map[laneKey] = [];
		map[laneKey].push(rec);
	}
	return LANES.map((lane) => ({
		...lane,
		records: map[lane.key] || [],
	}));
});

function openTender(name) {
	router.push({ path: "/tender/crm", query: { tender: name } });
}

function openNewDrawer(lot = null) {
	editingTender.value = null;
	selectedOrphanLot.value = lot;
	drawerOpen.value = true;
}

function openEditDrawer(tender, event) {
	if (event) event.stopPropagation();
	editingTender.value = tender;
	selectedOrphanLot.value = null;
	drawerOpen.value = true;
}

async function linkOrphanToMaster(lot, tenderName) {
	if (!lot?.name || !tenderName) return;
	try {
		await call("stabler.api.tender.save_deal_intake", {
			deal: lot.name,
			data: { custom_parent_tender: tenderName },
			company: activeCompany.value,
		});
		toast.success(t("Lot {0} linked to tender {1}", { 0: lot.name, 1: tenderName }));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not link lot"));
	}
}
</script>

<template>
	<TenderPage :label="t('Tender')" :title="t('Tender CRM')">
		<template #meta>
			<span>{{ t("Level 1: Tender Master oversight") }}</span>
			<span>{{ t("One card per published tender — click to open child lots") }}</span>
		</template>

		<template #actions>
			<button type="button" class="btn btn-primary btn-sm" @click="openNewDrawer()">
				<i class="ti ti-plus me-1"></i>{{ t("New Tender") }}
			</button>
		</template>

		<!-- Top KPIs -->
		<div class="ds-kpis" data-cols="4">
			<div class="ds-kpi" data-sev="neutral">
				<div class="ds-label">{{ t("Tender Masters") }}</div>
				<div><span class="ds-kpi-val">{{ records.length }}</span></div>
				<div class="ds-kpi-note">{{ t("active parent tenders") }}</div>
			</div>

			<div class="ds-kpi" data-sev="neutral">
				<div class="ds-label">{{ t("Total Lots") }}</div>
				<div><span class="ds-kpi-val">{{ totalLots }}</span></div>
				<div class="ds-kpi-note">{{ t("child lots under tenders") }}</div>
			</div>

			<div class="ds-kpi" data-sev="neutral">
				<div class="ds-label">{{ t("Pipeline Value") }}</div>
				<div><span class="ds-kpi-val">{{ formatMoney(totalValue, "USD", user.language) }}</span></div>
				<div class="ds-kpi-note">{{ t("derived from child lots") }}</div>
			</div>

			<div class="ds-kpi" :data-sev="orphanData.count ? 'warn' : 'ok'">
				<div class="ds-label">{{ t("Unlinked Lots") }}</div>
				<div><span class="ds-kpi-val">{{ orphanData.count }}</span></div>
				<div class="ds-kpi-note">{{ t("migration queue backlog") }}</div>
			</div>
		</div>

		<!-- Migration Queue Panel (Orphan Lots) -->
		<section v-if="orphanData.count > 0" class="ds-panel orphan-panel mb-3">
			<div class="ds-panel-head">
				<h2>
					<i class="ti ti-alert-triangle text-warning me-1"></i>
					{{ t("Unlinked Lots Migration Queue ({0})", { 0: orphanData.count }) }}
				</h2>
				<span class="ds-label ms-auto">{{ t("Lots created without a parent tender link") }}</span>
			</div>
			<div class="p-3">
				<div class="table-responsive">
					<table class="table table-sm align-middle mb-0">
						<thead>
							<tr>
								<th>{{ t("Lot Name") }}</th>
								<th>{{ t("Organization") }}</th>
								<th>{{ t("Status") }}</th>
								<th class="text-end">{{ t("Actions") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="lot in orphanData.lots" :key="lot.name">
								<td class="fw-semibold font-monospace">{{ lot.name }}</td>
								<td>{{ lot.organization || "—" }}</td>
								<td><span class="badge bg-secondary-lt">{{ lot.status || "Open" }}</span></td>
								<td class="text-end">
									<div class="btn-group btn-group-sm">
										<button type="button" class="btn btn-outline-primary btn-sm" @click="openNewDrawer(lot)">
											<i class="ti ti-plus me-1"></i>{{ t("New Tender") }}
										</button>
										<button
											v-if="records.length"
											type="button"
											class="btn btn-outline-secondary btn-sm dropdown-toggle"
											data-bs-toggle="dropdown"
										>
											{{ t("Link to Tender") }}
										</button>
										<div v-if="records.length" class="dropdown-menu dropdown-menu-end">
											<button
												v-for="master in records"
												:key="master.name"
												type="button"
												class="dropdown-item small"
												@click="linkOrphanToMaster(lot, master.name)"
											>
												{{ master.title || master.name }} ({{ master.tender_number || master.name }})
											</button>
										</div>
									</div>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</section>

		<!-- Level 1 Kanban Lanes -->
		<div class="ds-kanban mt-3">
			<div v-for="lane in lanesWithRecords" :key="lane.key" class="ds-col" :data-tone="lane.tone">
				<div class="ds-col-head">
					<h3>{{ lane.label }}</h3>
					<span class="ds-col-cnt">{{ lane.records.length }}</span>
				</div>

				<div class="ds-col-body">
					<div
						v-for="card in lane.records"
						:key="card.name"
						class="ds-card"
						role="button"
						tabindex="0"
						@click="openTender(card.name)"
						@keydown.enter="openTender(card.name)"
					>
						<div class="ds-card-head d-flex justify-content-between align-items-start">
							<div>
								<div class="ds-card-title fw-bold">{{ card.title || card.name }}</div>
								<div class="ds-mono small text-secondary">
									{{ card.tender_number ? card.tender_number + " · " : "" }}{{ card.buyer_name || "—" }}
								</div>
							</div>
							<button type="button" class="btn btn-ghost-secondary btn-icon btn-sm" @click="openEditDrawer(card, $event)">
								<i class="ti ti-edit"></i>
							</button>
						</div>

						<div class="ds-card-metrics mt-2 pt-2 border-top d-flex flex-wrap gap-1">
							<span class="ds-chip" data-tone="ink">{{ card.lot_count || 0 }} {{ t("lots") }}</span>
							<span v-if="card.risk_count" class="ds-chip" data-tone="risk">{{ card.risk_count }} {{ t("risks") }}</span>
							<span v-if="card.policy_gap_count" class="ds-chip" data-tone="warn">{{ card.policy_gap_count }} {{ t("policy gap") }}</span>
						</div>

						<div class="ds-card-foot mt-2 d-flex justify-content-between align-items-center">
							<span class="fw-bold text-primary font-monospace">
								{{ formatMoney(card.lot_estimated_total || card.estimated_total || 0, card.currency || "USD", user.language) }}
							</span>
							<span v-if="card.earliest_deadline" class="ds-mono small text-secondary">
								<i class="ti ti-calendar me-1"></i>{{ formatDate(card.earliest_deadline) }}
							</span>
						</div>
					</div>

					<div v-if="!lane.records.length" class="text-center py-4 text-secondary small">
						{{ t("No tenders in this stage") }}
					</div>
				</div>
			</div>
		</div>

		<!-- Drawer component -->
		<TenderMasterDrawer
			v-model:open="drawerOpen"
			:tender="editingTender"
			:initial-lot="selectedOrphanLot"
			@saved="load"
		/>
	</TenderPage>
</template>

<style scoped>
.ds-kanban { display: flex; gap: 16px; overflow-x: auto; padding-bottom: 16px; }
.ds-col { flex: 1; min-width: 260px; max-width: 320px; background: var(--stbl-bg-subtle, #f8fafc); border: 1px solid var(--stbl-border, #dbe1ea); border-radius: 8px; display: flex; flex-direction: column; }
.ds-col-head { padding: 12px 16px; border-bottom: 1px solid var(--stbl-border, #dbe1ea); display: flex; justify-content: space-between; align-items: center; }
.ds-col-head h3 { font-size: 14px; font-weight: 700; margin: 0; }
.ds-col-cnt { background: var(--stbl-surface, #fff); border: 1px solid var(--stbl-border, #dbe1ea); padding: 2px 8px; border-radius: 12px; font-size: 12px; font-weight: 600; }
.ds-col-body { padding: 12px; flex: 1; display: flex; flex-direction: column; gap: 12px; min-height: 200px; }
.ds-card { background: var(--stbl-surface, #fff); border: 1px solid var(--stbl-border, #dbe1ea); border-radius: 8px; padding: 12px; cursor: pointer; transition: transform 0.15s ease, box-shadow 0.15s ease; }
.ds-card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.08); }
.ds-card-title { font-size: 14px; color: var(--stbl-text, #1e293b); }
.orphan-panel { border-left: 4px solid var(--stbl-warning, #f59e0b); }
</style>
