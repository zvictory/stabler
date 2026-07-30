<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { call } from "../../api/client.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import {
	createLatestRequestGuard,
	groupTenderMasters,
	normalizeTenderMaster,
	tenderMasterListParams,
} from "../../composables/tenderMaster.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useSession } from "../../stores/session.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const route = useRoute();
const toast = useToast();

const loading = ref(false);
const detailLoading = ref(false);
const mode = ref("kanban");
const depth = ref("tender");
const records = ref([]);
const selected = ref(null);
const lots = ref([]);
const orphanLots = ref([]);
const orphanCount = ref(0);
const showOrphanLots = ref(false);
const listRequestGuard = createLatestRequestGuard();
const detailRequestGuard = createLatestRequestGuard();
const orphanRequestGuard = createLatestRequestGuard();

const groups = computed(() => groupTenderMasters(records.value));
const hasDocumentReadiness = computed(() =>
	records.value.some((record) => record.documentReadiness !== undefined)
);
const currency = (record) =>
	record.currency || session.companyMeta?.(activeCompany.value)?.default_currency || "";
const money = (value, record) => formatMoney(value, currency(record), user.value.language);

function isTenderMasterCompanyCurrent(requestCompany, currentCompany) {
	return requestCompany === currentCompany;
}

async function load() {
	const requestCompany = activeCompany.value;
	const request = listRequestGuard.start();
	if (!requestCompany) {
		records.value = [];
		return;
	}
	loading.value = true;
	try {
		const response = await call("stabler.api.tender_master.list_tender_masters", {
			company: requestCompany,
			...tenderMasterListParams(route.query),
		});
		if (
			!listRequestGuard.isLatest(request) ||
			!isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)
		)
			return;
		records.value = (response?.records || []).map(normalizeTenderMaster);
	} catch (error) {
		if (
			!listRequestGuard.isLatest(request) ||
			!isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)
		)
			return;
		records.value = [];
		toast.error(error?.message || t("Could not load tenders."));
	} finally {
		if (
			listRequestGuard.isLatest(request) &&
			isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)
		)
			loading.value = false;
	}
}

/**
 * The lots no tender on this board can account for.
 *
 * The lanes are derived from the lots reachable through a parent, so a parentless
 * lot is not "somewhere else" on the board — it is nowhere, and the portfolio just
 * reads low. Guessing a parent for it would be worse than showing the gap, so the
 * gap is what gets shown.
 */
async function loadOrphanLots() {
	const requestCompany = activeCompany.value;
	const request = orphanRequestGuard.start();
	orphanCount.value = 0;
	orphanLots.value = [];
	showOrphanLots.value = false;
	if (!requestCompany) return;
	try {
		const response = await call("stabler.api.tender_master.orphan_tender_lots", {
			company: requestCompany,
		});
		if (
			!orphanRequestGuard.isLatest(request) ||
			!isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)
		)
			return;
		orphanCount.value = response?.count || 0;
		orphanLots.value = response?.lots || [];
	} catch {
		// No toast: `load()` already reports whatever made this company unreadable,
		// and a second one would double every failure on the same page. An unknown
		// count leaves the strip hidden rather than claiming zero orphans.
	}
}

async function openTender(record) {
	const requestCompany = activeCompany.value;
	const request = detailRequestGuard.start();
	if (!requestCompany) return;
	detailLoading.value = true;
	selected.value = normalizeTenderMaster(record);
	lots.value = [];
	try {
		const response = await call("stabler.api.tender_master.get_tender_master", {
			name: record.name,
			company: requestCompany,
		});
		if (
			!detailRequestGuard.isLatest(request) ||
			!isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)
		)
			return;
		selected.value = normalizeTenderMaster(response?.tender || record);
		lots.value = response?.lots || [];
		depth.value = "lots";
	} catch (error) {
		if (
			!detailRequestGuard.isLatest(request) ||
			!isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)
		)
			return;
		selected.value = null;
		toast.error(error?.message || t("Could not load tender lots."));
	} finally {
		if (
			detailRequestGuard.isLatest(request) &&
			isTenderMasterCompanyCurrent(requestCompany, activeCompany.value)
		)
			detailLoading.value = false;
	}
}

function openLot(lot) {
	router.push({ path: "/tender/po-control", query: { deal: lot.name } });
}

function closeDetail() {
	detailRequestGuard.start();
	detailLoading.value = false;
	depth.value = "tender";
	selected.value = null;
	lots.value = [];
}

