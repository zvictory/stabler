<script setup>
/**
 * Remittance refund — the three signatures it takes to give the money back.
 *
 * Request → decide → post. Only the last of the three moves cash, and the screen
 * says so at every step, because the failure this layout exists to prevent is a
 * cashier reading "Approved" as "paid" and counting the notes out twice.
 *
 * Every button is drawn from the row's own `allowed_actions`, never from the
 * signed-in user's role and never from the transfer's status. `_remittance_actions`
 * on the server is the single table that decides; this file renders its answer and
 * holds no second opinion. A Cashier therefore never sees Approve or Reject, not
 * because this file checks for a Cashier — it does not know what a Cashier is — but
 * because the server did not offer those two actions on the row.
 *
 * The refund settles at the rate frozen when the transfer was registered (ADR-008),
 * not at today's rate. That is stated on the preview in words, because the cashier
 * handing the money over is the person who would otherwise assume the difference is
 * a shortfall in their own drawer.
 *
 * Nothing here reads, renders, stores or logs the pickup code. The refund kills the
 * code as a side effect of posting; that fact is worth saying out loud, and the code
 * itself is not this screen's to know.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { REMITTANCE_ACTIONS, REMITTANCE_QUEUES, remittanceApi } from "../../api/remittance.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import PostingPreview from "../../components/PostingPreview.vue";
import EmptyState from "../../components/EmptyState.vue";
import Pagination from "../../components/Pagination.vue";
import Select from "../../components/Select.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();

// --------------------------------------------------------------------- list --
// Three ways in, because a refund is worked from three different desks: the
// counter searching for the transfer a sender walked back in with, the manager
// clearing the decision queue, and the expiry queue — which today answers
// "no policy is configured" rather than "nothing has expired".
const SOURCE_SEARCH = "search";

const source = ref(SOURCE_SEARCH);
const search = ref("");
// The two operational statuses a refund is spoken of on. The server offers refund
// actions on `Registered` only; `Expired` is selectable so a transfer in that
// state can still be opened and read, and the workspace then says plainly that no
// step is available rather than hiding the transfer and explaining nothing.
const operationalStatus = ref("Registered");
const limitStart = ref(0);
const pageLength = ref(25);

const rows = ref([]);
const listTotal = ref(0);
const listLoading = ref(false);
const listError = ref("");
const policyConfigured = ref(true);
let listToken = 0;

const sources = computed(() => [
	{ key: SOURCE_SEARCH, label: t("Find a transfer"), icon: "ti-search" },
	{
		// The queue behind this tab carries Requested AND Approved (stabler-t1j9):
		// an approved refund is not a decision still to make, it is cash the origin
		// desk still has to count out. "Awaiting approval" promised only the first
		// half and the tab listed both.
		key: REMITTANCE_QUEUES.REFUND_AWAITING_APPROVAL,
		label: t("Refund open"),
		icon: "ti-gavel",
	},
	{
		key: REMITTANCE_QUEUES.EXPIRED_REFUND_REQUIRED,
		label: t("Expired / refund required"),
		icon: "ti-clock-exclamation",
	},
]);

const statusOptions = computed(() => [
	{ value: "Registered", label: t("Registered") },
	{ value: "Expired", label: t("Expired") },
]);

// ---------------------------------------------------------------- selection --
const selected = ref("");
const detail = ref(null);
const detailLoading = ref(false);
const detailError = ref("");

// ------------------------------------------------------------------- forms --
const senderCheck = ref("");
const requestReason = ref("");
const approveNote = ref("");
const rejectReason = ref("");
const postingDate = ref("");
const busy = ref("");
// The refund's counted-cash confirmation. Payout has had one since it shipped
// (RemittancePayout.vue, "I have counted …"); this side moves the same cash in the
// other direction and had nothing but a warning paragraph — the button was live the
// moment the card rendered.
const refundCashConfirmed = ref(false);
const preview = ref(null);
const previewLoading = ref(false);
const previewError = ref("");

// One idempotency key per step, generated on the first attempt and kept until
// that step succeeds — so a retry after a timeout replays the same key and the
// server answers with the original result instead of recording the step twice.
// Deliberately not reactive: nothing renders it.
let requestKeys = new Map();

function keyFor(action) {
	if (!requestKeys.has(action)) requestKeys.set(action, crypto.randomUUID());
	return requestKeys.get(action);
}

// ------------------------------------------------------------------ labels --
const actionLabels = computed(() => ({
	[REMITTANCE_ACTIONS.PAYOUT]: t("Pay out"),
	[REMITTANCE_ACTIONS.UNLOCK_PICKUP_CODE]: t("Unlock pickup code"),
	[REMITTANCE_ACTIONS.REQUEST_REFUND]: t("Request refund"),
	[REMITTANCE_ACTIONS.APPROVE_REFUND]: t("Approve refund"),
	[REMITTANCE_ACTIONS.REJECT_REFUND]: t("Reject refund"),
	[REMITTANCE_ACTIONS.COMPLETE_REFUND]: t("Complete refund"),
}));

const statusLabels = computed(() => ({
	// operational
	Draft: t("Draft"),
	Registered: t("Registered"),
	"Paid Out": t("Paid Out"),
	Refunded: t("Refunded"),
	Exception: t("Exception"),
	// accounting
	Unposted: t("Unposted"),
	Posted: t("Posted"),
	Reversed: t("Reversed"),
	"Posting Error": t("Posting Error"),
	// verification
	"Not Issued": t("Not Issued"),
	Active: t("Active"),
	Locked: t("Locked"),
	Consumed: t("Consumed"),
	Expired: t("Expired"),
	// refund
	None: t("None"),
	Requested: t("Requested"),
	Approved: t("Approved"),
	Rejected: t("Rejected"),
	Completed: t("Completed"),
}));

const commissionModeLabels = computed(() => ({
	Exclusive: t("Exclusive"),
	Inclusive: t("Inclusive"),
}));

function label(map, value) {
	if (value === null || value === undefined || value === "") return "—";
	return map[value] || value;
}

function money(value, currency) {
	return formatMoney(value, currency, user.value?.language);
}

// A rate is not money and must not be formatted as money. Trailing zeros are
// trimmed so 1 reads as "1" and 0.904200 as "0.9042"; a missing or zero rate
// reads as "—", never as a number this screen made up.
function rate(value) {
	const n = Number(value);
	if (!Number.isFinite(n) || n === 0) return "—";
	return String(Number(n.toFixed(6)));
}

// A percentage, unlike a rate, is legitimately zero — a transfer registered with
// no commission has to read "0%", not "—%".
function percent(value) {
	const n = Number(value);
	if (value === null || value === undefined || value === "" || !Number.isFinite(n)) return "—";
	return String(Number(n.toFixed(4)));
}

function errText(err, fallback) {
	const message = err && typeof err.message === "string" ? err.message.trim() : "";
	return message || fallback;
}

// ------------------------------------------------------------ derived state --
const transfer = computed(() => detail.value?.transfer || null);
// `{}` and not `null`: every field read off the quote goes through `money()` or
// `rate()`, both of which render "—" for a missing value. A null here would turn
// one absent block into a render crash on the whole workspace.
const quote = computed(() => detail.value?.quote || {});
const axes = computed(() => detail.value?.status || {});
const trail = computed(() => detail.value?.refund || {});
const codeState = computed(() => detail.value?.code_state || {});
const refundStatus = computed(() => detail.value?.refund?.status || "None");

const allowed = computed(() => new Set(detail.value?.allowed_actions || []));

function can(action) {
	return allowed.value.has(action);
}

const showsAnyStep = computed(
	() =>
		can(REMITTANCE_ACTIONS.REQUEST_REFUND) ||
		can(REMITTANCE_ACTIONS.APPROVE_REFUND) ||
		can(REMITTANCE_ACTIONS.REJECT_REFUND) ||
		can(REMITTANCE_ACTIONS.COMPLETE_REFUND)
);

// The three stages, in the order the money follows them. `done` is read off the
// refund status rather than off the presence of an event, so a re-requested
// refund that was rejected once does not show as approved.
const stages = computed(() => {
	const status = refundStatus.value;
	return [
		{
			key: "requested",
			label: t("Requested"),
			icon: "ti-file-text",
			done: ["Requested", "Approved", "Completed", "Rejected"].includes(status),
			event: trail.value.requested,
		},
		{
			key: "approved",
			label: t("Approved"),
			icon: "ti-gavel",
			done: ["Approved", "Completed"].includes(status),
			event: trail.value.approved,
		},
		{
			key: "completed",
			label: t("Cash returned"),
			icon: "ti-cash",
			done: status === "Completed",
			event: trail.value.completed,
		},
	];
});

// The audit table. Fixed four-row shape and fixed order — a rejected request
// that was later re-requested and approved leaves all four rows populated, and
// the order is what makes that readable.
const trailRows = computed(() => [
	{ key: "requested", label: t("Requested"), event: trail.value.requested },
	{ key: "approved", label: t("Approved"), event: trail.value.approved },
	{ key: "rejected", label: t("Rejected"), event: trail.value.rejected },
	{ key: "completed", label: t("Completed"), event: trail.value.completed },
]);

// The one check this screen makes on its own: the person at the counter is the
// sender. Case and inner spacing are noise, so both are normalised away; an
// empty box never passes.
function normalizeName(value) {
	return String(value || "")
		.trim()
		.replace(/\s+/g, " ")
		.toLocaleLowerCase();
}

const senderVerified = computed(() => {
	const typed = normalizeName(senderCheck.value);
	if (!typed) return false;
	return typed === normalizeName(transfer.value?.sender_name);
});

const senderMismatch = computed(
	() => normalizeName(senderCheck.value).length > 0 && !senderVerified.value
);

const canSubmitRequest = computed(
	() =>
		can(REMITTANCE_ACTIONS.REQUEST_REFUND) &&
		senderVerified.value &&
		requestReason.value.trim().length > 0 &&
		!busy.value
);

const canSubmitReject = computed(
	() => can(REMITTANCE_ACTIONS.REJECT_REFUND) && rejectReason.value.trim().length > 0 && !busy.value
);

// ------------------------------------------------------------------- loading --
async function loadList() {
	const company = activeCompany.value;
	if (!company) {
		rows.value = [];
		listTotal.value = 0;
		return;
	}
	const token = ++listToken;
	listLoading.value = true;
	listError.value = "";
	try {
		const response =
			source.value === SOURCE_SEARCH
				? await remittanceApi.transfers({
						company,
						query: search.value.trim() || null,
						status: operationalStatus.value,
						limit: pageLength.value,
						offset: limitStart.value,
					})
				: await remittanceApi.workQueue(company, source.value, pageLength.value, limitStart.value);
		if (token !== listToken) return;
		rows.value = response?.rows || [];
		listTotal.value = Number(response?.total) || 0;
		// The flag only exists on the queue responses. Absent means "not a question
		// this endpoint answers", which is not the same as `false`.
		policyConfigured.value = response?.policy_configured !== false;
	} catch (err) {
		if (token !== listToken) return;
		rows.value = [];
		listTotal.value = 0;
		listError.value = errText(err, t("The transfer list could not be loaded."));
	} finally {
		if (token === listToken) listLoading.value = false;
	}
}

async function loadDetail() {
	if (!selected.value) return;
	detailLoading.value = true;
	detailError.value = "";
	try {
		detail.value = await remittanceApi.transferDetail(selected.value);
		// Only when the cash card can actually render: the preview is what that
		// card's confirmation is about, and fetching it for a transfer nobody may
		// complete is a request per click with nothing to show for it.
		if (can(REMITTANCE_ACTIONS.COMPLETE_REFUND)) await loadPreview();
	} catch (err) {
		detail.value = null;
		detailError.value = errText(err, t("This transfer could not be loaded."));
	} finally {
		detailLoading.value = false;
	}
}

function resetForms() {
	senderCheck.value = "";
	requestReason.value = "";
	approveNote.value = "";
	rejectReason.value = "";
	postingDate.value = "";
	refundCashConfirmed.value = false;
	preview.value = null;
	previewError.value = "";
	requestKeys = new Map();
}

function open(name) {
	if (!name) return;
	selected.value = name;
	detail.value = null;
	detailError.value = "";
	resetForms();
	loadDetail();
}

function clearSelection() {
	selected.value = "";
	detail.value = null;
	detailError.value = "";
	resetForms();
}

function setSource(key) {
	if (source.value === key) return;
	source.value = key;
	limitStart.value = 0;
	loadList();
}

function onSearch() {
	limitStart.value = 0;
	loadList();
}

// ------------------------------------------------------------------ mutating --
/**
 * Run one refund step. Returns true only when the server accepted it.
 *
 * The idempotency key is dropped on success and KEPT on failure, so a retry
 * after a network error replays the same key rather than asking for a second
 * refund. The detail is re-read afterwards because a mutation response carries
 * the new statuses but not the new `allowed_actions` — and `allowed_actions` is
 * the only thing this screen draws buttons from.
 */
