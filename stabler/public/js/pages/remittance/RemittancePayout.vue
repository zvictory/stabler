<script setup>
/**
 * Payout — the counter screen that hands the cash over.
 *
 * Until this screen existed a registered transfer could only be released by an
 * administrator on the server: the cash came in through Register and there was
 * no way out of the app. Everything here is one desk transaction, in the order
 * the cashier actually performs it — find the transfer, read the receiver and
 * the exact amount back to them, take the code, confirm the desk, count the
 * cash, post, hand over a receipt.
 *
 * The pickup code:
 *   - lives in ONE ref, `pickupCode`, and leaves this component only as the
 *     `pickup_code` argument of `payoutTransfer`;
 *   - is never rendered back, never logged, never put in the route or in
 *     storage, and never interpolated into any message — not the confirm
 *     dialog, not a toast, not an error line;
 *   - is cleared on every exit: a refused attempt, a successful payout, a step
 *     back to the queue, a company switch, and unmount.
 *
 * Nothing about the lockout is counted here. "Attempts left" is read from
 * `code_state` on the detail endpoint, because the limit is a per-company
 * setting — a literal 5 in this file would be right until someone changed the
 * setting, and then it would quietly lie to the person at the counter. When the
 * detail read fails the screen shows the failures it does know about and no
 * remaining count at all: unknown and zero are not the same thing.
 *
 * Which buttons exist is decided by the server's `allowed_actions` on the row,
 * never by the role and never by the status. If the array does not carry the
 * action, the button is not drawn.
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { REMITTANCE_ACTIONS, remittanceApi } from "../../api/remittance.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import PostingPreview from "../../components/PostingPreview.vue";
import { formatDate, formatDateTime, todayIso } from "../../composables/date.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import { useLatestRequest } from "../../composables/useLatestRequest.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();
const latest = useLatestRequest();

// `payout_queue` takes a limit and no offset, so this screen searches rather
// than pages. When the answer fills the limit the list says so instead of
// pretending it is complete.
const QUEUE_LIMIT = 50;

const STEP = Object.freeze({ FIND: 1, VERIFY: 2, DESK: 3, CASH: 4 });

const search = ref("");
const rows = ref([]);
const loading = ref(false);
const queueError = ref("");

const step = ref(STEP.FIND);
const selected = ref(null);
const detail = ref(null);
const detailError = ref("");
const detailLoading = ref(false);

// The receiver's code. See the file docstring for every rule that applies to it.
const pickupCode = ref("");

const deskConfirmed = ref(false);
const cashConfirmed = ref(false);
// The three preconditions the Pay out button is gated on. `codeVerified` is the
// server's answer, never this screen's guess: a non-empty box used to be enough to
// reach the last step, so a wrong code was discovered after the cashier had already
// confirmed the count. Any edit to the box drops it back to false.
const codeVerified = ref(false);
const identityChecked = ref(false);
const verifying = ref(false);
const preview = ref(null);
const previewLoading = ref(false);
const previewError = ref("");

// The sentence above is only true because of this line. Without it, editing the
// box after a successful check — including WHILE the check is in flight, which the
// input allows unless it is disabled — leaves `codeVerified` true for a string the
// server has never seen, and the Pay out button satisfies its own gate on an
// unverified code. `payout_transfer` still re-verifies, so no cash moves; what is
// lost is the entire point of the gate: the cashier learns after counting, and
// burns an attempt against a lockout only a Finance Manager can clear.
watch(pickupCode, () => {
	codeVerified.value = false;
});
const postingDate = ref(todayIso());

const submitting = ref(false);
const actionError = ref("");
const unlockReason = ref("");
const unlocking = ref(false);

const receipt = ref(null);

// ── Derived ───────────────────────────────────────────────────────────────────

// One source for the role gate: the array the server stamped on the row. The
// detail response is preferred only because it is the fresher of the two reads.
const allowedActions = computed(
	() => detail.value?.allowed_actions || selected.value?.allowed_actions || []
);

const canPayout = computed(() => allowedActions.value.includes(REMITTANCE_ACTIONS.PAYOUT));
const canUnlock = computed(() =>
	allowedActions.value.includes(REMITTANCE_ACTIONS.UNLOCK_PICKUP_CODE)
);

const codeLocked = computed(() => {
	if (detail.value?.code_state) return Boolean(detail.value.code_state.locked);
	return Boolean(Number(selected.value?.code_locked || 0));
});

const failedAttempts = computed(() => {
	if (detail.value?.code_state) return Number(detail.value.code_state.attempts || 0);
	return Number(selected.value?.code_attempts || 0);
});

// `null` means "the allowance could not be read", which is a different sentence
// from "no attempts left" — the template must not collapse the two.
const attemptsLeft = computed(() => {
	const max = Number(detail.value?.code_state?.max_attempts || 0);
	if (max <= 0) return null;
	return Math.max(0, max - failedAttempts.value);
});

const receiveCurrency = computed(() => selected.value?.receive_currency || "");
const receiverAmount = computed(() => Number(selected.value?.receiver_amount || 0));

const truncated = computed(() => rows.value.length >= QUEUE_LIMIT);

/** A desk as the cashier names it: branch first, city as the qualifier. */
function desk(branch, city) {
	const parts = [branch, city].filter(Boolean);
	return parts.length ? parts.join(" · ") : "—";
}

