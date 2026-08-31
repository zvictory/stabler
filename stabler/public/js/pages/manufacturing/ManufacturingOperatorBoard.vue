<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { halfAssigned } from "../../composables/workOrderRoles.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { formatDate } from "../../composables/date.js";
import { sanitizeNumeric } from "../../composables/numpad.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import NumPad from "../../components/NumPad.vue";

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

// ERPNext validation errors (e.g. stock shortages) arrive as HTML with /desk
// links. Strip tags + entities so the kiosk shows plain, Desk-free text instead
// of raw "<strong>… <a href=/desk/…>" markup.
function humanizeError(err) {
	let msg = err && err.message ? String(err.message) : "";
	if (!msg) return "";
	if (msg.indexOf("<") !== -1) {
		// DOMParser, not a detached <div>. An element from document.createElement
		// belongs to a document WITH a browsing context, so `innerHTML = msg`
		// fires <img src=x onerror=...> the moment it parses — attached or not.
		// DOMParser's document is inert: nothing loads, nothing runs. The path is
		// not theoretical, because these messages are assembled from data:
		// `_assert_sweep_is_acknowledged` interpolates item_name straight off the
		// Item master, so whoever can name an Item can put markup into a string
		// every operator's kiosk renders.
		msg = new DOMParser().parseFromString(msg, "text/html").body.textContent || "";
	}
	return msg.replace(/\s+/g, " ").trim();
}