async function run(action, invoke, successMessage) {
	if (busy.value) return false;
	busy.value = action;
	try {
		const result = await invoke(keyFor(action));
		requestKeys.delete(action);
		if (result && result.replayed) {
			toast.info(t("This step was already recorded. Nothing was posted a second time."));
		} else {
			toast.success(successMessage);
		}
		await loadDetail();
		await loadList();
		return true;
	} catch (err) {
		toast.error(errText(err, t("The step could not be completed. Nothing was changed.")));
		return false;
	} finally {
		busy.value = "";
	}
}

async function submitRequest() {
	if (!canSubmitRequest.value) return;
	const reason = requestReason.value.trim();
	const ok = await run(
		REMITTANCE_ACTIONS.REQUEST_REFUND,
		(key) => remittanceApi.requestRefund(selected.value, reason, key),
		t("Refund requested. No money has moved.")
	);
	if (ok) {
		requestReason.value = "";
		senderCheck.value = "";
	}
}

async function submitApprove() {
	if (!can(REMITTANCE_ACTIONS.APPROVE_REFUND) || busy.value) return;
	const confirmed = await confirm({
		title: t("Approve this refund?"),
		body: t(
			"Approving records the decision and nothing else. No cash leaves the drawer at this step — the sender is paid back only when the refund is completed."
		),
		confirmLabel: t("Approve refund"),
		cancelLabel: t("Cancel"),
	});
	if (!confirmed) return;
	const note = approveNote.value.trim();
	const ok = await run(
		REMITTANCE_ACTIONS.APPROVE_REFUND,
		(key) => remittanceApi.approveRefund(selected.value, key, note || null),
		t("Refund approved. No money has moved yet.")
	);
	if (ok) approveNote.value = "";
}