// ── Loading ───────────────────────────────────────────────────────────────────

async function loadQueue() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	const isCurrent = latest.take();
	loading.value = true;
	queueError.value = "";
	try {
		const res = await remittanceApi.payoutQueue(
			activeCompany.value,
			search.value.trim() || null,
			QUEUE_LIMIT
		);
		if (!isCurrent()) return;
		rows.value = res || [];
	} catch (err) {
		if (!isCurrent()) return;
		rows.value = [];
		queueError.value = err?.message || t("Could not load the payout queue.");
	} finally {
		if (isCurrent()) loading.value = false;
	}
}

/**
 * The attempt allowance and the freshest action list, for the selected row.
 *
 * A failure here is not fatal: the queue row already carries the money, the
 * route and an `allowed_actions` array, so the screen keeps working and simply
 * declines to state a remaining-attempt count it cannot read.
 */
async function loadDetail() {
	const name = selected.value?.name;
	if (!name) return;
	detailLoading.value = true;
	detailError.value = "";
	try {
		const res = await remittanceApi.transferDetail(name);
		// The cashier may have moved on while this was in flight.
		if (selected.value?.name !== name) return;
		detail.value = res;
	} catch (err) {
		if (selected.value?.name !== name) return;
		detail.value = null;
		detailError.value = err?.message || t("Could not read this transfer's attempt allowance.");
	} finally {
		if (selected.value?.name === name) detailLoading.value = false;
	}
}

// ── Navigation ────────────────────────────────────────────────────────────────

function clearCode() {
	pickupCode.value = "";
	codeVerified.value = false;
}

function backToQueue() {
	clearCode();
	selected.value = null;
	detail.value = null;
	detailError.value = "";
	actionError.value = "";
	unlockReason.value = "";
	deskConfirmed.value = false;
	cashConfirmed.value = false;
	identityChecked.value = false;
	preview.value = null;
	previewError.value = "";
	postingDate.value = todayIso();
	step.value = STEP.FIND;
}

async function selectTransfer(row) {
	backToQueue();
	selected.value = row;
	step.value = STEP.VERIFY;
	await loadDetail();
}

/** The step indicator walks backwards only; forward moves have their own guard. */
function goStep(n) {
	if (n >= step.value) return;
	if (n === STEP.FIND) {
		backToQueue();
		return;
	}
	step.value = n;
}

async function toDeskStep() {
	if (!canPayout.value || codeLocked.value || !pickupCode.value || verifying.value) return;

	// The code is checked HERE, against the server, before the cashier is asked to
	// confirm a desk or count a note. It costs the same attempt the payout would
	// have cost — the counter and the lock live on the server and are re-read on
	// refusal rather than deduced from it.
	// The transfer this answer is about, captured before the await. Back is live
	// while the check runs, so by the time it resolves the cashier may be on a
	// different transfer — and an unguarded resolve would print THIS transfer's
	// "2 attempts left" against THAT one, whose counter never moved. Same guard as
	// `loadDetail()`, for the same reason.
	const name = selected.value.name;
	verifying.value = true;
	actionError.value = "";
	try {
		await remittanceApi.verifyPickupCode(name, pickupCode.value, crypto.randomUUID());
		if (selected.value?.name !== name) return;
		codeVerified.value = true;
		step.value = STEP.DESK;
	} catch (err) {
		if (selected.value?.name !== name) return;
		clearCode();
		actionError.value = err?.message || t("The pickup code was refused.");
		await loadDetail();
	} finally {
		verifying.value = false;
	}
}

