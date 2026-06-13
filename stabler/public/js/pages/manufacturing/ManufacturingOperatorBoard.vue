<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { formatDate } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const { confirm } = useConfirm();

// ----- Auth State -----
const isLoggedIn = computed(() => session.user && session.user.id && session.user.id !== "Guest");
const scanUid = ref("");
const showPinForm = ref(false);
const employeeId = ref("");
const pinCode = ref("");
const scannerInput = ref(null);
const inputFocused = ref(false);

// ----- Work order list -----
const loading = ref(false);
const loadError = ref("");
const rows = ref([]);

// ----- Per-card action state -----
const busyName = ref(""); // name of WO currently processing
const actionError = ref("");

async function load() {
	if (!activeCompany.value || !isLoggedIn.value) return;
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

// ----- 90s Inactivity / Idle Timeout -----
let idleTimer = null;
const IDLE_TIMEOUT_MS = 90000; // 90 seconds

function resetIdleTimer() {
	if (idleTimer) clearTimeout(idleTimer);
	if (!isLoggedIn.value) return;
	idleTimer = setTimeout(async () => {
		await logout();
	}, IDLE_TIMEOUT_MS);
}

const activityEvents = ["mousemove", "mousedown", "keypress", "touchstart", "scroll", "click"];

function setupActivityListeners() {
	if (isLoggedIn.value) {
		activityEvents.forEach((event) => {
			window.addEventListener(event, resetIdleTimer);
		});
		resetIdleTimer();
	}
}

function removeActivityListeners() {
	activityEvents.forEach((event) => {
		window.removeEventListener(event, resetIdleTimer);
	});
	if (idleTimer) clearTimeout(idleTimer);
}

// ----- Polling Queue -----
let pollTimer = null;

function startPolling() {
	if (isLoggedIn.value) {
		pollTimer = setInterval(load, 10000); // Poll every 10 seconds
	}
}

function stopPolling() {
	if (pollTimer) clearInterval(pollTimer);
}

// ----- Login Handlers -----
async function handleScanSubmit() {
	const uid = scanUid.value.trim();
	if (!uid) return;
	scanUid.value = "";
	actionError.value = "";
	loading.value = true;
	try {
		await call("stabler.api.manufacturing.badge_login", { uid });
		window.location.reload();
	} catch (err) {
		actionError.value = err?.message || t("Card not recognized");
	} finally {
		loading.value = false;
	}
}

function togglePinForm(show) {
	showPinForm.value = show;
	actionError.value = "";
	pinCode.value = "";
	employeeId.value = "";
	if (!show) {
		setTimeout(focusScanner, 200);
	}
}

function pressKey(val) {
	if (val === "clear") {
		pinCode.value = "";
	} else if (val === "backspace") {
		pinCode.value = pinCode.value.slice(0, -1);
	} else {
		if (pinCode.value.length < 8) {
			pinCode.value += val.toString();
		}
	}
}

const pinObscured = computed(() => {
	return "•".repeat(pinCode.value.length) || "";
});

async function handlePinSubmit() {
	const emp = employeeId.value.trim();
	const pin = pinCode.value;
	if (!emp || !pin) return;
	actionError.value = "";
	loading.value = true;
	try {
		await call("stabler.api.manufacturing.pin_login", { employee: emp, pin });
		window.location.reload();
	} catch (err) {
		actionError.value = err?.message || t("Card not recognized");
		pinCode.value = ""; // Clear entered PIN on failure
	} finally {
		loading.value = false;
	}
}

async function logout() {
	removeActivityListeners();
	stopPolling();
	try {
		await call("stabler.api.manufacturing.badge_logout");
	} catch (err) {
		console.error("Logout failed:", err);
	}
	window.location.reload();
}

// ----- Scanner Focus Helpers -----
function focusScanner() {
	if (!isLoggedIn.value && !showPinForm.value && scannerInput.value) {
		scannerInput.value.focus();
		inputFocused.value = true;
	}
}

function handleInputBlur() {
	inputFocused.value = false;
	setTimeout(() => {
		focusScanner();
	}, 150);
}

// ----- Lifecycle Hooks -----
onMounted(() => {
	if (isLoggedIn.value) {
		load();
		setupActivityListeners();
		startPolling();
	} else {
		focusScanner();
		window.addEventListener("focus", focusScanner);
		document.addEventListener("click", focusScanner);
	}
});

onUnmounted(() => {
	removeActivityListeners();
	stopPolling();
	window.removeEventListener("focus", focusScanner);
	document.removeEventListener("click", focusScanner);
});

watch(activeCompany, () => {
	if (isLoggedIn.value) {
		load();
	}
});

// ----- Status helpers -----
function isBusy(name) {
	return busyName.value === name;
}

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

// ----- Action triggers -----
async function start(row) {
	const ok = await confirm({
		title: t("Start Work Order"),
		body: t("Start Work Order and transfer raw materials?"),
		confirmLabel: t("Start"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	busyName.value = row.name;
	actionError.value = "";
	resetIdleTimer();
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
	resetIdleTimer();
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
	resetIdleTimer();
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

async function pause(row) {
	const ok = await confirm({
		title: t("Pause Work Order"),
		body: t("Pause this Work Order?"),
		confirmLabel: t("Pause"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	busyName.value = row.name;
	actionError.value = "";
	resetIdleTimer();
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
	resetIdleTimer();
	try {
		await call("stabler.api.manufacturing.resume_work_order", { name: row.name });
		await load();
	} catch (err) {
		actionError.value = err?.message || t("Resume failed.");
	} finally {
		busyName.value = "";
	}
}

// Active WOs first
const sortedRows = computed(() => {
	const active = rows.value.filter((r) => canStart(r) || canFinish(r) || canPause(r) || canResume(r));
	const inactive = rows.value.filter((r) => !active.includes(r));
	return [...active, ...inactive];
});
</script>

<template>
	<!-- Logged Out (Auth Screen) -->
	<div v-if="!isLoggedIn" class="kiosk-auth-container d-flex align-items-center justify-content-center">
		<div class="kiosk-auth-card card p-5 shadow-lg border-0" style="max-width: 460px; width: 100%; border-radius: 16px;">
			<div v-if="!showPinForm">
				<div class="scanner-circle mb-4">
					<div class="scanner-pulse"></div>
					<i class="ti ti-rfid text-primary" style="font-size: 3.2rem;"></i>
				</div>
				<h2 class="mb-2 fw-bold">{{ t("Operator Kiosk") }}</h2>
				<p class="text-secondary mb-4">{{ t("Place your RFID badge on the reader to log in") }}</p>

				<div v-if="actionError" class="alert alert-danger mb-4 py-2 px-3 small border-0 shadow-sm">{{ actionError }}</div>

				<!-- Hidden input for RFID reader wedge input -->
				<form @submit.prevent="handleScanSubmit">
					<input
						ref="scannerInput"
						v-model="scanUid"
						type="text"
						class="scanner-hidden-input"
						@blur="handleInputBlur"
						@focus="inputFocused = true"
					/>
				</form>

				<div class="mt-4">
					<button type="button" class="btn btn-outline-primary w-100 py-2.5 fw-semibold" @click="togglePinForm(true)">
						<i class="ti ti-dialpad me-2"></i>{{ t("Lost Badge? Login with PIN") }}
					</button>
				</div>
				
				<div class="mt-4 text-center">
					<span v-if="inputFocused" class="badge bg-success-lt px-3 py-1.5 fs-6 select-none">
						<i class="ti ti-circle-filled me-1"></i>{{ t("Scanner Ready") }}
					</span>
					<span v-else class="badge bg-warning-lt px-3 py-1.5 fs-6 cursor-pointer select-none" @click="focusScanner">
						<i class="ti ti-alert-triangle-filled me-1"></i>{{ t("Click to Activate Scanner") }}
					</span>
				</div>
			</div>

			<!-- PIN Fallback Screen -->
			<div v-else>
				<h2 class="mb-2 fw-bold">{{ t("Login with PIN") }}</h2>
				<p class="text-secondary small mb-4">{{ t("Enter your Employee ID and secure PIN") }}</p>

				<div v-if="actionError" class="alert alert-danger mb-4 py-2 px-3 small border-0 shadow-sm">{{ actionError }}</div>

				<div class="mb-3 text-start">
					<label class="form-label small fw-semibold text-secondary">{{ t("Employee ID") }}</label>
					<input
						v-model="employeeId"
						type="text"
						class="form-control form-control-lg text-center font-monospace"
						placeholder="EMP-0001"
						autofocus
					/>
				</div>

				<div class="mb-3 text-start">
					<label class="form-label small fw-semibold text-secondary">{{ t("PIN") }}</label>
					<div class="form-control form-control-lg text-center font-monospace fs-1 py-2 bg-light select-none border-dashed" style="letter-spacing: 0.6rem; height: 58px;">
						{{ pinObscured || "••••" }}
					</div>
				</div>

				<!-- GLOVE-FRIENDLY KEYPAD -->
				<div class="keypad-grid mb-4">
					<button v-for="num in [1, 2, 3, 4, 5, 6, 7, 8, 9]" :key="num" type="button" class="keypad-btn" @click="pressKey(num)">
						{{ num }}
					</button>
					<button type="button" class="keypad-btn keypad-btn-action text-danger" @click="pressKey('clear')">
						{{ t("C") }}
					</button>
					<button type="button" class="keypad-btn" @click="pressKey(0)">
						0
					</button>
					<button type="button" class="keypad-btn keypad-btn-action text-secondary" @click="pressKey('backspace')">
						<i class="ti ti-backspace fs-3"></i>
					</button>
				</div>

				<div class="d-flex gap-3">
					<button type="button" class="btn btn-ghost-secondary w-50 py-2.5 fw-semibold" @click="togglePinForm(false)">
						{{ t("Cancel") }}
					</button>
					<button type="button" class="btn btn-primary w-50 py-2.5 fw-semibold" :disabled="!employeeId || !pinCode" @click="handlePinSubmit">
						{{ t("Submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Logged In (Operator Board Queue) -->
	<div v-else>
		<!-- Kiosk Top Banner -->
		<div class="card mb-4 bg-dark text-white border-0 shadow-sm overflow-hidden position-relative">
			<div class="card-body p-4 d-flex flex-wrap justify-content-between align-items-center position-relative" style="z-index: 2;">
				<div>
					<div class="small text-white-50 text-uppercase tracking-wider fw-bold mb-1">{{ t("Line Operator Kiosk") }}</div>
					<h3 class="mb-0 fw-bold d-flex align-items-center">
						<i class="ti ti-user-circle me-2 text-primary fs-2"></i>
						{{ session.user.name || session.user.id }}
					</h3>
				</div>
				<div class="d-flex align-items-center gap-3 mt-3 mt-md-0">
					<div class="text-end d-none d-md-block">
						<div class="small text-white-50">{{ t("Active Company") }}</div>
						<div class="fw-semibold">{{ activeCompany }}</div>
					</div>
					<button type="button" class="btn btn-danger btn-lg px-4 d-flex align-items-center gap-2" @click="logout">
						<i class="ti ti-logout"></i>
						<span>{{ t("Log Out") }}</span>
					</button>
				</div>
			</div>
			<!-- Decorative Background Glow -->
			<div class="position-absolute end-0 top-0 bottom-0 bg-primary opacity-10 blur-30" style="width: 300px; transform: skewX(-20deg); filter: blur(40px);"></div>
		</div>

		<!-- Page Header -->
		<div class="d-flex align-items-center justify-content-between mb-3">
			<h4 class="mb-0 fw-bold">{{ t("My Work Orders Queue") }}</h4>
			<button type="button" class="btn btn-ghost-secondary" @click="load" :disabled="loading">
				<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
		</div>

		<div v-if="actionError" class="alert alert-danger alert-dismissible shadow-sm border-0">
			<div class="d-flex align-items-center">
				<i class="ti ti-alert-circle me-2 fs-3"></i>
				<div>{{ actionError }}</div>
			</div>
			<button type="button" class="btn-close" @click="actionError = ''"></button>
		</div>

		<div v-if="loadError" class="alert alert-danger border-0 shadow-sm">{{ loadError }}</div>

		<div v-if="loading && !rows.length" class="text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<EmptyState
			v-else-if="!loadError && !rows.length"
			icon="ti-tool"
			tone="secondary"
			:title="t('Queue is empty')"
			:subtitle="t('There are currently no work orders assigned to you.')"
		/>

		<!-- Work Order Cards Grid -->
		<div v-else class="row g-3">
			<div v-for="r in sortedRows" :key="r.name" class="col-12 col-md-6 col-xl-4">
				<div class="card h-100 shadow-sm border-0 transition-all" :class="{ 'border-primary border-2': r.status === 'In Process' }">
					<div class="card-body p-4 d-flex flex-column h-100">
						<div class="d-flex justify-content-between align-items-start mb-3">
							<div>
								<div class="fw-bold fs-3 text-dark mb-1">{{ r.item_name || r.production_item }}</div>
								<div class="text-secondary small font-monospace d-flex align-items-center gap-1">
									<span>{{ r.production_item }}</span>
									<span class="text-muted">•</span>
									<span class="text-secondary">{{ r.name }}</span>
								</div>
							</div>
							<span class="badge px-2.5 py-1.5 fs-6 rounded-pill" :class="statusBadge(r.status)">
								{{ r.status }}
							</span>
						</div>

						<!-- Progress Stats -->
						<div class="row g-2 mb-3 bg-light rounded p-3 text-center">
							<div class="col-4 border-end">
								<div class="text-secondary small mb-1">{{ t("Planned") }}</div>
								<div class="fw-bold fs-4 text-dark">{{ r.qty }}</div>
							</div>
							<div class="col-4 border-end">
								<div class="text-secondary small mb-1">{{ t("Produced") }}</div>
								<div class="fw-bold fs-4 text-blue">{{ r.produced_qty || 0 }}</div>
							</div>
							<div class="col-4">
								<div class="text-secondary small mb-1">{{ t("Remaining") }}</div>
								<div class="fw-bold fs-4" :class="remainingQty(r) > 0 ? 'text-warning' : 'text-success'">
									{{ remainingQty(r) }}
								</div>
							</div>
						</div>

						<!-- Progress Bar -->
						<div class="progress mb-3 bg-secondary-lt" style="height: 8px; border-radius: 4px;">
							<div
								class="progress-bar bg-primary rounded"
								:style="{
									width: r.qty > 0 ? `${Math.min(100, ((r.produced_qty || 0) / r.qty) * 100)}%` : '0%',
								}"
							></div>
						</div>

						<!-- Warehouse & Timestamps info -->
						<div class="text-secondary small mb-4 flex-grow-1">
							<div class="d-flex align-items-center gap-2 mb-1">
								<i class="ti ti-building-warehouse text-muted"></i>
								<span>{{ t("WIP Whse") }}: <strong class="text-dark">{{ r.wip_warehouse || '—' }}</strong></span>
							</div>
							<div class="d-flex align-items-center gap-2 mb-1">
								<i class="ti ti-building-warehouse-filled text-muted"></i>
								<span>{{ t("FG Whse") }}: <strong class="text-dark">{{ r.fg_warehouse || '—' }}</strong></span>
							</div>
							<div class="d-flex align-items-center gap-2 mt-2 pt-2 border-top border-light">
								<i class="ti ti-calendar text-muted"></i>
								<span>{{ t("Planned Start") }}: <strong class="text-dark">{{ formatDate(r.planned_start_date) }}</strong></span>
							</div>
						</div>

						<!-- Large touch-friendly control buttons (sized for gloves) -->
						<div v-if="r.docstatus === 1" class="d-flex flex-wrap gap-2 mt-auto pt-2">
							<button
								v-if="canStart(r)"
								type="button"
								class="btn btn-success btn-lg flex-grow-1 py-3 fw-bold shadow-sm d-flex align-items-center justify-content-center gap-2"
								:disabled="isBusy(r.name)"
								@click="start(r)"
							>
								<span v-if="isBusy(r.name)" class="spinner-border spinner-border-sm"></span>
								<template v-else>
									<i class="ti ti-player-play-filled"></i>
									<span>{{ t("Start Work") }}</span>
								</template>
							</button>

							<button
								v-if="canFinish(r)"
								type="button"
								class="btn btn-primary btn-lg flex-grow-1 py-3 fw-bold shadow-sm d-flex align-items-center justify-content-center gap-2"
								:disabled="isBusy(r.name)"
								@click="openFinish(r)"
							>
								<i class="ti ti-square-rounded-check-filled"></i>
								<span>{{ t("Finish Order") }}</span>
							</button>

							<button
								v-if="canPause(r)"
								type="button"
								class="btn btn-outline-warning btn-lg px-4 py-3 fw-bold shadow-sm d-flex align-items-center justify-content-center"
								:disabled="isBusy(r.name)"
								@click="pause(r)"
								:title="t('Pause Work')"
							>
								<span v-if="isBusy(r.name)" class="spinner-border spinner-border-sm"></span>
								<i v-else class="ti ti-player-pause-filled fs-3"></i>
							</button>

							<button
								v-if="canResume(r)"
								type="button"
								class="btn btn-outline-primary btn-lg flex-grow-1 py-3 fw-bold shadow-sm d-flex align-items-center justify-content-center gap-2"
								:disabled="isBusy(r.name)"
								@click="resume(r)"
							>
								<span v-if="isBusy(r.name)" class="spinner-border spinner-border-sm"></span>
								<template v-else>
									<i class="ti ti-player-play-filled"></i>
									<span>{{ t("Resume Work") }}</span>
								</template>
							</button>
						</div>

						<div v-else class="text-secondary small fst-italic text-center py-2 bg-light rounded mt-auto">
							<i class="ti ti-lock me-1"></i>{{ t("Awaiting release by manager") }}
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Finish Modal -->
		<template v-if="finishTarget">
			<div class="modal-backdrop fade show" @click="cancelFinish"></div>
			<div class="modal fade show d-block" tabindex="-1" style="background: transparent">
				<div class="modal-dialog modal-dialog-centered">
					<div class="modal-content shadow-lg border-0" style="border-radius: 12px;">
						<div class="modal-header bg-light">
							<h5 class="modal-title fw-bold">
								{{ t("Finish Production Run") }}
							</h5>
							<button type="button" class="btn-close" @click="cancelFinish"></button>
						</div>
						<div class="modal-body p-4">
							<div v-if="actionError" class="alert alert-danger mb-3 border-0 shadow-sm">{{ actionError }}</div>
							
							<div class="mb-4 text-center py-3 bg-light rounded">
								<div class="fw-bold fs-3 text-dark">{{ finishTarget.item_name || finishTarget.production_item }}</div>
								<span class="small text-muted font-monospace">{{ finishTarget.name }}</span>
							</div>

							<div class="mb-4">
								<label class="form-label fw-bold text-dark fs-4 mb-2">{{ t("Good Produced Qty") }}</label>
								<input
									v-model.number="producedQty"
									type="number"
									min="0.001"
									step="0.001"
									inputmode="decimal"
									class="form-control form-control-lg text-center fs-2 fw-bold font-monospace"
									style="height: 60px;"
									autofocus
								/>
								<div class="form-hint mt-2 text-secondary d-flex justify-content-between">
									<span>{{ t("Target Remaining") }}: <strong>{{ remainingQty(finishTarget) }}</strong></span>
									<span>{{ t("Planned Total") }}: <strong>{{ finishTarget.qty }}</strong></span>
								</div>
							</div>

							<div class="mb-2">
								<label class="form-label fw-bold text-dark fs-4 mb-2">
									{{ t("Scrap / Rejects Qty") }}
									<span class="text-secondary small fw-normal">({{ t("optional") }})</span>
								</label>
								<input
									v-model.number="scrapQty"
									type="number"
									min="0"
									step="0.001"
									inputmode="decimal"
									class="form-control form-control-lg text-center fs-3 font-monospace"
									style="height: 50px;"
									placeholder="0"
								/>
							</div>
						</div>
						<div class="modal-footer bg-light p-3">
							<button type="button" class="btn btn-link link-secondary fw-semibold" @click="cancelFinish">
								{{ t("Cancel") }}
							</button>
							<button
								type="button"
								class="btn btn-primary btn-lg px-4 fw-bold shadow-sm"
								:disabled="!producedQty || producedQty <= 0"
								@click="confirmFinish"
							>
								<i class="ti ti-check me-1"></i>{{ t("Confirm Submit") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.kiosk-auth-container {
	min-height: 80vh;
	background: radial-gradient(circle at center, #1e293b 0%, #0f172a 100%);
	border-radius: 12px;
	padding: 24px;
}
.kiosk-auth-card {
	background: rgba(255, 255, 255, 0.05);
	backdrop-filter: blur(12px);
	border: 1px solid rgba(255, 255, 255, 0.15) !important;
	color: #f8fafc;
}
.kiosk-auth-card h2 {
	color: #ffffff;
}
.kiosk-auth-card p {
	color: #cbd5e1 !important;
}
.kiosk-auth-card label {
	color: #94a3b8 !important;
}
.kiosk-auth-card input {
	background: rgba(15, 23, 42, 0.6);
	border: 1px solid rgba(255, 255, 255, 0.2);
	color: #ffffff;
}
.kiosk-auth-card input::placeholder {
	color: #64748b;
}
.kiosk-auth-card input:focus {
	background: rgba(15, 23, 42, 0.8);
	border-color: var(--tblr-primary);
	color: #ffffff;
	box-shadow: 0 0 0 0.25rem rgba(32, 107, 196, 0.25);
}

.scanner-circle {
	width: 130px;
	height: 130px;
	border-radius: 50%;
	background: rgba(32, 107, 196, 0.15);
	border: 2px solid var(--tblr-primary);
	display: flex;
	align-items: center;
	justify-content: center;
	position: relative;
	margin: 0 auto;
}
.scanner-pulse {
	position: absolute;
	width: 100%;
	height: 100%;
	border-radius: 50%;
	border: 2px solid var(--tblr-primary);
	animation: pulse-wave 2s infinite linear;
	opacity: 0;
}
@keyframes pulse-wave {
	0% {
		transform: scale(1);
		opacity: 0.6;
	}
	100% {
		transform: scale(1.6);
		opacity: 0;
	}
}

.scanner-hidden-input {
	position: absolute;
	opacity: 0;
	pointer-events: none;
	width: 1px;
	height: 1px;
	left: -9999px;
}

/* Keypad Layout */
.keypad-grid {
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: 12px;
	max-width: 320px;
	margin: 0 auto;
}
.keypad-btn {
	height: 64px;
	font-size: 1.5rem;
	font-weight: 600;
	border-radius: 10px;
	border: 1px solid rgba(255, 255, 255, 0.15);
	background: rgba(255, 255, 255, 0.08);
	color: #ffffff;
	display: flex;
	align-items: center;
	justify-content: center;
	cursor: pointer;
	user-select: none;
	transition: all 0.15s ease;
}
.keypad-btn:hover {
	background: rgba(255, 255, 255, 0.15);
}
.keypad-btn:active {
	background: rgba(255, 255, 255, 0.25);
	transform: scale(0.95);
}
.keypad-btn-action {
	background: rgba(15, 23, 42, 0.4);
}

.card {
	transition: all 0.2s ease-in-out;
}
.card:hover {
	transform: translateY(-2px);
}
.btn-lg {
	border-radius: 8px;
}
.select-none {
	user-select: none;
}
</style>