async function submitReject() {
	if (!canSubmitReject.value) return;
	const reason = rejectReason.value.trim();
	const ok = await run(
		REMITTANCE_ACTIONS.REJECT_REFUND,
		(key) => remittanceApi.rejectRefund(selected.value, reason, key),
		t("Refund request rejected. The transfer stays as it was.")
	);
	if (ok) rejectReason.value = "";
}

/** The reversal this step will post, asked for when the transfer is opened. */
async function loadPreview() {
	const name = selected.value;
	if (!name) return;
	previewLoading.value = true;
	previewError.value = "";
	try {
		const rows = await remittanceApi.postingPreview(name, "Refund", postingDate.value || null);
		// The cashier may have opened another transfer while this was in flight.
		// Guarded on the assignment, not only on the spinner: this table renders
		// immediately above "I have counted {amount} and am handing it back".
		if (selected.value !== name) return;
		preview.value = rows;
	} catch (err) {
		if (selected.value !== name) return;
		// Never an empty table: an empty table reads as "this posts nothing", which
		// is the opposite of what a refund does.
		preview.value = null;
		previewError.value = err?.message || t("The posting could not be previewed.");
	} finally {
		if (selected.value === name) previewLoading.value = false;
	}
}

async function submitComplete() {
	if (!can(REMITTANCE_ACTIONS.COMPLETE_REFUND) || busy.value) return;
	if (!refundCashConfirmed.value) return;
	const confirmed = await confirm({
		title: t("Pay this refund back to the sender?"),
		body: t(
			"This posts the reversal and hands {amount} back to {sender} at the origin desk. The pickup code stops working and the transfer can no longer be paid out.",
			{
				amount: money(quote.value?.tendered, transfer.value?.send_currency),
				sender: transfer.value?.sender_name || "—",
			}
		),
		danger: true,
		confirmLabel: t("Post the refund"),
		cancelLabel: t("Cancel"),
	});
	if (!confirmed) return;
	const ok = await run(
		REMITTANCE_ACTIONS.COMPLETE_REFUND,
		(key) => remittanceApi.completeRefund(selected.value, key, postingDate.value || null),
		t("Refund posted. Hand the cash back to the sender.")
	);
	if (ok) {
		postingDate.value = "";
		refundCashConfirmed.value = false;
	}
}