async function load() {
	if (!activeCompany.value || !isLoggedIn.value) return;
	loading.value = true;
	loadError.value = "";
	try {
		// `required_items` is dropped rather than merged. The endpoint may still
		// send it -- a manager badging in at the same terminal gets the full list --
		// but nothing on this screen may hold the recipe, because a ref that exists
		// is a ref the next template edit can render.
		const data = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			limit: 100,
		});

		rows.value = data.map(({ required_items: _hidden, ...r }) => r);
	} catch (err) {
		loadError.value = humanizeError(err) || t("Failed to load work orders.");
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
		actionError.value = humanizeError(err) || t("Card not recognized");
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
		actionError.value = humanizeError(err) || t("Card not recognized");
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

const canStart = (r) => r.docstatus === 1 && ["Not Started", "Stock Partially Reserved", "Submitted"].includes(r.status);
const canFinish = (r) => r.docstatus === 1 && ["In Process", "Stock Partially Reserved", "Material Transferred", "Submitted"].includes(r.status);
const canPause = (r) => r.docstatus === 1 && ["Not Started", "In Process", "Stock Partially Reserved", "Material Transferred", "Submitted"].includes(r.status);
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

// ----- Start dialog -----
const startTarget = ref(null); // the WO row currently starting
const transferFromWh = ref("");
const transferToWh = ref("");
const warehouses = ref([]);

async function start(row) {
	startTarget.value = row;
	// Straight off the Work Order, and no longer off `wo_transfer_preview`. That
	// endpoint answers with ERPNext's own transfer rows -- measured on anjan
	// 2026-08-31 as Manufacturing User `qwerty03@mail.com`: 15 lines with
	// quantities, R194 27840 Dona among them. It was the one route by which the
	// recipe reached this screen, and the dialog no longer needs it: the server
	// builds the same rows when `items` is absent from the post.
	transferFromWh.value = row.source_warehouse || "";
	transferToWh.value = row.wip_warehouse || "";

	actionError.value = "";
	resetIdleTimer();

	if (!warehouses.value.length) {
		try {
			warehouses.value = await call("stabler.api.inventory.list_warehouses", { company: activeCompany.value });
		} catch (err) {
			console.error("Failed to load warehouses", err);
		}
	}
}

function cancelStart() {
	startTarget.value = null;
}

async function confirmStart() {
	const row = startTarget.value;
	if (!row) return;

	busyName.value = row.name;
	actionError.value = "";
	resetIdleTimer();

	try {
		// No `items`. The server then builds the transfer with ERPNext's own
		// `make_stock_entry` (manufacturing.py, `items: str | None = None`), which
		// is the same list this dialog used to send back after showing it -- so the
		// document posted is unchanged and the operator never saw its contents.
		await call("stabler.api.manufacturing.make_work_order_stock_entry", {
			work_order: row.name,
			purpose: "Material Transfer for Manufacture",
			from_warehouse: transferFromWh.value,
			to_warehouse: transferToWh.value,
		});
		startTarget.value = null;
		await load();
	} catch (err) {
		actionError.value = humanizeError(err) || t("Start failed.");
	} finally {
		busyName.value = "";
	}
}

// ----- Finish dialog -----
const finishTarget = ref(null); // the WO row currently finishing
// Strings, not numbers: the numpad hands over "1." mid-decimal and no number
// can hold that. Converted once, at the two call sites that send them.
const producedQty = ref("");
const scrapQty = ref("");

// Which of the two fields the numpad is driving. The operator taps a field to
// aim it; production is what the dialog opens on, so that is the default.
const numTarget = ref("produced");
const numBuffer = computed({
	get: () => (numTarget.value === "scrap" ? scrapQty.value : producedQty.value),
	set: (v) => {
		if (numTarget.value === "scrap") scrapQty.value = v;
		else producedQty.value = v;
	},
});

// `:value` binds the model and Vue patches the DOM only when that value changes.
// A character the sanitiser rejects leaves the model exactly as it was, so there
// is nothing to patch and the box keeps showing what was typed — "12a" on the
// wall while the order will be finished with 12. Writing the clean value back
// onto the element forces the two into agreement on the same keystroke.
function onQtyInput(event, target) {
	const clean = sanitizeNumeric(event.target.value);
	if (target === "scrap") scrapQty.value = clean;
	else producedQty.value = clean;
	event.target.value = clean;
}

const batchNo = ref("");
const batchMfg = ref("");
const batchExpiry = ref("");

const draftBusy = ref(false);

// ----- Rejects: one number, two destinations, never both ------------------
//
// "Киоск 2.0: очередь, крупные кнопки, брак с причиной" — defect WITH A REASON.
// The number has been askable since 2026-06-08 and was used on 0 of 3757
// Manufacture entries; the missing thing was the reason.
//
// Both destinations exist and the server refuses the combination in both
// directions (`_assert_no_scrap_record`, `_assert_rejects_were_not_already_
// reported`), because `scrap_qty` draws the lost units' raw material into the
// good output's cost while a scrap record moves that same material into the
// scrap warehouse — each number individually correct, their sum wrong, and
// nothing throwing. So the modal does not offer two boxes. It offers ONE box and
// a switch that says where the number goes, and switching empties it.
const rejectMode = ref("reasoned");
// How many scrap records this order already carries: from `wo_scrap_options` on
// open, plus whatever is filed in this dialog. Non-zero retires the bare count
// entirely — that is the server's refusal, met before the pallet is counted.
const scrapRecords = ref(0);
const scrapWarehouse = ref(null);
const scrapItems = ref([]);
const scrapReasons = ref([]);
const scrapItem = ref("");
const scrapReason = ref("");
const scrapBusy = ref(false);
const scrapNotice = ref("");

/**
 * Where this Finish's reject number goes, and what the Finish call may carry.
 *
 * `unfiled` is the one that is not about the server. In reasoned mode the number
 * in the box belongs to a scrap record that has not been filed yet, and sending
 * the Finish would drop it silently — the loss counted on the floor and recorded
 * nowhere. It holds the Confirm button instead of quietly discarding it.
 */
function rejectPath(mode, typedQty, recordedCount) {
	const typed = Number(typedQty) > 0 ? Number(typedQty) : 0;
	if (recordedCount > 0) {
		return { path: "record", scrap_qty: undefined, locked: true, unfiled: typed };
	}
	if (mode === "reasoned") {
		return { path: "record", scrap_qty: undefined, locked: false, unfiled: typed };
	}
	return { path: "count", scrap_qty: typed > 0 ? typed : undefined, locked: false, unfiled: 0 };
}

const rejectDecision = computed(() =>
	rejectPath(rejectMode.value, scrapQty.value, scrapRecords.value)
);
const unfiledScrap = computed(() => rejectDecision.value.unfiled > 0);
const scrapReady = computed(
	() => !!scrapWarehouse.value && scrapItems.value.some((i) => Number(i.available) > 0)
);

// Switching destinations empties the box. The two are mutually exclusive on the
// server per Work Order, so a number carried across the switch is a number aimed
// at the wrong one — and it would look identical to the operator either way.
function setRejectMode(mode) {
	if (rejectMode.value === mode) return;
	rejectMode.value = mode;
	// The NUMBER is what must not cross: it was typed for one destination and
	// looks identical aimed at the other. A picked item or reason is inert on the
	// count side and worth keeping if they switch back.
	scrapQty.value = "";
	if (numTarget.value === "scrap") numTarget.value = "produced";
}

async function recordScrap() {
	const row = finishTarget.value;
	if (!row) return;
	scrapBusy.value = true;
	actionError.value = "";
	resetIdleTimer();
	try {
		const out = await call("stabler.api.manufacturing.log_line_scrap", {
			company: activeCompany.value,
			work_order: row.name,
			item_code: scrapItem.value,
			qty: Number(scrapQty.value),
			reason: scrapReason.value,
		});
		// The draft's name, because the endpoint returns it for exactly this: a
		// stock document now sits in accounting's queue and the operator is the
		// only person who knows why it is there.
		scrapNotice.value = out?.stock_entry
			? t("Recorded. Stock transfer {0} is waiting for accounting.", [out.stock_entry])
			: t("Recorded.");
		scrapRecords.value += 1;
		scrapQty.value = "";
		scrapItem.value = "";
		scrapReason.value = "";
		numTarget.value = "produced";
		await loadScrapOptions(row.name);
	} catch (err) {
		actionError.value = humanizeError(err) || t("Could not record the scrap.");
	} finally {
		scrapBusy.value = false;
	}
}

async function loadScrapOptions(workOrder) {
	try {
		const opts = await call("stabler.api.manufacturing.wo_scrap_options", {
			work_order: workOrder,
		});
		scrapWarehouse.value = opts?.scrap_warehouse || null;
		scrapItems.value = opts?.items || [];
		scrapRecords.value = Number(opts?.scrap_records) || 0;
	} catch (err) {
		// Non-fatal, like the sweep preview: a failed read costs the reasoned path,
		// not the Finish. `scrapWarehouse` stays null, so the modal says scrap
		// cannot be recorded here rather than offering a picker that would throw.
		console.error("Failed to read the scrap options", err);
	}
}

async function loadScrapReasons() {
	if (scrapReasons.value.length || !activeCompany.value) return;
	try {
		// The Loss half of `Stabler Stop Reason`, seeded and translated into five
		// languages. The four chips in the design package illustrate the SHAPE of
		// this picker; the taxonomy is the catalogue's and is not yet reviewed, so
		// nothing here may carry a second opinion about it.
		scrapReasons.value = await call("stabler.api.manufacturing.list_stop_reasons", {
			company: activeCompany.value,
			kind: "Loss",
		});
	} catch (err) {
		console.error("Failed to read the loss reasons", err);
	}
}

// Finishing can still drag the other role's unconsumed material onto this
// operator's document, and `_assert_sweep_is_acknowledged` still refuses it
// server-side. What is gone is the early warning that named the lines: it came
// from `wo_consumption_preview`, which answers with item codes and quantities,
// and the operator can no longer act on the answer anyway -- with the write-off
// off this screen there is no colleague to go and find, only a refusal to accept
// or to walk away from. So the checkbox now appears when the server says so.
const sweepAck = ref(false);
const sweepBlocked = ref(false);
const sweepPending = computed(() => sweepBlocked.value);

async function openFinish(row) {
	finishTarget.value = row;
	producedQty.value = String(remainingQty(row) ?? "");
	scrapQty.value = "";
	numTarget.value = "produced";
	batchNo.value = "";
	batchMfg.value = "";
	batchExpiry.value = "";
	actionError.value = "";
	// Cleared per order, not per session: a kiosk is one screen for a whole
	// shift, and a tick left over from the last order would wave the next one
	// straight through the guard.
	sweepAck.value = false;
	sweepBlocked.value = false;
	// Cleared per order for the reason sweepAck is: a kiosk is one screen for a
	// whole shift, and a record count left over from the last order would hide
	// this one's count box, or offer it on an order the server has already
	// closed to it.
	rejectMode.value = "reasoned";
	scrapRecords.value = 0;
	scrapWarehouse.value = null;
	scrapItems.value = [];
	scrapItem.value = "";
	scrapReason.value = "";
	scrapNotice.value = "";
	resetIdleTimer();
	loadScrapReasons();
	// Awaited, unlike the two previews below: whether this order already carries
	// scrap records decides which box the operator is shown, and showing the
	// wrong one for a frame is how a number gets typed into the path the server
	// refuses.
	await loadScrapOptions(row.name);
	try {
		const s = await call("stabler.api.manufacturing.suggest_wo_batch", { work_order: row.name });
		batchNo.value = s?.batch_no || "";
		batchMfg.value = s?.mfg_date || "";
		batchExpiry.value = s?.expiry_date || "";
	} catch (err) {
		console.error("Failed to suggest batch", err);
	}
	// After the suggestion, not before: a parked count is somebody's actual walk of
	// the pallet and outranks anything the server guessed. `?? ` and not `||` —
	// zero produced with forty rejects is a real shift, and the one nobody should
	// be made to count twice.
	const d = row.finish_draft;
	if (d) {
		producedQty.value = String(d.produced_qty ?? producedQty.value);
		scrapQty.value = d.scrap_qty != null ? String(d.scrap_qty) : "";
		if (d.batch_no) batchNo.value = d.batch_no;
		if (d.mfg_date) batchMfg.value = d.mfg_date;
		if (d.expiry_date) batchExpiry.value = d.expiry_date;
	}
}

async function saveDraft() {
	const row = finishTarget.value;
	if (!row) return;
	draftBusy.value = true;
	actionError.value = "";
	resetIdleTimer();
	try {
		await call("stabler.api.manufacturing.save_finish_draft", {
			work_order: row.name,
			produced_qty: Number(producedQty.value) || 0,
			scrap_qty: Number(scrapQty.value) || 0,
			batch_no: batchNo.value || undefined,
			mfg_date: batchNo.value && batchMfg.value ? batchMfg.value : undefined,
			expiry_date: batchNo.value && batchExpiry.value ? batchExpiry.value : undefined,
		});
		finishTarget.value = null;
		await load();
	} catch (err) {
		actionError.value = humanizeError(err) || t("Could not save the draft.");
	} finally {
		draftBusy.value = false;
	}
}

async function discardDraft() {
	const row = finishTarget.value;
	if (!row) return;
	draftBusy.value = true;
	actionError.value = "";
	resetIdleTimer();
	try {
		await call("stabler.api.manufacturing.discard_finish_draft", { work_order: row.name });
		finishTarget.value = null;
		await load();
	} catch (err) {
		actionError.value = humanizeError(err) || t("Could not discard the draft.");
	} finally {
		draftBusy.value = false;
	}
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
			qty: Number(producedQty.value),
			scrap_qty: rejectDecision.value.scrap_qty,
			batch_no: batchNo.value || undefined,
			mfg_date: batchNo.value && batchMfg.value ? batchMfg.value : undefined,
			expiry_date: batchNo.value && batchExpiry.value ? batchExpiry.value : undefined,
			acknowledge_sweep: sweepAck.value,
		});
		await load();
	} catch (err) {
		// Matched on the exception class, never on the message: that string ships
		// in five languages and matching its text would strand four of them.
		if (err?.response?.exc_type === "SweepNotAcknowledged") {
			sweepBlocked.value = true;
			finishTarget.value = row;
		}
		actionError.value = humanizeError(err) || t("Finish failed.");
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
		actionError.value = humanizeError(err) || t("Pause failed.");
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
		actionError.value = humanizeError(err) || t("Resume failed.");
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
							<div class="d-flex align-items-center justify-content-between mb-1">
								<div class="d-flex align-items-center gap-2">
									<i class="ti ti-building-warehouse text-muted"></i>
									<span>{{ t("WIP Whse") }}: <strong class="text-dark">{{ r.wip_warehouse || '—' }}</strong></span>
								</div>
								<router-link
									v-slot="{ navigate }"
									v-if="r.wip_warehouse"
									:to="{ path: '/inventory/stock-status', query: { warehouse: r.wip_warehouse } }"
									custom
								>
									<button
										type="button"
										class="btn btn-xs btn-outline-secondary py-0 px-2"
										@click="navigate"
									>
										<i class="ti ti-packages me-1"></i>{{ t("View Stock") }}
									</button>
								</router-link>
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
							<div v-if="r.finish_draft" class="alert alert-warning py-2 px-3 small w-100 mb-1">
								<i class="ti ti-device-floppy me-1"></i>{{ t("Unconfirmed finish saved by {0} at {1} — {2} good, {3} rejected.", [r.finish_draft.saved_by, r.finish_draft.saved_at, r.finish_draft.produced_qty, r.finish_draft.scrap_qty]) }}
							</div>

							<div v-if="halfAssigned(r)" class="alert alert-danger py-2 px-3 small w-100 mb-1">
								<i class="ti ti-user-exclamation me-1"></i>{{ t("Materials cannot be transferred until both operator roles are assigned.") }}
							</div>

							<button
								v-if="canStart(r)"
								type="button"
								class="btn btn-success btn-lg flex-grow-1 py-3 fw-bold shadow-sm d-flex align-items-center justify-content-center gap-2"
								:disabled="isBusy(r.name) || halfAssigned(r)"
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
								:disabled="isBusy(r.name) || halfAssigned(r)"
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
		
		<!-- Start Modal -->
		<template v-if="startTarget">
			<div class="modal-backdrop fade show" @click="cancelStart"></div>
			<div class="modal fade show d-block" tabindex="-1" style="background: transparent">
				<div class="modal-dialog modal-dialog-centered modal-lg">
					<div class="modal-content shadow-lg border-0" style="border-radius: 12px; max-height: 90vh; display: flex; flex-direction: column;">
						<div class="modal-header bg-light">
							<h5 class="modal-title fw-bold">
								{{ t("Start Work Order & Transfer Materials") }}
							</h5>
							<button type="button" class="btn-close" @click="cancelStart"></button>
						</div>
						<div class="modal-body p-4" style="overflow-y: auto; flex: 1;">
							<div v-if="actionError" class="alert alert-danger mb-3 border-0 shadow-sm">{{ actionError }}</div>
							
							<div class="row g-3 mb-4">
								<div class="col-md-6">
									<label class="form-label fw-bold text-secondary text-uppercase small">{{ t("From Warehouse") }}</label>
									<select v-model="transferFromWh" class="form-select">
										<option value="">-- {{ t("Select Warehouse") }} --</option>
										<option v-for="w in warehouses" :key="w.name" :value="w.name">
											{{ w.warehouse_name || w.name }}
										</option>
									</select>
								</div>
								<div class="col-md-6">
									<label class="form-label fw-bold text-secondary text-uppercase small">{{ t("To Warehouse (WIP)") }}</label>
									<select v-model="transferToWh" class="form-select">
										<option value="">-- {{ t("Select Warehouse") }} --</option>
										<option v-for="w in warehouses" :key="w.name" :value="w.name">
											{{ w.warehouse_name || w.name }}
										</option>
									</select>
								</div>
							</div>

							<div class="alert alert-secondary border-0 mb-0">
								<i class="ti ti-package me-1"></i>{{ t("Starting moves this order's materials from the store to the line. The store issues the standard quantities.") }}
							</div>
						</div>
						<div class="modal-footer bg-light p-3">
							<button type="button" class="btn btn-link link-secondary fw-semibold" @click="cancelStart">
								{{ t("Cancel") }}
							</button>
							<button
								type="button"
								class="btn btn-success btn-lg px-4 fw-bold shadow-sm"
								:disabled="!transferFromWh || !transferToWh || isBusy(startTarget.name)"
								@click="confirmStart"
							>
								<span v-if="isBusy(startTarget.name)" class="spinner-border spinner-border-sm me-1"></span>
								<i v-else class="ti ti-play-filled me-1"></i>{{ t("Start & Transfer") }}
							</button>
						</div>
					</div>
				</div>
			</div>
		</template>

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

							<div v-if="sweepPending" class="alert alert-warning border-0 shadow-sm mb-4">
								<div class="fw-bold mb-2">
									<i class="ti ti-alert-triangle me-1"></i>{{ t("The other operator has not written this off yet") }}
								</div>
								<p class="mb-3">{{ t("Finishing now writes it off under your name.") }}</p>
								<div class="form-check">
									<input
										id="sweep-ack"
										v-model="sweepAck"
										class="form-check-input"
										type="checkbox"
										style="width: 1.6rem; height: 1.6rem; margin-top: 0.1rem;"
									/>
									<label class="form-check-label fw-semibold ps-2 fs-5" for="sweep-ack">
										{{ t("Put it on my document anyway") }}
									</label>
								</div>
							</div>

							<div class="mb-4">
								<label class="form-label fw-bold text-dark fs-4 mb-2">{{ t("Good Produced Qty") }}</label>
								<input
									:value="producedQty"
									type="text"
									inputmode="decimal"
									class="form-control form-control-lg text-center fs-2 fw-bold font-monospace"
									:class="numTarget === 'produced' ? 'border-primary border-2' : ''"
									style="height: 60px;"
									autofocus
									@focus="numTarget = 'produced'"
									@input="onQtyInput($event, 'produced')"
								/>
								<div class="form-hint mt-2 text-secondary d-flex justify-content-between">
									<span>{{ t("Target Remaining") }}: <strong>{{ remainingQty(finishTarget) }}</strong></span>
									<span>{{ t("Planned Total") }}: <strong>{{ finishTarget.qty }}</strong></span>
								</div>
							</div>

							<!-- ONE reject box, and a switch that says where its number goes.
								 Not two boxes: the server refuses the combination per Work
								 Order in both directions, so two boxes an operator can fill
								 both of is a double count that surfaces as a confusing
								 refusal after the pallet has been counted. -->
							<div class="mb-2 border rounded p-3">
								<label class="form-label fw-bold text-dark fs-4 mb-2">
									{{ t("Scrap / Rejects Qty") }}
									<span class="text-secondary small fw-normal">({{ t("optional") }})</span>
								</label>

								<!-- The server's refusal, met here instead of there. -->
								<div v-if="rejectDecision.locked" class="alert alert-info py-2 mb-3">
									{{ t("This order's losses are already recorded with a reason ({0} so far), so the plain count is closed for it.", [scrapRecords]) }}
								</div>
								<div v-else class="btn-group w-100 mb-3" role="group">
									<button
										type="button"
										class="btn btn-lg btn-outline-secondary fw-semibold"
										:class="rejectMode === 'reasoned' ? 'active' : ''"
										@click="setRejectMode('reasoned')"
									>
										<i class="ti ti-clipboard-text me-1"></i>{{ t("With a reason") }}
									</button>
									<button
										type="button"
										class="btn btn-lg btn-outline-secondary fw-semibold"
										:class="rejectMode === 'count' ? 'active' : ''"
										@click="setRejectMode('count')"
									>
										{{ t("Just a count") }}
									</button>
								</div>

								<input
									:value="scrapQty"
									type="text"
									inputmode="decimal"
									class="form-control form-control-lg text-center fs-3 font-monospace"
									:class="numTarget === 'scrap' ? 'border-primary border-2' : ''"
									style="height: 50px;"
									placeholder="0"
									@focus="numTarget = 'scrap'"
									@input="onQtyInput($event, 'scrap')"
								/>

								<template v-if="rejectMode === 'reasoned' || rejectDecision.locked">
									<!-- Not an error toast, and not a stack trace: no tenant has
										 named a scrap warehouse yet, so this is the state this
										 panel opens in on every site until a manager acts. It
										 names the document and the role, and the plain count is
										 still there above as the way out. -->
									<div v-if="!scrapWarehouse" class="alert alert-warning py-2 mt-3 mb-0">
										<div class="fw-bold mb-1">
											<i class="ti ti-settings-exclamation me-1"></i>{{ t("Scrap is not set up on this site yet") }}
										</div>
										{{ t("Nothing can be recorded until a scrap warehouse is named in Stabler Manufacturing Settings. Ask a manufacturing manager to name one — the loss has to have somewhere to move to, or the record and the stock ledger would disagree.") }}
									</div>
									<div v-else-if="!scrapReady" class="alert alert-info py-2 mt-3 mb-0">
										{{ t("This order has nothing standing in WIP to scrap.") }}
									</div>
									<template v-else>
										<div class="mt-3">
											<div class="form-label fw-semibold">{{ t("Pick what was lost") }}</div>
											<div class="d-flex flex-wrap gap-2">
												<button
													v-for="it in scrapItems.filter((i) => Number(i.available) > 0)"
													:key="it.item_code"
													type="button"
													class="btn btn-lg btn-outline-secondary text-start"
													:class="scrapItem === it.item_code ? 'active' : ''"
													@click="scrapItem = it.item_code"
												>
													{{ it.item_name || it.item_code }}
													<span class="d-block small">{{ it.available }} {{ it.uom }}</span>
												</button>
											</div>
										</div>
										<div class="mt-3">
											<div class="form-label fw-semibold">{{ t("Pick a reason") }}</div>
											<div class="d-flex flex-wrap gap-2">
												<button
													v-for="r in scrapReasons"
													:key="r.name"
													type="button"
													class="btn btn-lg btn-outline-secondary"
													:class="scrapReason === r.name ? 'active' : ''"
													@click="scrapReason = r.name"
												>
													{{ t(r.reason) }}
												</button>
											</div>
										</div>
										<div v-if="scrapNotice" class="alert alert-success py-2 mt-3 mb-0">
											{{ scrapNotice }}
										</div>
										<button
											type="button"
											class="btn btn-lg btn-outline-secondary w-100 fw-semibold mt-3"
											:disabled="scrapBusy || !scrapItem || !scrapReason || !(Number(scrapQty) > 0)"
											@click="recordScrap"
										>
											<i class="ti ti-trash me-1"></i>{{ t("Record the loss") }}
										</button>
									</template>
								</template>

								<!-- The number is in the box, aimed at a record nobody filed.
									 Sending the Finish would drop it silently; saying so costs
									 one line and one tap. -->
								<div v-if="unfiledScrap" class="text-danger small fw-semibold mt-2">
									{{ t("Record this loss with its reason, or switch to a plain count, before finishing.") }}
								</div>
							</div>

							<!-- The terminal is wall-mounted and worked with gloves. Native
								 spinners put two 12-pixel arrows on that wall, and on a
								 locked-down kiosk it is a coin toss whether the OS offers a
								 keyboard at all. Tapping a field above aims the pad at it. -->
							<div class="mb-2">
								<!-- "All" fills the planned remainder, the end-of-shift case, in one
									 tap instead of four gloved digits. Good output only: "all of it
									 was scrap" is not a sensible default, and offering it there
									 invites a mis-tap that writes off a whole order. -->
								<NumPad
									v-model="numBuffer"
									:fill="numTarget === 'produced' ? String(remainingQty(finishTarget) || '') : ''"
								/>
							</div>

							<div class="border-top pt-3 mt-3">
								<label class="form-label fw-bold text-dark mb-2">
									<i class="ti ti-versions me-1"></i>{{ t("Batch / lot") }}
								</label>
								<input v-model="batchNo" type="text" class="form-control font-monospace mb-2" :placeholder="t('Batch / lot')" />
								<div class="row g-2">
									<div class="col-6">
										<label class="form-label small text-secondary">{{ t("Batch manufacture date") }}</label>
										<DateInput v-model="batchMfg" />
									</div>
									<div class="col-6">
										<label class="form-label small text-secondary">{{ t("Batch expiry") }}</label>
										<DateInput v-model="batchExpiry" />
									</div>
								</div>
							</div>
						</div>
						<div class="modal-footer bg-light p-3">
							<button type="button" class="btn btn-link link-secondary fw-semibold" @click="cancelFinish">
								{{ t("Cancel") }}
							</button>
							<button
								v-if="finishTarget.finish_draft"
								type="button"
								class="btn btn-link link-danger fw-semibold"
								:disabled="draftBusy"
								@click="discardDraft"
							>
								{{ t("Discard draft") }}
							</button>
							<!-- Saving parks the count without posting stock. The button is live at
								 zero produced on purpose: nothing good and forty rejected is a real
								 shift, and it is the one you least want counted twice. -->
							<button
								type="button"
								class="btn btn-outline-secondary btn-lg px-4 fw-semibold"
								:disabled="draftBusy"
								@click="saveDraft"
							>
								<i class="ti ti-device-floppy me-1"></i>{{ t("Save draft") }}
							</button>
							<button
								type="button"
								class="btn btn-primary btn-lg px-4 fw-bold shadow-sm"
								:disabled="!(Number(producedQty) > 0) || (sweepPending && !sweepAck) || unfiledScrap"
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