watch([activeCompany, () => JSON.stringify(tenderMasterListParams(route.query))], () => {
	closeDetail();
	load();
});
// Company-scoped only: the queue is the whole company's backlog, so re-fetching it
// for every drill-down filter change would be a query that cannot change its answer.
watch(activeCompany, loadOrphanLots);
onMounted(() => {
	load();
	loadOrphanLots();
});
</script>

<template>
	<div class="container-xl py-3">
		<div class="d-flex align-items-center gap-2 mb-3 flex-wrap">
			<div>
				<h2 class="mb-0">{{ t("Tender CRM") }}</h2>
				<div class="text-secondary">{{ t("Tenders and their permitted lots") }}</div>
			</div>
			<div class="ms-auto btn-group">
				<button
					type="button"
					class="btn btn-sm"
					:class="mode === 'kanban' ? 'btn-primary' : 'btn-outline-secondary'"
					@click="mode = 'kanban'"
				>
					{{ t("Kanban") }}
				</button>
				<button
					type="button"
					class="btn btn-sm"
					:class="mode === 'list' ? 'btn-primary' : 'btn-outline-secondary'"
					@click="mode = 'list'"
				>
					{{ t("List") }}
				</button>
			</div>
		</div>

		<!-- Parentless tender lots. Shown at portfolio depth only: inside one
		tender's drill-down it is somebody else's backlog. -->
		<div v-if="depth === 'tender' && orphanCount" class="mb-3">
			<div class="alert alert-warning d-flex align-items-center gap-2 flex-wrap mb-0" role="alert">
				<i class="ti ti-unlink"></i>
				<span>{{ t("{0} tender lots are not linked to a tender.", { 0: orphanCount }) }}</span>
				<button
					type="button"
					class="btn btn-sm btn-outline-secondary ms-auto"
					@click="showOrphanLots = !showOrphanLots"
				>
					{{ t("Show unlinked lots") }}
				</button>
			</div>
			<div v-if="showOrphanLots" class="card mt-2">
				<table class="table card-table">
					<thead>
						<tr>
							<th>{{ t("Lot") }}</th>
							<th>{{ t("Customer") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("Updated") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="lot in orphanLots" :key="lot.name">
							<td class="fw-semibold">{{ lot.name }}</td>
							<td>{{ lot.organization || "—" }}</td>
							<td>
								<span
									v-if="lot.status"
									class="badge"
									:class="getStatusBadgeClass('CRM Deal', lot.status)"
									>{{ t(lot.status) }}</span
								>
								<span v-else>—</span>
							</td>
							<td>{{ lot.modified ? formatDate(lot.modified) : "—" }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<div v-if="depth === 'lots'" class="card mb-3">
			<div class="card-header d-flex align-items-center gap-2">
				<button type="button" class="btn btn-sm btn-ghost-secondary" @click="closeDetail">
					<i class="ti ti-arrow-left"></i>{{ t("All tenders") }}
				</button>
				<div>
					<div class="fw-semibold">
						{{ selected?.tenderNumber }}<span v-if="selected?.title"> · {{ selected.title }}</span>
					</div>
					<div v-if="selected?.buyer" class="text-secondary small">{{ selected.buyer }}</div>
				</div>
			</div>
			<div class="card-body p-0">
				<table class="table card-table">
					<thead>
						<tr>
							<th>{{ t("Lot") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Estimated total") }}</th>
							<th>{{ t("Updated") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="detailLoading" :cols="4" :rows="3" />
					<tbody v-else>
						<tr v-for="lot in lots" :key="lot.name" role="button" @click="openLot(lot)">
							<td class="fw-semibold">{{ lot.name }}</td>
							<td>
								<span
									v-if="lot.status"
									class="badge"
									:class="getStatusBadgeClass('CRM Deal', lot.status)"
									>{{ t(lot.status) }}</span
								>
								<span v-else>—</span>
							</td>
							<td class="text-end font-monospace">{{ money(lot.custom_estimated_value, lot) }}</td>
							<td>{{ lot.modified ? formatDate(lot.modified) : "—" }}</td>
						</tr>
					</tbody>
				</table>
				<EmptyState
					v-if="!detailLoading && !lots.length"
					icon="ti-list-details"
					:title="t('No permitted lots for this tender.')"
					compact
				/>
			</div>
		</div>

		<div v-if="depth === 'tender'" class="card">
			<div class="card-body p-0">
				<table v-if="mode === 'list'" class="table card-table">
					<thead>
						<tr>
							<th>{{ t("Tender") }}</th>
							<th>{{ t("Buyer") }}</th>
							<th>{{ t("Deadline") }}</th>
							<th class="text-end">{{ t("Lots") }}</th>
							<th class="text-end">{{ t("Estimated total") }}</th>
							<th>{{ t("Stage") }}</th>
							<th>{{ t("Owner") }}</th>
							<th v-if="hasDocumentReadiness">{{ t("Documents") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loading" :cols="hasDocumentReadiness ? 8 : 7" :rows="6" />
					<tbody v-else>
						<tr
							v-for="record in records"
							:key="record.name"
							role="button"
							@click="openTender(record)"
						>
							<td>
								<div class="fw-semibold">{{ record.tenderNumber }}</div>
								<div v-if="record.title" class="text-secondary small">{{ record.title }}</div>
							</td>
							<td>{{ record.buyer || "—" }}</td>
							<td>{{ record.deadline ? formatDate(record.deadline) : "—" }}</td>
							<td class="text-end">{{ record.lotCount }}</td>
							<td class="text-end font-monospace">{{ money(record.estimatedTotal, record) }}</td>
							<td>
								<!-- The DERIVED lane, same value the Kanban groups by. Showing the
								parent's hand-typed `status` here would put "New" next to a tender
								whose every lot is won — the drift K1 removed, relocated to a column. -->
								<span class="badge" :class="getStatusBadgeClass('Tender Lane', record.stage)">{{
									t(record.stage)
								}}</span>
							</td>
							<td>{{ record.owner || "—" }}</td>
							<td v-if="hasDocumentReadiness">
								<span v-if="record.documentReadiness !== undefined" class="text-secondary">{{
									record.documentReadiness
								}}</span>
							</td>
						</tr>
					</tbody>
				</table>
				<div v-else class="p-3 overflow-auto">
					<div class="d-flex gap-3 tender-lanes">
						<section v-for="lane in groups" :key="lane.key" class="card bg-light tender-lane">
							<div class="card-header py-2 fw-semibold">
								{{ t(lane.key) }}
								<span class="badge bg-secondary-lt ms-1">{{ lane.records.length }}</span>
							</div>
							<div class="card-body p-2">
								<button
									v-for="record in lane.records"
									:key="record.name"
									type="button"
									class="card card-sm w-100 text-start mb-2 border-0 shadow-sm"
									@click="openTender(record)"
								>
									<div class="card-body p-2">
										<div class="fw-semibold">{{ record.tenderNumber }}</div>
										<div v-if="record.title" class="small text-secondary">{{ record.title }}</div>
										<div v-if="record.buyer" class="small mt-2">{{ record.buyer }}</div>
										<div class="small d-flex justify-content-between mt-2">
											<span>{{ record.deadline ? formatDate(record.deadline) : "—" }}</span
											><span class="font-monospace">{{
												money(record.estimatedTotal, record)
											}}</span>
										</div>
										<div class="small text-secondary mt-1">
											{{ t("Lots") }}: {{ record.lotCount
											}}<span v-if="record.owner"> · {{ record.owner }}</span>
										</div>
										<div v-if="record.lotCount" class="small text-secondary mt-1">
											{{ t("Open") }}: {{ record.openLotCount
											}}<span v-if="record.submittedLotCount">
												({{ t("awaiting result") }}: {{ record.submittedLotCount }})</span
											>
											· {{ t("Won") }}: {{ record.wonLotCount }} · {{ t("Lost") }}:
											{{ record.lostLotCount }}
										</div>
										<div v-if="record.earliestDeadline" class="small text-secondary mt-1">
											{{ t("Next lot deadline") }}: {{ formatDate(record.earliestDeadline) }}
										</div>
										<div v-if="record.policyGapCount" class="small text-warning mt-1">
											{{ t("Policy gap") }}: {{ record.policyGapCount }}
										</div>
										<div v-if="record.riskCount" class="small text-danger mt-1">
											{{ t("Overdue bids") }}: {{ record.riskCount }}
										</div>
										<div
											v-if="record.documentReadiness !== undefined"
											class="small text-secondary mt-1"
										>
											{{ record.documentReadiness }}
										</div>
									</div>
								</button>
							</div>
						</section>
					</div>
				</div>
				<EmptyState
					v-if="!loading && !records.length"
					icon="ti-clipboard-list"
					:title="t('No tenders found for this company.')"
				/>
			</div>
		</div>
	</div>
</template>

<style scoped>
.tender-lane {
	flex: 0 0 260px;
	min-height: 180px;
}
</style>
