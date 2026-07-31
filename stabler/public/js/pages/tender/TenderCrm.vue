<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useSession } from "../../stores/session.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import TenderNav from "./TenderNav.vue";

const session = useSession();
const { activeCompany, user, currency } = storeToRefs(session);
const router = useRouter();
const route = useRoute();
const toast = useToast();

const loading = ref(false);
const viewMode = ref("kanban"); // 'kanban' | 'list'
const searchQuery = ref("");
const lanes = ref([]);
const cards = ref([]);

// Selected deal drawer
const drawerOpen = ref(false);
const selectedDeal = ref(null);
const dealDetailLoading = ref(false);
const dealLots = ref([]);
const dealQuotations = ref(null);

// Drag and drop state
const dragCardName = ref("");
const dragOverLane = ref("");

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		const res = await call("stabler.api.tender.crm_board", { company: activeCompany.value });
		lanes.value = res?.lanes || [];
		cards.value = res?.cards || [];
	} catch (err) {
		toast.error(err?.message || t("Could not load Tender CRM."));
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

const filteredCards = computed(() => {
	let list = cards.value || [];
	if (searchQuery.value.trim()) {
		const q = searchQuery.value.trim().toLowerCase();
		list = list.filter(
			(c) =>
				c.name.toLowerCase().includes(q) ||
				(c.label || "").toLowerCase().includes(q) ||
				(c.organization || "").toLowerCase().includes(q) ||
				(c.lead_name || "").toLowerCase().includes(q)
		);
	}
	return list;
});

const cardsByLane = computed(() => {
	const map = {};
	for (const l of lanes.value) map[l.id] = [];
	for (const c of filteredCards.value) {
		const laneId = c.stage || "seen";
		(map[laneId] || (map[laneId] = [])).push(c);
	}
	return map;
});

const laneTotal = (laneId) =>
	(cardsByLane.value[laneId] || []).reduce((sum, c) => sum + (c.contract_value || 0), 0);

// Drag and drop handlers
function onCardDragStart(cardName, e) {
	dragCardName.value = cardName;
	e.dataTransfer.effectAllowed = "move";
}

async function onDrop(targetLaneId) {
	dragOverLane.value = "";
	const name = dragCardName.value;
	dragCardName.value = "";
	if (!name) return;

	const card = cards.value.find((c) => c.name === name);
	if (!card || card.stage === targetLaneId) return;

	const prevStage = card.stage;
	card.stage = targetLaneId; // Optimistic update

	try {
		await call("stabler.api.tender.move_deal_stage", { name, stage: targetLaneId });
		toast.success(t("Moved to {0}").replace("{0}", t(targetLaneId)));
	} catch (err) {
		card.stage = prevStage; // Rollback
		toast.error(err?.message || t("Move failed."));
	}
}

// Side Drawer Detail View
async function openDealDrawer(card) {
	selectedDeal.value = card;
	drawerOpen.value = true;
	dealDetailLoading.value = true;
	dealLots.value = [];
	dealQuotations.value = null;

	try {
		const [masterRes, sqRes] = await Promise.all([
			call("stabler.api.tender_master.get_tender_master", {
				name: card.name,
				company: activeCompany.value,
			}).catch(() => null),
			call("stabler.api.purchasing.tender_quotations", {
				deal: card.name,
			}).catch(() => null),
		]);
		dealLots.value = masterRes?.lots || [];
		dealQuotations.value = sqRes || null;
	} catch {
		// Non-critical background detail failure
	} finally {
		dealDetailLoading.value = false;
	}
}

function closeDrawer() {
	drawerOpen.value = false;
	selectedDeal.value = null;
}

function riskBadgeClass(risk) {
	switch (risk) {
		case "risk":
			return "bg-red-lt text-red";
		case "warn":
			return "bg-yellow-lt text-yellow";
		case "expired":
			return "bg-secondary-lt text-secondary";
		default:
			return "bg-green-lt text-green";
	}
}

function riskLabel(risk) {
	switch (risk) {
		case "risk":
			return t("Risk (<=48h)");
		case "warn":
			return t("Warning");
		case "expired":
			return t("Expired");
		default:
			return t("On track");
	}
}
</script>

<template>
	<div class="container-fluid py-3">
		<TenderNav />

		<!-- Header & Controls -->
		<div class="d-flex align-items-center justify-content-between mb-3 gap-2 flex-wrap">
			<div>
				<h2 class="h3 mb-0 fw-bold d-flex align-items-center gap-2">
					<i class="ti ti-address-book text-primary"></i>
					{{ t("Tender CRM") }}
				</h2>
				<span class="text-secondary small">
					{{ t("Manage and track all tender deals across pipeline stages") }}
				</span>
			</div>
			<div class="d-flex align-items-center gap-2 flex-wrap">
				<!-- Search -->
				<div class="input-icon" style="width: 220px">
					<span class="input-icon-addon"><i class="ti ti-search"></i></span>
					<input
						v-model="searchQuery"
						type="search"
						class="form-control form-control-sm"
						:placeholder="t('Search tenders…')"
					/>
				</div>

				<!-- View Mode Switcher -->
				<div class="btn-group btn-group-sm">
					<button
						type="button"
						class="btn"
						:class="viewMode === 'kanban' ? 'btn-primary' : 'btn-outline-secondary'"
						@click="viewMode = 'kanban'"
					>
						<i class="ti ti-layout-kanban me-1"></i>{{ t("Kanban") }}
					</button>
					<button
						type="button"
						class="btn"
						:class="viewMode === 'list' ? 'btn-primary' : 'btn-outline-secondary'"
						@click="viewMode = 'list'"
					>
						<i class="ti ti-list me-1"></i>{{ t("List") }}
					</button>
				</div>

				<!-- Refresh -->
				<button type="button" class="btn btn-outline-secondary btn-sm" :disabled="loading" @click="load">
					<i class="ti ti-refresh" :class="{ 'spin': loading }"></i>
				</button>
			</div>
		</div>

		<!-- Loading State -->
		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<!-- Empty State -->
		<EmptyState
			v-else-if="!cards.length"
			icon="ti-address-book"
			:title="t('No tender deals found.')"
			:subtitle="t('No active tenders found for {0}.').replace('{0}', activeCompany)"
		/>

		<template v-else>
			<!-- KANBAN VIEW -->
			<div
				v-if="viewMode === 'kanban'"
				class="d-flex gap-3 align-items-start overflow-auto pb-3"
				style="min-height: 70vh"
			>
				<div
					v-for="l in lanes"
					:key="l.id"
					class="flex-shrink-0"
					style="width: 300px"
					@dragover.prevent="dragOverLane = l.id"
					@dragleave="dragOverLane = ''"
					@drop="onDrop(l.id)"
				>
					<!-- Lane Header Card -->
					<div class="card mb-2 shadow-sm border-0" :style="{ borderTop: `4px solid ${l.color}` }">
						<div class="card-header py-2 px-3 d-flex align-items-center gap-2 bg-white rounded-2">
							<span
								class="badge font-monospace"
								:style="{ background: l.color + '22', color: l.color, border: `1px solid ${l.color}55` }"
							>
								{{ (cardsByLane[l.id] || []).length }}
							</span>
							<span class="fw-bold flex-grow-1 text-truncate">{{ t(l.label) }}</span>
							<span class="text-secondary small font-monospace fw-semibold">
								{{ formatMoney(laneTotal(l.id), currency, user.language) }}
							</span>
						</div>
					</div>

					<!-- Lane Cards Container -->
					<div
						class="vstack gap-2 px-1"
						:class="{ 'bg-primary-lt rounded-3 p-2': dragOverLane === l.id }"
						style="min-height: 80px"
					>
						<div
							v-for="c in cardsByLane[l.id]"
							:key="c.name"
							class="card card-hover shadow-sm border-0 cursor-pointer rounded-3"
							draggable="true"
							style="cursor: grab"
							@dragstart="onCardDragStart(c.name, $event)"
							@click="openDealDrawer(c)"
						>
							<div class="card-body p-3">
								<!-- Title & ID -->
								<div class="d-flex align-items-start justify-content-between gap-1 mb-1">
									<div>
										<span class="fw-bold text-body text-truncate d-block" style="max-width: 210px">
											{{ c.label || c.name }}
										</span>
										<span class="small font-monospace text-secondary">{{ c.name }}</span>
									</div>
									<span
										v-if="c.owner_initials"
										class="avatar avatar-xs rounded-circle bg-blue-lt fw-bold"
										:title="c.owner_name || c.owner"
									>
										{{ c.owner_initials }}
									</span>
								</div>

								<!-- Organization / Buyer -->
								<div v-if="c.organization || c.lead_name" class="text-secondary small text-truncate mb-2">
									<i class="ti ti-building me-1"></i>{{ c.organization || c.lead_name }}
								</div>

								<!-- Contract Value -->
								<div class="h3 mb-2 font-monospace fw-bold text-primary">
									{{ formatMoney(c.contract_value, c.currency || currency, user.language) }}
								</div>

								<!-- Badges Row: Deadline Risk & Sourcing -->
								<div class="d-flex align-items-center gap-1 flex-wrap mb-2">
									<!-- Risk Badge -->
									<span v-if="c.deadline" class="badge" :class="riskBadgeClass(c.risk)">
										<i class="ti ti-clock me-1"></i>{{ riskLabel(c.risk) }}
									</span>

									<!-- Sourcing Badge -->
									<span
										class="badge"
										:class="c.has_min_5 && c.has_2_countries ? 'bg-green-lt text-green' : c.sq_count > 0 ? 'bg-yellow-lt text-yellow' : 'bg-secondary-lt text-secondary'"
									>
										<i class="ti ti-file-dollar me-1"></i>
										{{ c.sq_count }}/5 {{ t("Quotes") }}
									</span>
								</div>

								<!-- Document Readiness Progress Bar -->
								<div>
									<div class="d-flex justify-content-between small text-secondary mb-1">
										<span>{{ t("Readiness") }}</span>
										<span class="fw-semibold">{{ c.doc_progress }}%</span>
									</div>
									<div class="progress progress-sm" style="height: 5px">
										<div
											class="progress-bar"
											:class="c.doc_progress >= 100 ? 'bg-green' : c.doc_progress >= 50 ? 'bg-blue' : 'bg-yellow'"
											:style="{ width: c.doc_progress + '%' }"
										></div>
									</div>
								</div>
							</div>
						</div>
					</div>
				</div>
			</div>

			<!-- LIST VIEW -->
			<div v-else-if="viewMode === 'list'" class="card shadow-sm border-0">
				<div class="table-responsive">
					<table class="table table-vcenter table-hover card-table m-0">
						<thead>
							<tr>
								<th>{{ t("Tender / Deal") }}</th>
								<th>{{ t("Buyer / Organization") }}</th>
								<th>{{ t("Stage") }}</th>
								<th class="text-end">{{ t("Value") }}</th>
								<th>{{ t("Sourcing") }}</th>
								<th>{{ t("Deadline Risk") }}</th>
								<th>{{ t("Readiness") }}</th>
								<th>{{ t("Owner") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr
								v-for="c in filteredCards"
								:key="c.name"
								class="cursor-pointer"
								@click="openDealDrawer(c)"
							>
								<td>
									<div class="fw-bold text-body">{{ c.label || c.name }}</div>
									<div class="small font-monospace text-secondary">{{ c.name }}</div>
								</td>
								<td class="text-secondary">{{ c.organization || c.lead_name || "—" }}</td>
								<td>
									<span class="badge bg-primary-lt">{{ t(c.stage) }}</span>
								</td>
								<td class="text-end font-monospace fw-bold">
									{{ formatMoney(c.contract_value, c.currency || currency, user.language) }}
								</td>
								<td>
									<span
										class="badge"
										:class="c.has_min_5 && c.has_2_countries ? 'bg-green-lt text-green' : c.sq_count > 0 ? 'bg-yellow-lt text-yellow' : 'bg-secondary-lt text-secondary'"
									>
										{{ c.sq_count }}/5 {{ t("Quotes") }}
									</span>
								</td>
								<td>
									<span v-if="c.deadline" class="badge" :class="riskBadgeClass(c.risk)">
										{{ riskLabel(c.risk) }}
									</span>
									<span v-else class="text-secondary">—</span>
								</td>
								<td>
									<div class="d-flex align-items-center gap-2" style="min-width: 100px">
										<div class="progress flex-grow-1" style="height: 5px">
											<div
												class="progress-bar"
												:class="c.doc_progress >= 100 ? 'bg-green' : c.doc_progress >= 50 ? 'bg-blue' : 'bg-yellow'"
												:style="{ width: c.doc_progress + '%' }"
											></div>
										</div>
										<span class="small font-monospace text-secondary">{{ c.doc_progress }}%</span>
									</div>
								</td>
								<td>
									<span v-if="c.owner_name" class="avatar avatar-xs rounded-circle bg-blue-lt fw-bold me-1" :title="c.owner_name">
										{{ c.owner_initials }}
									</span>
									<span class="small text-secondary">{{ c.owner_name || "—" }}</span>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</template>

		<!-- SIDE DRAWER DETAIL VIEW -->
		<template v-if="drawerOpen && selectedDeal">
			<div class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
			<div class="offcanvas offcanvas-end show shadow-lg" tabindex="-1" style="width: min(540px, 100vw)">
				<!-- Drawer Header -->
				<div class="offcanvas-header border-bottom bg-light">
					<div>
						<h4 class="offcanvas-title fw-bold text-body m-0">
							{{ selectedDeal.label || selectedDeal.name }}
						</h4>
						<div class="small font-monospace text-secondary d-flex align-items-center gap-2 mt-1">
							<span>{{ selectedDeal.name }}</span>
							<span>·</span>
							<span class="badge bg-primary-lt">{{ t(selectedDeal.stage) }}</span>
						</div>
					</div>
					<button type="button" class="btn-close text-reset" @click="closeDrawer"></button>
				</div>

				<!-- Drawer Body -->
				<div class="offcanvas-body p-4">
					<div v-if="dealDetailLoading" class="text-center py-5">
						<div class="spinner-border text-primary"></div>
					</div>

					<template v-else>
						<!-- Summary Grid -->
						<div class="row g-3 mb-4">
							<div class="col-6">
								<div class="card p-3 border bg-light shadow-none rounded-2">
									<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Contract Value") }}</div>
									<div class="h3 mb-0 font-monospace text-primary fw-bold">
										{{ formatMoney(selectedDeal.contract_value, selectedDeal.currency || currency, user.language) }}
									</div>
								</div>
							</div>
							<div class="col-6">
								<div class="card p-3 border bg-light shadow-none rounded-2">
									<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Buyer / Customer") }}</div>
									<div class="fw-semibold text-truncate text-body">
										{{ selectedDeal.organization || selectedDeal.lead_name || "—" }}
									</div>
								</div>
							</div>
						</div>

						<!-- Quick Actions -->
						<div class="d-flex gap-2 flex-wrap mb-4">
							<router-link
								:to="{ path: '/tender/sourcing', query: { deal: selectedDeal.name } }"
								class="btn btn-outline-primary btn-sm flex-fill"
								@click="closeDrawer"
							>
								<i class="ti ti-versions me-1"></i>{{ t("Sourcing comparison") }}
							</router-link>
							<router-link
								to="/tender/board"
								class="btn btn-outline-secondary btn-sm flex-fill"
								@click="closeDrawer"
							>
								<i class="ti ti-layout-kanban me-1"></i>{{ t("Contract board") }}
							</router-link>
						</div>

						<!-- Sourcing Quotations Summary -->
						<div class="card mb-4 border shadow-none rounded-2">
							<div class="card-header py-2 bg-light fw-bold text-body d-flex align-items-center justify-content-between">
								<span><i class="ti ti-file-dollar me-1 text-primary"></i>{{ t("Sourcing Summary") }}</span>
								<span
									class="badge"
									:class="dealQuotations?.has_min_5 && dealQuotations?.has_2_countries ? 'bg-green-lt text-green' : 'bg-yellow-lt text-yellow'"
								>
									{{ dealQuotations?.count || 0 }} / 5 {{ t("Quotes") }}
								</span>
							</div>
							<div class="card-body p-0">
								<table v-if="dealQuotations?.rows?.length" class="table table-sm card-table m-0">
									<thead>
										<tr>
											<th>{{ t("Supplier") }}</th>
											<th>{{ t("Country") }}</th>
											<th class="text-end">{{ t("Total") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="q in dealQuotations.rows" :key="q.name" :class="{ 'table-success': q.cheapest }">
											<td>
												<span class="fw-semibold">{{ q.supplier_name }}</span>
												<span v-if="q.cheapest" class="badge bg-green ms-1">{{ t("Cheapest") }}</span>
											</td>
											<td class="text-secondary small">{{ q.country || "—" }}</td>
											<td class="text-end font-monospace">{{ formatMoney(q.grand_total, q.currency, user.language) }}</td>
										</tr>
									</tbody>
								</table>
								<div v-else class="p-3 text-center text-secondary small">
									{{ t("No supplier quotations tagged to this deal yet.") }}
								</div>
							</div>
						</div>

						<!-- Lots List -->
						<div class="card border shadow-none rounded-2">
							<div class="card-header py-2 bg-light fw-bold text-body d-flex align-items-center justify-content-between">
								<span><i class="ti ti-layers-subtract me-1 text-primary"></i>{{ t("Lots") }}</span>
								<span class="badge bg-secondary-subtle text-secondary">{{ dealLots.length }}</span>
							</div>
							<div class="card-body p-0">
								<div v-if="dealLots.length" class="list-group list-group-flush">
									<div v-for="lot in dealLots" :key="lot.name" class="list-group-item p-3">
										<div class="d-flex justify-content-between align-items-start">
											<div>
												<div class="fw-bold text-body">{{ lot.label || lot.name }}</div>
												<div class="small text-secondary">{{ lot.description || "" }}</div>
											</div>
											<div class="text-end font-monospace fw-bold">
												{{ formatMoney(lot.contract_value, lot.currency || currency, user.language) }}
											</div>
										</div>
									</div>
								</div>
								<div v-else class="p-3 text-center text-secondary small">
									{{ t("No lots registered for this tender.") }}
								</div>
							</div>
						</div>
					</template>
				</div>
			</div>
		</template>
	</div>
</template>