// -------------------------------------------------------------------- wiring --
watch(activeCompany, () => {
	clearSelection();
	limitStart.value = 0;
	loadList();
});

watch([limitStart, pageLength], loadList);
watch(operationalStatus, () => {
	if (source.value !== SOURCE_SEARCH) return;
	limitStart.value = 0;
	loadList();
});

onMounted(loadList);
</script>

<template>
	<div class="stbl-refund">
		<EmptyState
			v-if="!activeCompany"
			icon="ti-building"
			accent-icon="ti-alert-circle"
			tone="warning"
			:title="t('No company is selected')"
			:subtitle="t('Pick a company to work its refunds.')"
		/>

		<!-- ------------------------------------------------------------- picker -->
		<div v-else-if="!selected" class="card">
			<div class="card-header py-2 flex-wrap gap-2">
				<div class="card-title">{{ t("Refunds") }}</div>
				<div class="ms-auto btn-group btn-group-sm stbl-refund-sources" role="group">
					<button
						v-for="s in sources"
						:key="s.key"
						type="button"
						class="btn btn-outline-secondary"
						:class="{ active: source === s.key }"
						@click="setSource(s.key)"
					>
						<i class="ti me-1" :class="s.icon"></i>{{ s.label }}
					</button>
				</div>
			</div>

			<ListToolbar
				v-if="source === SOURCE_SEARCH"
				v-model="search"
				:placeholder="t('Reference, sender, receiver or desk… ⌘K')"
				:count="listTotal"
				@search="onSearch"
			>
				<template #filters>
					<div style="width: 160px">
						<Select v-model="operationalStatus" :options="statusOptions" size="sm" />
					</div>
				</template>
			</ListToolbar>
			<div
				v-else
				class="d-flex align-items-center gap-3 flex-wrap py-2 px-3 border-bottom bg-light small text-secondary"
			>
				<div>
					{{ t("Count") }}:
					<strong class="font-monospace text-body">{{ listTotal }}</strong>
				</div>
			</div>

			<div v-if="listError" class="card-body">
				<div class="alert alert-danger m-0">{{ listError }}</div>
			</div>

			<EmptyState
				v-else-if="!listLoading && !policyConfigured"
				icon="ti-clock-off"
				accent-icon="ti-alert-circle"
				tone="warning"
				:title="t('No pickup expiry policy is configured yet')"
				:subtitle="
					t(
						'Nothing records when a transfer expires, so this queue cannot say whether anything has expired. That is not the same as saying nothing has.'
					)
				"
			/>

			<EmptyState
				v-else-if="!listLoading && !rows.length"
				icon="ti-receipt-refund"
				accent-icon="ti-search"
				:title="t('No transfers here')"
				:subtitle="t('Nothing in this list matches. Try another search or another queue.')"
			/>

			<div v-else class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th>{{ t("Reference") }}</th>
							<th>{{ t("Sender → Receiver") }}</th>
							<th class="d-none d-lg-table-cell">{{ t("Route") }}</th>
							<th class="text-end">{{ t("Sender paid") }}</th>
							<th>{{ t("Refund") }}</th>
							<th>{{ t("Next step") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="listLoading" :rows="6" :cols="6" />
					<tbody v-else>
						<tr v-for="row in rows" :key="row.name" style="cursor: pointer" @click="open(row.name)">
							<td>
								<div class="font-monospace">{{ row.name }}</div>
								<div class="text-secondary small font-monospace">
									{{ row.client_request_id || "—" }}
								</div>
							</td>
							<td>
								<div>{{ row.sender_name || "—" }}</div>
								<div class="text-secondary small">{{ row.receiver_name || "—" }}</div>
							</td>
							<td class="d-none d-lg-table-cell small text-secondary">
								{{ row.origin_branch || "—" }} → {{ row.destination_branch || "—" }}
							</td>
							<td class="text-end font-monospace">
								{{ money(row.tendered, row.send_currency) }}
							</td>
							<td>
								<span
									class="badge"
									:class="getStatusBadgeClass('Remittance Transfer', row.refund_status)"
								>
									{{ label(statusLabels, row.refund_status || "None") }}
								</span>
							</td>
							<td class="small">
								<span v-if="row.next_action">
									{{ label(actionLabels, row.next_action) }}
								</span>
								<span v-else class="text-secondary">{{ t("None available") }}</span>
							</td>
						</tr>
					</tbody>
				</table>
			</div>

			<div v-if="!listError && policyConfigured" class="card-footer p-0">
				<Pagination
					v-model:limit-start="limitStart"
					v-model:page-length="pageLength"
					:total="listTotal"
					:page-count="rows.length"
				/>
			</div>
		</div>

		<!-- ---------------------------------------------------------- workspace -->
		<template v-else>
			<div v-if="detailLoading" class="card">
				<div class="card-body text-center py-5">
					<div class="spinner-border text-primary" role="status"></div>
				</div>
			</div>

			<div v-else-if="detailError" class="card">
				<div class="card-body">
					<div class="alert alert-danger">{{ detailError }}</div>
					<button type="button" class="btn btn-outline-secondary" @click="clearSelection">
						<i class="ti ti-arrow-left me-1"></i>{{ t("Back to list") }}
					</button>
				</div>
			</div>

			<template v-else-if="transfer">
				<!-- Facts -->
				<div class="card mb-3">
					<div class="card-body py-3">
						<div class="d-flex align-items-start gap-3 flex-wrap">
							<button type="button" class="btn btn-sm btn-ghost-secondary" @click="clearSelection">
								<i class="ti ti-arrow-left me-1"></i>{{ t("Back to list") }}
							</button>
							<div class="flex-fill">
								<div class="font-monospace fw-bold fs-3">{{ transfer.name }}</div>
								<div class="text-secondary small font-monospace">
									{{ transfer.client_request_id || "—" }}
								</div>
							</div>
							<div class="d-flex flex-wrap gap-2">
								<span
									class="badge"
									:class="getStatusBadgeClass('Remittance Transfer', axes.operational)"
								>
									{{ t("Operational") }}: {{ label(statusLabels, axes.operational) }}
								</span>
								<span
									class="badge"
									:class="getStatusBadgeClass('Remittance Transfer', axes.accounting)"
								>
									{{ t("Accounting") }}: {{ label(statusLabels, axes.accounting) }}
								</span>
								<span
									class="badge"
									:class="getStatusBadgeClass('Remittance Transfer', axes.verification)"
								>
									{{ t("Pickup") }}: {{ label(statusLabels, axes.verification) }}
								</span>
								<span
									class="badge"
									:class="getStatusBadgeClass('Remittance Transfer', axes.refund)"
								>
									{{ t("Refund") }}: {{ label(statusLabels, axes.refund || "None") }}
								</span>
							</div>
						</div>

						<div class="row g-3 mt-1">
							<div class="col-6 col-lg-3">
								<div class="text-secondary small">{{ t("Sender") }}</div>
								<div class="fw-semibold">{{ transfer.sender_name || "—" }}</div>
							</div>
							<div class="col-6 col-lg-3">
								<div class="text-secondary small">{{ t("Receiver") }}</div>
								<div class="fw-semibold">{{ transfer.receiver_name || "—" }}</div>
							</div>
							<div class="col-6 col-lg-3">
								<div class="text-secondary small">{{ t("Route") }}</div>
								<div>
									{{ transfer.origin_branch || "—" }}
									<span class="text-secondary">({{ transfer.origin_city || "—" }})</span>
									→
									{{ transfer.destination_branch || "—" }}
									<span class="text-secondary"> ({{ transfer.destination_city || "—" }}) </span>
								</div>
							</div>
							<div class="col-6 col-lg-3">
								<div class="text-secondary small">{{ t("Registered") }}</div>
								<div>{{ formatDateTime(transfer.registered_at) || "—" }}</div>
								<div class="text-secondary small">{{ transfer.registered_by || "—" }}</div>
							</div>
						</div>

						<div v-if="codeState.locked" class="alert alert-warning mt-3 mb-0 py-2 small">
							<i class="ti ti-lock me-1"></i>
							{{
								t(
									"The pickup code is locked after {attempts} of {max} failed attempts. A refund does not need it unlocked — completing the refund retires the code for good.",
									{ attempts: codeState.attempts, max: codeState.max_attempts }
								)
							}}
						</div>
					</div>
				</div>

				<!-- Stage strip -->
				<div class="card mb-3">
					<div class="card-body py-3">
						<div class="d-flex align-items-stretch gap-2 flex-wrap">
							<div
								v-for="(stage, index) in stages"
								:key="stage.key"
								class="stbl-refund-stage flex-fill"
								:class="{ 'is-done': stage.done }"
							>
								<div class="d-flex align-items-center gap-2">
									<i class="ti" :class="stage.done ? 'ti-circle-check' : stage.icon"></i>
									<span class="fw-semibold"> {{ index + 1 }}. {{ stage.label }} </span>
								</div>
								<div v-if="stage.event" class="small text-secondary mt-1">
									{{ formatDateTime(stage.event.at) }} · {{ stage.event.actor || "—" }}
								</div>
								<div v-else class="small text-secondary mt-1">{{ t("Not yet") }}</div>
							</div>
						</div>

						<div v-if="refundStatus === 'Rejected'" class="alert alert-danger mt-3 mb-0 py-2">
							<div class="fw-semibold">{{ t("This refund request was rejected.") }}</div>
							<div v-if="trail.rejected" class="small mt-1">
								{{ formatDateTime(trail.rejected.at) }} · {{ trail.rejected.actor || "—" }} ·
								{{ trail.rejected.details || "—" }}
							</div>
						</div>
						<div
							v-else-if="refundStatus === 'Completed'"
							class="alert alert-success mt-3 mb-0 py-2"
						>
							<div class="fw-semibold">
								{{ t("The refund is posted and the cash has gone back.") }}
							</div>
							<div class="small mt-1">
								{{ t("The pickup code for this transfer no longer works.") }}
							</div>
						</div>
					</div>
				</div>

				<div class="row g-3">
					<!-- What goes back -->
					<div class="col-12 col-lg-6">
						<div class="card h-100">
							<div class="card-header py-2">
								<div class="card-title">{{ t("What goes back to the sender") }}</div>
							</div>
							<div class="card-body">
								<table class="table table-sm table-no-stripe mb-0">
									<tbody>
										<tr>
											<td>{{ t("Principal") }}</td>
											<td class="text-end font-monospace">
												{{ money(quote.principal, transfer.send_currency) }}
											</td>
										</tr>
										<tr>
											<td>
												{{ t("Commission") }}
												<span class="text-secondary small">
													({{ label(commissionModeLabels, quote.commission_mode) }},
													{{ percent(quote.commission_pct) }}%)
												</span>
											</td>
											<td class="text-end font-monospace">
												{{ money(quote.commission, transfer.send_currency) }}
											</td>
										</tr>
										<tr class="fw-bold border-top">
											<td>{{ t("Total returned to the sender") }}</td>
											<td class="text-end font-monospace fs-3">
												{{ money(quote.tendered, transfer.send_currency) }}
											</td>
										</tr>
										<tr>
											<td class="text-secondary small">
												{{ t("Receiver obligation reversed") }}
											</td>
											<td class="text-end font-monospace small text-secondary">
												{{ money(quote.receiver_amount, transfer.receive_currency) }}
											</td>
										</tr>
									</tbody>
								</table>

								<div class="alert alert-info mt-3 mb-0 py-2">
									<div class="fw-semibold">
										{{ t("Settled at the registration rate, not today's rate.") }}
									</div>
									<div class="small mt-1">
										{{
											t(
												"The obligation closes at the same rate it opened at, so the sender gets back exactly what they put on the counter. Any market move since registration is not a shortfall in this drawer and must not be made up out of it."
											)
										}}
									</div>
									<div class="d-flex flex-wrap gap-4 mt-2 small">
										<div v-if="transfer.send_currency !== transfer.receive_currency">
											<div class="text-secondary">
												{{ t("Rate typed at registration") }}
											</div>
											<div class="font-monospace">
												{{ rate(quote.exchange_rate) }}
												{{ transfer.receive_currency }} / 1
												{{ transfer.send_currency }}
											</div>
										</div>
										<div>
											<div class="text-secondary">
												{{ t("Base rate the register leg posted at") }}
											</div>
											<div class="font-monospace">
												{{ rate(quote.register_base_rate) }}
											</div>
											<div v-if="rate(quote.register_base_rate) === '—'" class="text-secondary">
												{{ t("not recorded on this transfer") }}
											</div>
										</div>
									</div>
								</div>

								<div class="text-secondary small mt-3">
									{{ t("Nothing on this screen moves cash until the final step is posted.") }}
								</div>
							</div>
						</div>
					</div>

					<!-- The steps -->
					<div class="col-12 col-lg-6 stbl-refund-actions">
						<EmptyState
							v-if="!showsAnyStep"
							icon="ti-lock"
							accent-icon="ti-info-circle"
							tone="warning"
							compact
							:title="t('No refund step is open to you on this transfer')"
							:subtitle="
								t(
									'The server decides this from the transfer state and your role. Operational status is {operational}, accounting status is {accounting}, refund status is {refund}.',
									{
										operational: label(statusLabels, axes.operational),
										accounting: label(statusLabels, axes.accounting),
										refund: label(statusLabels, axes.refund || 'None'),
									}
								)
							"
						/>

						<!-- Step 1 — request -->
						<div v-if="can(REMITTANCE_ACTIONS.REQUEST_REFUND)" class="card mb-3">
							<div class="card-header py-2">
								<div class="card-title">{{ t("1. Request the refund") }}</div>
							</div>
							<div class="card-body">
								<div class="mb-3">
									<label class="form-label" for="stbl-refund-sender">
										{{ t("Confirm the sender") }}
									</label>
									<input
										id="stbl-refund-sender"
										v-model="senderCheck"
										type="text"
										class="form-control"
										autocomplete="off"
										:class="{
											'is-invalid': senderMismatch,
											'is-valid': senderVerified,
										}"
										:placeholder="t('Type the sender name as registered')"
									/>
									<div class="form-hint">
										{{
											t(
												"Check the sender's ID at the counter, then type their name exactly as it was registered. The refund is paid to that person and nobody else."
											)
										}}
									</div>
									<div v-if="senderMismatch" class="invalid-feedback d-block">
										{{ t("That is not the name this transfer was registered under.") }}
									</div>
								</div>

								<div class="mb-3">
									<label class="form-label required" for="stbl-refund-reason">
										{{ t("Reason for the refund") }}
									</label>
									<textarea
										id="stbl-refund-reason"
										v-model="requestReason"
										class="form-control"
										rows="3"
										:placeholder="t('Why is this transfer being returned?')"
									></textarea>
									<div class="form-hint">
										{{
											t(
												"This reason is written to the transfer's permanent event trail and is what the approving manager reads."
											)
										}}
									</div>
								</div>

								<button
									type="button"
									class="btn btn-primary w-100"
									:disabled="!canSubmitRequest"
									@click="submitRequest"
								>
									<span
										v-if="busy === REMITTANCE_ACTIONS.REQUEST_REFUND"
										class="spinner-border spinner-border-sm me-2"
									></span>
									<i v-else class="ti ti-receipt-refund me-1"></i>
									{{ t("Request refund") }}
								</button>
								<div class="text-secondary small mt-2">
									{{ t("Requesting a refund does not move money.") }}
								</div>
							</div>
						</div>

						<!-- Step 2 — decide -->
						<div
							v-if="can(REMITTANCE_ACTIONS.APPROVE_REFUND) || can(REMITTANCE_ACTIONS.REJECT_REFUND)"
							class="card mb-3"
						>
							<div class="card-header py-2">
								<div class="card-title">{{ t("2. Decide") }}</div>
							</div>
							<div class="card-body">
								<div class="alert alert-warning py-2">
									<div class="fw-semibold">
										{{ t("Approving does not move money.") }}
									</div>
									<div class="small mt-1">
										{{
											t(
												"Approval records the decision only. No cash leaves the drawer until step 3 is posted — do not pay the sender on the strength of this step."
											)
										}}
									</div>
								</div>

								<div v-if="trail.requested" class="mb-3">
									<div class="text-secondary small">{{ t("Requested") }}</div>
									<div class="small">
										{{ formatDateTime(trail.requested.at) }} ·
										{{ trail.requested.actor || "—" }}
									</div>
									<div class="mt-1">{{ trail.requested.details || "—" }}</div>
								</div>

								<div v-if="can(REMITTANCE_ACTIONS.APPROVE_REFUND)" class="mb-3">
									<label class="form-label" for="stbl-refund-note">
										{{ t("Approval note") }}
										<span class="text-secondary">{{ t("(optional)") }}</span>
									</label>
									<textarea
										id="stbl-refund-note"
										v-model="approveNote"
										class="form-control"
										rows="2"
									></textarea>
								</div>

								<button
									v-if="can(REMITTANCE_ACTIONS.APPROVE_REFUND)"
									type="button"
									class="btn btn-primary w-100 mb-3"
									:disabled="!!busy"
									@click="submitApprove"
								>
									<span
										v-if="busy === REMITTANCE_ACTIONS.APPROVE_REFUND"
										class="spinner-border spinner-border-sm me-2"
									></span>
									<i v-else class="ti ti-gavel me-1"></i>
									{{ t("Approve refund") }}
								</button>

								<template v-if="can(REMITTANCE_ACTIONS.REJECT_REFUND)">
									<div class="mb-2">
										<label class="form-label required" for="stbl-refund-reject">
											{{ t("Reason for rejecting") }}
										</label>
										<textarea
											id="stbl-refund-reject"
											v-model="rejectReason"
											class="form-control"
											rows="2"
										></textarea>
									</div>
									<button
										type="button"
										class="btn btn-outline-danger w-100"
										:disabled="!canSubmitReject"
										@click="submitReject"
									>
										<span
											v-if="busy === REMITTANCE_ACTIONS.REJECT_REFUND"
											class="spinner-border spinner-border-sm me-2"
										></span>
										<i v-else class="ti ti-x me-1"></i>
										{{ t("Reject refund") }}
									</button>
								</template>
							</div>
						</div>

						<!-- Step 3 — pay it back -->
						<div v-if="can(REMITTANCE_ACTIONS.COMPLETE_REFUND)" class="card mb-3">
							<div class="card-header py-2">
								<div class="card-title">{{ t("3. Pay the money back") }}</div>
							</div>
							<div class="card-body">
								<div class="alert alert-danger py-2">
									<div class="fw-semibold">{{ t("This is the step that moves cash.") }}</div>
									<div class="small mt-1">
										{{
											t(
												"Posting this reverses the obligation and takes {amount} out of the origin desk. The pickup code stops working and the transfer can no longer be paid out.",
												{
													amount: money(quote.tendered, transfer.send_currency),
												}
											)
										}}
									</div>
								</div>

								<div v-if="trail.approved" class="mb-3 small">
									<div class="text-secondary">{{ t("Approved") }}</div>
									<div>
										{{ formatDateTime(trail.approved.at) }} ·
										{{ trail.approved.actor || "—" }}
									</div>
									<div class="mt-1">{{ trail.approved.details || "—" }}</div>
								</div>

								<div class="mb-3">
									<label class="form-label" for="stbl-refund-posting">
										{{ t("Posting date") }}
										<span class="text-secondary">{{ t("(defaults to today)") }}</span>
									</label>
									<DateInput id="stbl-refund-posting" v-model="postingDate" />
								</div>

								<PostingPreview
									:rows="preview?.rows || []"
									:base-currency="preview?.base_currency || ''"
									:total-debit="preview?.total_debit || 0"
									:total-credit="preview?.total_credit || 0"
									:balanced="Boolean(preview?.balanced)"
									:loading="previewLoading"
									:error="previewError"
								/>

								<label class="form-check stbl-touch mb-3">
									<input v-model="refundCashConfirmed" class="form-check-input" type="checkbox" />
									<span class="form-check-label">
										{{
											t("I have counted {amount} and am handing it back to {sender}.", {
												amount: money(quote.tendered, transfer.send_currency),
												sender: transfer.sender_name || t("the sender"),
											})
										}}
									</span>
								</label>

								<button
									type="button"
									class="btn btn-danger w-100"
									:disabled="!!busy || !refundCashConfirmed"
									@click="submitComplete"
								>
									<span
										v-if="busy === REMITTANCE_ACTIONS.COMPLETE_REFUND"
										class="spinner-border spinner-border-sm me-2"
									></span>
									<i v-else class="ti ti-cash me-1"></i>
									{{ t("Pay refund cash") }}
								</button>
							</div>
						</div>
					</div>
				</div>

				<!-- Trail -->
				<div class="card mt-3">
					<div class="card-header py-2">
						<div class="card-title">{{ t("Refund trail") }}</div>
					</div>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter card-table">
							<thead>
								<tr>
									<th>{{ t("Step") }}</th>
									<th>{{ t("When") }}</th>
									<th>{{ t("Who") }}</th>
									<th>{{ t("Desk") }}</th>
									<th>{{ t("What they said") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="row in trailRows" :key="row.key">
									<td>{{ row.label }}</td>
									<td>{{ row.event ? formatDateTime(row.event.at) : "—" }}</td>
									<td>{{ row.event?.actor || "—" }}</td>
									<td>{{ row.event?.branch || "—" }}</td>
									<td class="small">{{ row.event?.details || "—" }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</template>
		</template>
	</div>
</template>

<style scoped>
.stbl-refund-stage {
	min-width: 160px;
	border: 1px solid var(--tblr-border-color-light, #eef1f6);
	border-radius: 6px;
	padding: 0.5rem 0.75rem;
	background: var(--tblr-bg-surface, #fff);
}
.stbl-refund-stage.is-done {
	border-color: var(--tblr-green, #2fb344);
}
.stbl-refund-stage.is-done .ti {
	color: var(--tblr-green, #2fb344);
}

/* Desktop stays compact; on a phone every control clears the 40px touch target. */
@media (max-width: 767.98px) {
	.stbl-refund .btn,
	.stbl-refund .form-control,
	.stbl-refund .form-select {
		min-height: 40px;
	}
	.stbl-refund td {
		padding-top: 0.6rem;
		padding-bottom: 0.6rem;
	}
}
</style>
