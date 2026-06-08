<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

// ----- Work order list -----
const loading = ref(false);
const loadError = ref("");
const rows = ref([]);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	loadError.value = "";
	try {
		rows.value = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			limit: 100,
		});
	} catch (err) {
		loadError.value = err?.message || t("Failed to load work orders.");
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);

// ----- Per-card action state -----
const busyName = ref(""); // name of WO currently processing
const actionError = ref("");

function isBusy(name) {
	return busyName.value === name;
}

// ----- Status helpers -----
const canStart = (r) => r.docstatus === 1 && r.status === "Not Started";
const canFinish = (r) => r.docstatus === 1 && ["Not Started", "In Process"].includes(r.status);
const canPause = (r) => r.docstatus === 1 && ["Not Started", "In Process"].includes(r.status);
const canResume = (r) => r.docstatus === 1 && r.status === "Stopped";

const statusBadge = (s) => {
	switch (s) {
		case "Completed":
			return "bg-success-lt";
		case "In Process":
			return "bg-blue-lt";
		case "Not Started":
		case "Draft":
			return "bg-yellow-lt";
		case "Stopped":
		case "Cancelled":
			return "bg-secondary-lt";
		case "Closed":
			return "bg-purple-lt";
		default:
			return "bg-secondary-lt";
	}
};

function remainingQty(r) {
	return Math.max(0, (Number(r.qty) || 0) - (Number(r.produced_qty) || 0));
}

// ----- Start action (material transfer) -----
async function start(row) {
	if (!confirm(t("Transfer materials and start this Work Order?"))) return;
	busyName.value = row.name;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.make_work_order_stock_entry", {
			work_order: row.name,
			purpose: "Material Transfer for Manufacture",
		});
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Start failed.");
	} finally {
		busyName.value = "";
	}
}

// ----- Finish dialog -----
const finishTarget = ref(null); // the WO row currently finishing
const producedQty = ref(0);
const scrapQty = ref(0);

function openFinish(row) {
	finishTarget.value = row;
	producedQty.value = remainingQty(row);
	scrapQty.value = 0;
	actionError.value = "";
}
function cancelFinish() {
	finishTarget.value = null;
}

async function confirmFinish() {
	const row = finishTarget.value;
	if (!row) return;
	if (Number(producedQty.value) <= 0) {
		actionError.value = t("Produced quantity must be positive.");
		return;
	}
	busyName.value = row.name;
	actionError.value = "";
	finishTarget.value = null;
	try {
		await call("stabler.api.manufacturing.make_work_order_stock_entry", {
			work_order: row.name,
			purpose: "Manufacture",
			qty: producedQty.value,
			scrap_qty: scrapQty.value > 0 ? scrapQty.value : undefined,
		});
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Finish failed.");
	} finally {
		busyName.value = "";
	}
}

// ----- Pause / Resume -----
async function pause(row) {
	if (!confirm(t("Pause this Work Order? You can resume it later."))) return;
	busyName.value = row.name;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.stop_work_order", { name: row.name });
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Pause failed.");
	} finally {
		busyName.value = "";
	}
}

async function resume(row) {
	busyName.value = row.name;
	actionError.value = "";
	try {
		await call("stabler.api.manufacturing.resume_work_order", { name: row.name });
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Resume failed.");
	} finally {
		busyName.value = "";
	}
}

// Active WOs are those with actions available — show at the top
const sortedRows = computed(() => {
	const active = rows.value.filter((r) => canStart(r) || canFinish(r) || canPause(r) || canResume(r));
	const inactive = rows.value.filter((r) => !active.includes(r));
	return [...active, ...inactive];
});
</script>