/** The posting, fetched when the cashier reaches the step that hands cash over. */
async function toCashStep() {
	step.value = STEP.CASH;
	const name = selected.value?.name;
	if (!name) return;
	previewLoading.value = true;
	previewError.value = "";
	try {
		const rows = await remittanceApi.postingPreview(name, "Payout", postingDate.value || null);
		// The cashier may have moved on while this was in flight — same guard as
		// loadDetail, and on the assignment rather than only on the spinner. One
		// transfer's journal entry painted onto another's screen is the posting the
		// next control hands cash against.
		if (selected.value?.name !== name) return;
		preview.value = rows;
	} catch (err) {
		if (selected.value?.name !== name) return;
		// A preview that cannot be built is shown as such and never as an empty
		// table: an empty table reads as "this posts nothing".
		preview.value = null;
		previewError.value = err?.message || t("The posting could not be previewed.");
	} finally {
		if (selected.value?.name === name) previewLoading.value = false;
	}
}

function printReceipt() {
	window.print();
}

// ── Actions ───────────────────────────────────────────────────────────────────

async function unlock() {
	if (!canUnlock.value || !selected.value) return;
	const ok = await confirm({
		title: t("Unlock this pickup code?"),
		body: t(
			"Transfer {reference} becomes payable again and the attempt counter goes back to zero. The unlock is recorded against your name.",
			{
				reference: selected.value.name,
			}
		),
		confirmLabel: t("Unlock"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	unlocking.value = true;
	actionError.value = "";
	try {
		await remittanceApi.unlockPickupCode(selected.value.name, unlockReason.value.trim() || null);
		unlockReason.value = "";
		toast.success(t("Pickup code unlocked."));
		await loadDetail();
		await loadQueue();
	} catch (err) {
		actionError.value = err?.message || t("Could not unlock the pickup code.");
	} finally {
		unlocking.value = false;
	}
}

async function payout() {
	if (!selected.value || !canPayout.value) return;
	if (!pickupCode.value || !codeVerified.value) return;
	if (!deskConfirmed.value || !identityChecked.value || !cashConfirmed.value) return;

	// The dialog names the money, the receiver and the transfer. It does not
	// name the code, and nothing on this path ever will.
	const ok = await confirm({
		title: t("Hand over the cash?"),
		body: t(
			"Pay {amount} to {receiver} against {reference}. This posts the payout entry and closes the obligation.",
			{
				amount: formatMoney(receiverAmount.value, receiveCurrency.value),
				receiver: selected.value.receiver_name || t("the receiver"),
				reference: selected.value.name,
			}
		),
		confirmLabel: t("Pay out"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;

	submitting.value = true;
	actionError.value = "";
	// A NEW key for every attempt. The key is the server's idempotency key: reusing
	// the key of a refused attempt would send the same key with a different code,
	// which is a conflict, not a retry.
	const requestId = crypto.randomUUID();
	try {
		const res = await remittanceApi.payoutTransfer(
			selected.value.name,
			pickupCode.value,
			requestId,
			postingDate.value || null
		);
		clearCode();
		receipt.value = {
			name: selected.value.name,
			receiver_name: selected.value.receiver_name,
			sender_name: selected.value.sender_name,
			desk: desk(selected.value.destination_branch, selected.value.destination_city),
			currency: receiveCurrency.value,
			posting_date: postingDate.value,
			// Server-stated, not the number this screen was holding.
			paid: Number(res?.receiver_amount ?? receiverAmount.value),
			journal_entry: res?.payout_journal_entry || "",
			operational_status: res?.operational_status || "",
			accounting_status: res?.accounting_status || "",
		};
		toast.success(t("Paid out."));
		await loadQueue();
	} catch (err) {
		// Whatever went wrong, the code in the box is spent: a refused code must be
		// retyped, never resubmitted by a second click.
		clearCode();
		actionError.value = err?.message || t("The payout was refused.");
		cashConfirmed.value = false;
		step.value = STEP.VERIFY;
		// The attempt counter and the lock moved on the server. Re-read them rather
		// than deducing them from the refusal.
		await loadDetail();
	} finally {
		submitting.value = false;
	}
}

function payoutAnother() {
	receipt.value = null;
	backToQueue();
	loadQueue();
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

watch(activeCompany, () => {
	// A transfer belongs to the company it was registered in. Switching companies
	// mid-payout must drop the selection and the code with it.
	latest.invalidate();
	receipt.value = null;
	backToQueue();
	loadQueue();
});

onBeforeUnmount(clearCode);

onMounted(loadQueue);
</script>

<template>
	<div v-if="!activeCompany" class="alert alert-warning">
		{{ t("Select a company to pay out a transfer.") }}
	</div>

	<!-- ── Receipt ──────────────────────────────────────────────────────────
	     Shown instead of the wizard, never beside it. -->
	<div v-else-if="receipt" class="row justify-content-center">
		<div class="col-lg-6">
			<div class="card">
				<div class="card-body">
					<div class="text-center mb-3">
						<span class="avatar avatar-lg bg-green-lt mb-2">
							<i class="ti ti-cash-banknote fs-1"></i>
						</span>
						<h3 class="card-title mb-1">{{ t("Paid out") }}</h3>
						<div class="text-secondary font-monospace">{{ receipt.name }}</div>
					</div>

					<div class="text-center mb-3">
						<div class="text-secondary small">{{ t("Handed to") }}</div>
						<div class="fs-3 fw-semibold">{{ receipt.receiver_name || "—" }}</div>
						<div class="display-6 font-monospace fw-bold text-green">
							{{ formatMoney(receipt.paid, receipt.currency) }}
						</div>
					</div>

					<dl class="row mb-0 g-1 border-top pt-3">
						<dt class="col-6 text-secondary small">{{ t("Sender") }}</dt>
						<dd class="col-6 text-end small">{{ receipt.sender_name || "—" }}</dd>
						<dt class="col-6 text-secondary small">{{ t("Payout desk") }}</dt>
						<dd class="col-6 text-end small">{{ receipt.desk }}</dd>
						<dt class="col-6 text-secondary small">{{ t("Posting date") }}</dt>
						<dd class="col-6 text-end small font-monospace">
							{{ formatDate(receipt.posting_date) }}
						</dd>
						<dt v-if="receipt.journal_entry" class="col-6 text-secondary small">
							{{ t("Journal Entry") }}
						</dt>
						<dd v-if="receipt.journal_entry" class="col-6 text-end small font-monospace">
							{{ receipt.journal_entry }}
						</dd>
						<dt class="col-6 text-secondary small">{{ t("Status") }}</dt>
						<dd class="col-6 text-end small">
							{{ receipt.operational_status }}
							<span v-if="receipt.accounting_status" class="text-secondary">
								/ {{ receipt.accounting_status }}
							</span>
						</dd>
					</dl>

					<div class="d-flex gap-2 mt-4">
						<button
							type="button"
							class="btn btn-outline-secondary stbl-touch flex-fill"
							@click="printReceipt"
						>
							<i class="ti ti-printer me-1"></i>{{ t("Print") }}
						</button>
						<button
							type="button"
							class="btn btn-primary stbl-touch flex-fill"
							@click="payoutAnother"
						>
							<i class="ti ti-arrow-right me-1"></i>{{ t("Pay out another") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>

	<template v-else>
		<ul class="steps steps-counter mb-3">
			<li
				class="step-item"
				:class="{ active: step === STEP.FIND }"
				style="cursor: pointer"
				@click="goStep(STEP.FIND)"
			>
				{{ t("Find") }}
			</li>
			<li
				class="step-item"
				:class="{ active: step === STEP.VERIFY }"
				style="cursor: pointer"
				@click="goStep(STEP.VERIFY)"
			>
				{{ t("Verify code") }}
			</li>
			<li
				class="step-item"
				:class="{ active: step === STEP.DESK }"
				style="cursor: pointer"
				@click="goStep(STEP.DESK)"
			>
				{{ t("Payout desk") }}
			</li>
			<li class="step-item" :class="{ active: step === STEP.CASH }">
				{{ t("Cash") }}
			</li>
		</ul>

		<!-- ── Step 1: find the transfer ─────────────────────────────────── -->
		<div v-if="step === STEP.FIND" class="card">
			<ListToolbar
				v-model="search"
				:placeholder="t('Remittance id, reference, sender or receiver… ⌘K')"
				:count="rows.length"
				search-width="320px"
				@search="loadQueue()"
			/>

			<div v-if="queueError" class="card-body">
				<div class="alert alert-danger m-0">{{ queueError }}</div>
			</div>

			<template v-else>
				<div class="table-responsive">
					<table class="table table-vcenter card-table table-hover stbl-payout-table">
						<thead>
							<tr>
								<th>{{ t("Remittance id") }}</th>
								<th>{{ t("Sender → Receiver") }}</th>
								<th class="d-none d-md-table-cell">{{ t("Route") }}</th>
								<th class="text-end">{{ t("Receiver gets") }}</th>
								<th class="d-none d-lg-table-cell">{{ t("Registered") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="5" :cols="5" />
						<tbody v-else-if="rows.length">
							<tr
								v-for="row in rows"
								:key="row.name"
								style="cursor: pointer"
								@click="selectTransfer(row)"
							>
								<td>
									<div class="font-monospace">{{ row.name }}</div>
									<!-- A lock is not a document status — the queue is Registered +
									     Posted by construction — so it is a lock chip, not a
									     StatusBadge. -->
									<span v-if="Number(row.code_locked)" class="badge bg-red-lt mt-1">
										<i class="ti ti-lock me-1"></i>{{ t("Code locked") }}
									</span>
								</td>
								<td>
									<div>{{ row.sender_name || "—" }}</div>
									<div class="text-secondary small">{{ row.receiver_name || "—" }}</div>
								</td>
								<td class="d-none d-md-table-cell small">
									{{ desk(row.origin_branch, row.origin_city) }}
									<i class="ti ti-arrow-right mx-1 text-secondary"></i>
									{{ desk(row.destination_branch, row.destination_city) }}
								</td>
								<td class="text-end font-monospace fw-semibold">
									{{ formatMoney(row.receiver_amount, row.receive_currency) }}
								</td>
								<td class="d-none d-lg-table-cell text-secondary small">
									{{ formatDateTime(row.registered_at) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<EmptyState
					v-if="!loading && !rows.length && search.trim()"
					icon="ti-search"
					:title="t('No transfer matches that search')"
					:subtitle="t('Search by remittance id, client reference, sender or receiver name.')"
					compact
				/>
				<EmptyState
					v-else-if="!loading && !rows.length"
					icon="ti-cash-banknote"
					:title="t('Nothing is waiting for payout')"
					:subtitle="t('Registered transfers whose obligation has posted appear here.')"
					compact
				/>

				<div v-if="truncated" class="card-footer text-secondary small">
					{{
						t("Showing the first {count} — narrow the search to see the rest.", {
							count: QUEUE_LIMIT,
						})
					}}
				</div>
			</template>
		</div>

		<!-- ── Steps 2–4 ─────────────────────────────────────────────────── -->
		<div v-else-if="selected" class="row g-3">
			<!-- Who is being paid, and exactly what. Repeated on every step so the
			     cashier never confirms cash against a number they last saw two
			     screens ago. -->
			<div class="col-lg-5">
				<div class="card">
					<div class="card-body">
						<div class="text-secondary small">{{ t("Remittance id") }}</div>
						<div class="font-monospace mb-3">{{ selected.name }}</div>

						<div class="text-secondary small">{{ t("Receiver") }}</div>
						<div class="fs-3 fw-semibold mb-3">{{ selected.receiver_name || "—" }}</div>

						<div class="text-secondary small">{{ t("Receiver gets") }}</div>
						<div class="display-6 font-monospace fw-bold mb-3">
							{{ formatMoney(receiverAmount, receiveCurrency) }}
						</div>

						<dl class="row mb-0 g-1 border-top pt-3">
							<dt class="col-5 text-secondary small">{{ t("Sender") }}</dt>
							<dd class="col-7 text-end small">{{ selected.sender_name || "—" }}</dd>
							<dt class="col-5 text-secondary small">{{ t("From") }}</dt>
							<dd class="col-7 text-end small">
								{{ desk(selected.origin_branch, selected.origin_city) }}
							</dd>
							<dt class="col-5 text-secondary small">{{ t("To") }}</dt>
							<dd class="col-7 text-end small">
								{{ desk(selected.destination_branch, selected.destination_city) }}
							</dd>
							<dt class="col-5 text-secondary small">{{ t("Registered") }}</dt>
							<dd class="col-7 text-end small">{{ formatDateTime(selected.registered_at) }}</dd>
						</dl>
					</div>
				</div>
			</div>

			<div class="col-lg-7">
				<div class="card">
					<div class="card-body">
						<div v-if="actionError" class="alert alert-danger" role="alert">{{ actionError }}</div>
						<div v-if="detailError" class="alert alert-warning">
							{{ detailError }}
						</div>

						<!-- ── Step 2: the code ──────────────────────────────── -->
						<form v-if="step === STEP.VERIFY" autocomplete="off" @submit.prevent="toDeskStep">
							<h3 class="card-title">{{ t("Pickup code") }}</h3>

							<div v-if="codeLocked" class="alert alert-danger">
								<div class="fw-semibold">{{ t("This pickup code is locked.") }}</div>
								<div>
									{{
										t(
											"Too many wrong codes were entered. Ask a manager to unlock it — there is no timer."
										)
									}}
								</div>
							</div>

							<template v-else>
								<label class="form-label" for="stbl-pickup-code">
									{{ t("Code given to the receiver") }}
								</label>
								<!-- One input, masked, never echoed. No maxlength and no pattern:
								     the code format is a server constant, and a client-side rule
								     that disagrees with it would burn a real attempt on a valid
								     code. The value is sent exactly as typed — uppercasing it for
								     display would show one code and submit another. -->
								<input
									id="stbl-pickup-code"
									v-model="pickupCode"
									type="password"
									class="form-control form-control-lg font-monospace stbl-touch"
									:disabled="verifying"
									autocomplete="off"
									autocapitalize="characters"
									autocorrect="off"
									spellcheck="false"
									:aria-invalid="Boolean(actionError)"
									aria-describedby="stbl-pickup-code-hint"
								/>
								<div id="stbl-pickup-code-hint" class="form-text" aria-live="polite">
									<template v-if="attemptsLeft !== null">
										{{
											t("{count} attempt(s) left before this code locks.", { count: attemptsLeft })
										}}
									</template>
									<template v-else-if="failedAttempts > 0">
										{{
											t("{count} failed attempt(s) so far. The lockout limit could not be read.", {
												count: failedAttempts,
											})
										}}
									</template>
									<template v-else>
										{{ t("A wrong code costs an attempt and eventually locks the transfer.") }}
									</template>
								</div>
							</template>

							<!-- Drawn from `allowed_actions`, so a cashier never sees it and a
							     manager sees it only while the code is actually locked. -->
							<div v-if="canUnlock" class="mt-3 border-top pt-3">
								<label class="form-label" for="stbl-unlock-reason">
									{{ t("Reason for unlocking (recorded)") }}
								</label>
								<input
									id="stbl-unlock-reason"
									v-model="unlockReason"
									type="text"
									class="form-control stbl-touch"
								/>
								<button
									type="button"
									class="btn btn-outline-secondary stbl-touch mt-2"
									:disabled="unlocking"
									@click="unlock"
								>
									<span v-if="unlocking" class="spinner-border spinner-border-sm me-1"></span>
									<i v-else class="ti ti-lock-open me-1"></i>{{ t("Unlock pickup code") }}
								</button>
							</div>

							<div v-if="!canPayout && !codeLocked" class="alert alert-warning mt-3">
								{{ t("You cannot pay out this transfer.") }}
							</div>

							<div class="d-flex justify-content-between gap-2 mt-4">
								<button
									type="button"
									class="btn btn-outline-secondary stbl-touch"
									@click="goStep(STEP.FIND)"
								>
									<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
								</button>
								<button
									type="submit"
									class="btn btn-primary stbl-touch"
									:disabled="!canPayout || codeLocked || !pickupCode || detailLoading || verifying"
								>
									<span v-if="verifying" class="spinner-border spinner-border-sm me-1"></span>
									{{ t("Check the code") }}
									<i v-if="!verifying" class="ti ti-arrow-right ms-1"></i>
								</button>
							</div>
						</form>

						<!-- ── Step 3: the desk ──────────────────────────────── -->
						<div v-else-if="step === STEP.DESK">
							<h3 class="card-title">{{ t("Payout desk") }}</h3>
							<div class="mb-3">
								<div class="text-secondary small">{{ t("This transfer pays out at") }}</div>
								<div class="fs-3 fw-semibold">
									{{ desk(selected.destination_branch, selected.destination_city) }}
								</div>
							</div>

							<!-- The cash and obligation accounts are resolved server-side from
							     Remittance Settings for this branch, and no read endpoint
							     exposes them. Naming an account here would be a guess printed
							     as a fact, so the screen names the branch and says where the
							     accounts come from. -->
							<div class="alert alert-info">
								{{
									t(
										"The cash and obligation accounts for this payout come from Remittance Settings for this branch. They are applied by the server when the entry posts."
									)
								}}
							</div>

							<label class="form-check stbl-touch">
								<input v-model="deskConfirmed" class="form-check-input" type="checkbox" />
								<span class="form-check-label">
									{{ t("I am paying out at this desk.") }}
								</span>
							</label>

							<!-- The code proves the receiver knows the secret; it does not prove
							     they are the person the sender named. A code read off a
							     forwarded message is still a correct code, so identity is a
							     separate confirmation and not a rewording of the one above. -->
							<label class="form-check stbl-touch">
								<input v-model="identityChecked" class="form-check-input" type="checkbox" />
								<span class="form-check-label">
									{{
										t("I have checked {receiver}'s identity document.", {
											receiver: selected.receiver_name || t("the receiver"),
										})
									}}
								</span>
							</label>

							<div class="d-flex justify-content-between gap-2 mt-4">
								<button
									type="button"
									class="btn btn-outline-secondary stbl-touch"
									@click="goStep(STEP.VERIFY)"
								>
									<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
								</button>
								<button
									type="button"
									class="btn btn-primary stbl-touch"
									:disabled="!deskConfirmed || !identityChecked"
									@click="toCashStep"
								>
									{{ t("Next") }}<i class="ti ti-arrow-right ms-1"></i>
								</button>
							</div>
						</div>

						<!-- ── Step 4: the cash ──────────────────────────────── -->
						<div v-else-if="step === STEP.CASH">
							<h3 class="card-title">{{ t("Count the cash") }}</h3>

							<div class="mb-3" style="max-width: 220px">
								<label class="form-label">{{ t("Posting date") }}</label>
								<DateInput v-model="postingDate" />
							</div>

							<!-- Was a two-row Effect/Amount table with no debit or credit column
							     and no total: the balance was implied by printing the same figure
							     twice, and the commission legs were left out entirely because
							     this screen had no honest source for them. It has one now. -->
							<PostingPreview
								:rows="preview?.rows || []"
								:base-currency="preview?.base_currency || ''"
								:total-debit="preview?.total_debit || 0"
								:total-credit="preview?.total_credit || 0"
								:balanced="Boolean(preview?.balanced)"
								:loading="previewLoading"
								:error="previewError"
							/>
							<label class="form-check stbl-touch">
								<input v-model="cashConfirmed" class="form-check-input" type="checkbox" />
								<span class="form-check-label">
									{{
										t("I have counted {amount} and am handing it to {receiver}.", {
											amount: formatMoney(receiverAmount, receiveCurrency),
											receiver: selected.receiver_name || t("the receiver"),
										})
									}}
								</span>
							</label>

							<div class="d-flex justify-content-between gap-2 mt-4">
								<button
									type="button"
									class="btn btn-outline-secondary stbl-touch"
									:disabled="submitting"
									@click="goStep(STEP.DESK)"
								>
									<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
								</button>
								<button
									type="button"
									class="btn btn-primary stbl-touch"
									:disabled="
										submitting ||
										!canPayout ||
										!codeVerified ||
										!identityChecked ||
										!cashConfirmed ||
										!pickupCode
									"
									@click="payout"
								>
									<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
									<i v-else class="ti ti-cash-banknote me-1"></i>{{ t("Pay out") }}
								</button>
							</div>
						</div>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>

<style scoped>
/* `.stbl-touch` itself is in stabler.css — it was defined here, scoped, so the
   same class on any other remittance page rendered as inert markup. What stays
   here is the one rule that really is this component's: the queue rows. */
@media (max-width: 767.98px) {
	.stbl-payout-table tbody td {
		min-height: 40px;
	}
}
</style>