<template>
	<div>
		<!-- Page header -->
		<div class="d-flex align-items-center justify-content-between mb-3">
			<h4 class="mb-0">{{ t("My work orders") }}</h4>
			<button type="button" class="btn btn-ghost-secondary" @click="load" :disabled="loading">
				<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
		</div>

		<div v-if="actionError" class="alert alert-danger alert-dismissible">
			{{ actionError }}
			<button type="button" class="btn-close" @click="actionError = ''"></button>
		</div>

		<div v-if="loadError" class="alert alert-danger">{{ loadError }}</div>

		<div v-if="loading" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<EmptyState
			v-else-if="!loadError && !rows.length"
			icon="ti-tool"
			tone="secondary"
			:title="t('No work orders')"
			:subtitle="t('No work orders assigned to you yet.')"
		/>

		<div v-else class="row g-3">
			<div v-for="r in sortedRows" :key="r.name" class="col-12 col-md-6 col-xl-4">
				<div class="card h-100" :class="{ 'border-primary': r.status === 'In Process' }">
					<div class="card-body">
						<div class="d-flex justify-content-between align-items-start mb-2">
							<div>
								<div class="fw-bold fs-4">{{ r.item_name || r.production_item }}</div>
								<div class="text-secondary small font-monospace">{{ r.production_item }}</div>
							</div>
							<span class="badge ms-2 flex-shrink-0" :class="statusBadge(r.status)">
								{{ r.status }}
							</span>
						</div>

						<!-- Progress -->
						<div class="row g-2 mb-3">
							<div class="col-4 text-center">
								<div class="text-secondary small">{{ t("Planned") }}</div>
								<div class="fw-semibold">{{ r.qty }}</div>
							</div>
							<div class="col-4 text-center">
								<div class="text-secondary small">{{ t("Produced") }}</div>
								<div class="fw-semibold text-blue">{{ r.produced_qty || 0 }}</div>
							</div>
							<div class="col-4 text-center">
								<div class="text-secondary small">{{ t("Remaining") }}</div>
								<div class="fw-semibold" :class="remainingQty(r) > 0 ? 'text-yellow' : 'text-success'">
									{{ remainingQty(r) }}
								</div>
							</div>
						</div>

						<!-- Progress bar -->
						<div class="progress mb-3" style="height: 6px">
							<div
								class="progress-bar bg-primary"
								:style="{
									width: r.qty > 0 ? `${Math.min(100, ((r.produced_qty || 0) / r.qty) * 100)}%` : '0%',
								}"
							></div>
						</div>

						<div class="text-secondary small mb-3">
							<i class="ti ti-calendar me-1"></i>{{ formatDate(r.planned_start_date) }}
						</div>

						<!-- Action buttons — large for touch -->
						<div v-if="r.docstatus === 1" class="d-flex flex-wrap gap-2">
							<button
								v-if="canStart(r)"
								type="button"
								class="btn btn-success btn-lg flex-grow-1"
								:disabled="isBusy(r.name)"
								@click="start(r)"
							>
								<span v-if="isBusy(r.name)" class="spinner-border spinner-border-sm me-1"></span>
								<i v-else class="ti ti-player-play me-1"></i>
								{{ t("Start") }}
							</button>

							<button
								v-if="canFinish(r)"
								type="button"
								class="btn btn-primary btn-lg flex-grow-1"
								:disabled="isBusy(r.name)"
								@click="openFinish(r)"
							>
								<i class="ti ti-check me-1"></i>{{ t("Finish") }}
							</button>

							<button
								v-if="canPause(r)"
								type="button"
								class="btn btn-outline-warning btn-lg"
								:disabled="isBusy(r.name)"
								@click="pause(r)"
							>
								<span v-if="isBusy(r.name)" class="spinner-border spinner-border-sm"></span>
								<i v-else class="ti ti-player-pause"></i>
							</button>

							<button
								v-if="canResume(r)"
								type="button"
								class="btn btn-outline-primary btn-lg flex-grow-1"
								:disabled="isBusy(r.name)"
								@click="resume(r)"
							>
								<span v-if="isBusy(r.name)" class="spinner-border spinner-border-sm me-1"></span>
								<i v-else class="ti ti-player-play me-1"></i>
								{{ t("Resume") }}
							</button>
						</div>

						<!-- Draft: inform operator they can't act until manager submits -->
						<div v-else class="text-secondary small fst-italic">
							{{ t("Awaiting release by manager") }}
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Finish modal -->
		<template v-if="finishTarget">
			<div class="modal-backdrop fade show" @click="cancelFinish"></div>
			<div class="modal fade show d-block" tabindex="-1" style="background: transparent">
				<div class="modal-dialog modal-dialog-centered">
					<div class="modal-content">
						<div class="modal-header">
							<h5 class="modal-title">{{ t("Finish") }} — {{ finishTarget.item_name || finishTarget.production_item }}</h5>
							<button type="button" class="btn-close" @click="cancelFinish"></button>
						</div>
						<div class="modal-body">
							<div v-if="actionError" class="alert alert-danger mb-3">{{ actionError }}</div>

							<div class="mb-3">
								<label class="form-label fw-semibold">{{ t("Produced quantity") }}</label>
								<input
									v-model.number="producedQty"
									type="number"
									min="0.001"
									step="0.001"
									inputmode="decimal"
									class="form-control form-control-lg"
									autofocus
								/>
								<div class="form-hint">
									{{ t("Remaining") }}: {{ remainingQty(finishTarget) }} {{ t("planned") }}: {{ finishTarget.qty }}
								</div>
							</div>

							<div class="mb-1">
								<label class="form-label">{{ t("Scrap / rejects") }} <span class="text-secondary small">({{ t("optional") }})</span></label>
								<input
									v-model.number="scrapQty"
									type="number"
									min="0"
									step="0.001"
									inputmode="decimal"
									class="form-control form-control-lg"
									placeholder="0"
								/>
							</div>
						</div>
						<div class="modal-footer">
							<button type="button" class="btn btn-link link-secondary" @click="cancelFinish">
								{{ t("Cancel") }}
							</button>
							<button
								type="button"
								class="btn btn-primary btn-lg"
								:disabled="!producedQty || producedQty <= 0"
								@click="confirmFinish"
							>
								<i class="ti ti-check me-1"></i>{{ t("Confirm finish") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.card {
	transition: border-color 0.15s ease;
}

.btn-lg {
	min-height: 48px; /* touch target */
}

.text-yellow {
	color: var(--tblr-yellow, #f7b731);
}
</style>
