<script setup>
/**
 * Remittance Operations — the Transfer V1 landing screen.
 *
 * Two regions, and they answer different questions:
 *
 *   Scorecards  — what happened today and what is still owed, per currency.
 *                 USD, EUR and USDT are never added together (ADR-011): every
 *                 money figure the server sends is a list of per-currency rows
 *                 and this screen renders them as separate lines. There is no
 *                 grand total here and there must never be one.
 *
 *   Queues      — the six work queues, one tile each, and the rows of whichever
 *                 tile is selected. Every button in the "Next action" column is
 *                 drawn from the row's own `allowed_actions` array. This screen
 *                 never reads a role and never infers an action from a status:
 *                 the server decides which buttons exist, and a screen that
 *                 derived them independently would offer buttons the endpoint
 *                 refuses.
 *
 * Two things this screen deliberately refuses to invent:
 *
 *   1. An expiry. Nothing in the app writes `expires_at` yet, so the two expiry
 *      queues answer `policy_configured: false`. That is NOT "zero transfers are
 *      expiring" — it is "the question cannot be asked yet", and the tile shows
 *      an em dash with the reason rather than a 0 somebody would act on.
 *   2. A pickup code. No field, badge, title attribute, log line, URL or storage
 *      key on this page carries the code or its digest. `code_locked` is shown
 *      because a lockout is a fact about the transfer, not the secret itself.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { remittanceApi, REMITTANCE_ACTIONS, REMITTANCE_QUEUES } from "../../api/remittance.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { routeLabel } from "../../composables/remittanceRoute.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useLatestRequest } from "../../composables/useLatestRequest.js";
import KpiCard from "../../components/KpiCard.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import Pagination from "../../components/Pagination.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const toast = useToast();

// Out-of-order guards: the summary and the queue are two independent requests
// and a company switch retires both.
const summaryTicket = useLatestRequest();
const queueTicket = useLatestRequest();

// Server order (`remittance_queries.QUEUES`), which is also the order a desk
// works them.
const QUEUE_ORDER = [
	REMITTANCE_QUEUES.READY_FOR_PAYOUT,
	REMITTANCE_QUEUES.EXPIRING_12H,
	REMITTANCE_QUEUES.EXPIRED_REFUND_REQUIRED,
	REMITTANCE_QUEUES.REFUND_AWAITING_APPROVAL,
	REMITTANCE_QUEUES.LOCKED_PICKUP_CODE,
	REMITTANCE_QUEUES.ACCOUNTING_EXCEPTION,
];

const queueMeta = computed(() => ({
	[REMITTANCE_QUEUES.READY_FOR_PAYOUT]: {
		title: t("Ready for payout"),
		note: t("Obligation posted, code unlocked, no refund in flight"),
		icon: "ti-cash-banknote",
		tone: "green",
	},
	[REMITTANCE_QUEUES.EXPIRING_12H]: {
		title: t("Expiring within 12 hours"),
		note: t("Pickup deadline falls inside the next 12 hours"),
		icon: "ti-hourglass-low",
		tone: "orange",
	},
	[REMITTANCE_QUEUES.EXPIRED_REFUND_REQUIRED]: {
		title: t("Expired / refund required"),
		note: t("Pickup deadline has passed and the money is still owed"),
		icon: "ti-clock-exclamation",
		tone: "red",
	},
	// Two states, one queue, because both are unfinished refund work and an
	// approved one appeared in no queue at all before this. The row's own
	// `allowed_actions` is what tells them apart — "Approve refund" on one,
	// "Complete refund" on the other — and the refund badge on the row names the
	// state outright.
	[REMITTANCE_QUEUES.REFUND_AWAITING_APPROVAL]: {
		title: t("Refund open"),
		note: t("Requested and awaiting a decision, or approved and awaiting cash"),
		icon: "ti-gavel",
		tone: "yellow",
	},
	[REMITTANCE_QUEUES.LOCKED_PICKUP_CODE]: {
		title: t("Locked pickup code"),
		note: t("Too many wrong attempts — only a manager can reopen it"),
		icon: "ti-lock",
		tone: "purple",
	},
	[REMITTANCE_QUEUES.ACCOUNTING_EXCEPTION]: {
		title: t("Accounting exception"),
		note: t("The master record and its journal entries disagree"),
		icon: "ti-alert-triangle",
		tone: "red",
	},
}));

// Labels for the identifiers `_remittance_actions.ACTIONS` hands back. The wire
// value is never rendered raw — an untranslated "unlock_pickup_code" on a button
// is not a label.
const actionLabels = computed(() => ({
	[REMITTANCE_ACTIONS.PAYOUT]: t("Pay out"),
	[REMITTANCE_ACTIONS.UNLOCK_PICKUP_CODE]: t("Unlock code"),
	[REMITTANCE_ACTIONS.REQUEST_REFUND]: t("Request refund"),
	[REMITTANCE_ACTIONS.APPROVE_REFUND]: t("Approve refund"),
	[REMITTANCE_ACTIONS.REJECT_REFUND]: t("Reject refund"),
	[REMITTANCE_ACTIONS.COMPLETE_REFUND]: t("Complete refund"),
}));

// Where each action is actually performed. Payout has its own cashier screen;
// the manager-side actions live on the transfer's detail page. Resolved through
// `router.hasRoute` at click time rather than assumed, so a queue built before
// its destination screen lands says so instead of pushing into a blank route.
const ACTION_ROUTES = Object.freeze({
	[REMITTANCE_ACTIONS.PAYOUT]: "remittance-payout",
	[REMITTANCE_ACTIONS.UNLOCK_PICKUP_CODE]: "remittance-transfer",
	[REMITTANCE_ACTIONS.REQUEST_REFUND]: "remittance-transfer",
	[REMITTANCE_ACTIONS.APPROVE_REFUND]: "remittance-transfer",
	[REMITTANCE_ACTIONS.REJECT_REFUND]: "remittance-transfer",
	[REMITTANCE_ACTIONS.COMPLETE_REFUND]: "remittance-transfer",
});

// The three hard currencies the module carries (ADR-003: no local currency ever
// enters remittance). The filter narrows the send leg, which is the leg the
// cashier took the cash in.
const currencyOptions = computed(() => [
	{ value: "", label: t("All currencies") },
	{ value: "USD", label: t("USD") },
	{ value: "EUR", label: t("EUR") },
	{ value: "USDT", label: t("USDT") },
]);

const currencyFilter = ref("");

// The desk filter narrows to one cash desk on EITHER leg, which is the server's
// rule and not this screen's: a desk pays out what arrives at it and counts cash
// back out on refunds of what it registered, so filtering one leg would hide half
// of its own work.
const deskFilter = ref("");
const desks = ref([]);

const deskOptions = computed(() => [
	{ value: "", label: t("All cash desks") },
	...desks.value.map((desk) => ({
		value: desk.branch,
		label: desk.city ? `${desk.city} · ${desk.branch}` : desk.branch,
	})),
]);

const filtersActive = computed(() => Boolean(currencyFilter.value || deskFilter.value));

const summary = ref(null);
const summaryLoading = ref(false);
const summaryError = ref("");

const activeQueue = ref(REMITTANCE_QUEUES.READY_FOR_PAYOUT);
const queue = ref({ rows: [], total: 0, policyConfigured: true });
const queueLoading = ref(false);
const queueError = ref("");
const limitStart = ref(0);
const pageLength = ref(25);

const lang = computed(() => user.value?.language || "en");

// ------------------------------------------------------------------ loading --
async function loadSummary() {
	if (!activeCompany.value) return;
	const isCurrent = summaryTicket.take();
	summaryLoading.value = true;
	summaryError.value = "";
	try {
		const res = await remittanceApi.operationsSummary(
			activeCompany.value,
			currencyFilter.value || null,
			deskFilter.value || null
		);
		if (!isCurrent()) return;
		summary.value = res || null;
	} catch (err) {
		if (!isCurrent()) return;
		summary.value = null;
		summaryError.value = err?.message || t("Failed to load the operations summary.");
	} finally {
		if (isCurrent()) summaryLoading.value = false;
	}
}

async function loadQueue() {
	if (!activeCompany.value) return;
	const isCurrent = queueTicket.take();
	queueLoading.value = true;
	queueError.value = "";
	try {
		const res = await remittanceApi.workQueue(
			activeCompany.value,
			activeQueue.value,
			pageLength.value,
			limitStart.value,
			currencyFilter.value || null,
			deskFilter.value || null
		);
		if (!isCurrent()) return;
		queue.value = {
			rows: res?.rows || [],
			total: res?.total || 0,
			// Absent means "the server did not raise the question", which only the
			// two expiry queues ever do. Default to true so a normal queue is never
			// mislabelled as unconfigured.
			policyConfigured: res?.policy_configured !== false,
		};
	} catch (err) {
		if (!isCurrent()) return;
		queue.value = { rows: [], total: 0, policyConfigured: true };
		queueError.value = err?.message || t("Failed to load the queue.");
	} finally {
		if (isCurrent()) queueLoading.value = false;
	}
}

function reload() {
	limitStart.value = 0;
	loadSummary();
	loadQueue();
}

// Both filters reach both endpoints, so both regions reload. The queue used to
// be left alone here because `work_queue` took no such argument, which meant its
// rows sat unchanged beside a narrowed scorecard — a filter that appears to have
// silently failed. Reset paging: page 3 of the unfiltered queue is rarely page 3
// of the filtered one.
watch([currencyFilter, deskFilter], reload);

function clearFilters() {
	if (!filtersActive.value) return;
	currencyFilter.value = "";
	deskFilter.value = "";
}

async function loadDesks() {
	if (!activeCompany.value) {
		desks.value = [];
		return;
	}
	try {
		const rows = await remittanceApi.cashDesks(activeCompany.value);
		// One entry per branch: the settings table carries a row per desk AND
		// currency, so a desk with three cash accounts would otherwise appear three
		// times in the filter.
		const seen = new Map();
		for (const row of Array.isArray(rows) ? rows : []) {
			if (!row?.branch || seen.has(row.branch)) continue;
			seen.set(row.branch, { branch: row.branch, city: row.city || "" });
		}
		desks.value = [...seen.values()];
	} catch {
		// A desk list that failed to load is a missing filter, not a broken screen:
		// the queues below are the point and they answer without it.
		desks.value = [];
	}
}

function selectQueue(name) {
	if (activeQueue.value === name) return;
	activeQueue.value = name;
	limitStart.value = 0;
	loadQueue();
}

function setOffset(value) {
	limitStart.value = value;
	loadQueue();
}

function setPageLength(value) {
	pageLength.value = value;
	limitStart.value = 0;
	loadQueue();
}

// --------------------------------------------------------------- scorecards --
// One formatted line per currency, largest first: KpiCard renders lines[0] as
// the hero value, so leaving the server's alphabetical order would make whichever
// currency sorts first the headline number rather than the biggest exposure.
function currencyLines(rows) {
	if (!rows || !rows.length) return null;
	return [...rows]
		.sort((a, b) => Number(b.amount || 0) - Number(a.amount || 0))
		.map((row) => formatMoney(row.amount, row.currency, lang.value));
}

const scorecards = computed(() => summary.value?.scorecards || null);

const registeredTodayLines = computed(() =>
	currencyLines(scorecards.value?.registered_today?.rows)
);
const inTransitLines = computed(() =>
	currencyLines(scorecards.value?.in_transit_ready_payout?.rows)
);
const paidOutTodayLines = computed(() => currencyLines(scorecards.value?.paid_out_today?.rows));
// Two different shapes under one heading, kept apart on purpose: `earned_today`
// is a flow (commission that moved to income when a transfer was paid out today)
// and `deferred_open` is a balance (commission sitting against obligations
// nobody has collected). Merging them double-counts the desk's own revenue.
const commissionEarnedLines = computed(() =>
	currencyLines(scorecards.value?.commission?.earned_today)
);
const commissionDeferredLines = computed(() =>
	currencyLines(scorecards.value?.commission?.deferred_open)
);

function countBadge(count) {
	return [{ label: t("transfers"), value: count ?? 0, tone: "azure" }];
}

// ------------------------------------------------------------- queue tiles --
function queueState(name) {
	return summary.value?.queues?.[name] || null;
}

function queueConfigured(name) {
	const state = queueState(name);
	return !state || state.policy_configured !== false;
}

function queueCount(name) {
	// An em dash, never a 0: an unmeasurable queue and an empty one are opposite
	// claims and only one of them is true today.
	if (!queueConfigured(name)) return "—";
	return queueState(name)?.count ?? 0;
}

function queueHint(name) {
	if (!queueConfigured(name)) return t("Pickup expiry policy is not configured yet");
	return queueMeta.value[name]?.note || "";
}

// ---------------------------------------------------------------- row cells --
// `Tashkent · TAS-C → Istanbul · IST-1`, from the shared composable rather than
// from a second spelling here. This column used to stack `branch → branch` over
// `city → city` on two lines while the quote panel wrote the one-line form, and
// the design of record (PROMPT_remittance_design_v2.txt:141) names only the
// one-line form.
function rowRoute(row) {
	return routeLabel(
		{ branch: row.origin_branch, city: row.origin_city },
		{ branch: row.destination_branch, city: row.destination_city }
	);
}

// Age from `registered_at`, which is real data on every row. Nothing here is
// derived from `expires_at` — that column is rendered only when the server sent
// a value for it.
function ageLabel(value) {
	if (!value) return "";
	const raw = String(value).trim();
	// Date-only strings would parse as UTC midnight and shift the age by the
	// timezone offset. `registered_at` is a Datetime, so require the time part
	// rather than guessing one.
	if (raw.length < 16) return "";
	const stamp = new Date(raw.replace(" ", "T")).getTime();
	if (!Number.isFinite(stamp)) return "";
	const hours = Math.floor((Date.now() - stamp) / 3600000);
	if (hours < 0) return "";
	if (hours < 1) return t("<1h");
	if (hours < 48) return t("{count}h", { count: hours });
	return t("{count}d", { count: Math.floor(hours / 24) });
}

// The row's own array is the only gate. Not the role, not the status.
function rowActions(row) {
	return row?.allowed_actions || [];
}

function openAction(row, action) {
	const target = ACTION_ROUTES[action];
	if (!target || !router.hasRoute(target)) {
		toast.info(t("That screen is not available yet."));
		return;
	}
	router.push({ name: target, params: { name: row.name } });
}

// A company switch retires both in-flight requests and starts over: the previous
// company's rows must never be left on screen beside the new company's header.
watch(activeCompany, () => {
	summaryTicket.invalidate();
	queueTicket.invalidate();
	summary.value = null;
	queue.value = { rows: [], total: 0, policyConfigured: true };
	// The desks belong to the company that just went away, and so does the pick
	// made from them — carrying either over would filter the new company's queues
	// by a branch it does not have and show an honest, wrong, empty screen.
	desks.value = [];
	deskFilter.value = "";
	loadDesks();
	reload();
});

onMounted(() => {
	loadDesks();
	reload();
});
</script>

<template>
	<div class="card stbl-remit-ops">
		<!-- Region 1: scorecards -->
		<div class="d-flex align-items-center gap-2 flex-wrap py-2 px-3 border-bottom bg-light">
			<div class="subheader mb-0">{{ t("Scorecards") }}</div>
			<Select v-model="currencyFilter" size="sm" :options="currencyOptions" style="width: 160px" />
			<Select v-model="deskFilter" size="sm" :options="deskOptions" style="width: 200px" />
			<button
				v-if="filtersActive"
				type="button"
				class="btn btn-sm btn-ghost-secondary"
				@click="clearFilters"
			>
				<i class="ti ti-filter-off me-1"></i>{{ t("Clear filters") }}
			</button>
			<div class="ms-auto d-flex align-items-center gap-2">
				<span v-if="summary?.as_of" class="text-secondary small font-monospace">
					{{ formatDateTime(summary.as_of) }}
				</span>
				<button
					type="button"
					class="btn btn-sm btn-outline-secondary"
					:disabled="summaryLoading || queueLoading"
					@click="reload"
				>
					<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
				</button>
			</div>
		</div>

		<div class="text-secondary small px-3 py-2 border-bottom">
			{{
				t(
					"Amounts are listed per currency and never summed. Both filters narrow the scorecards, the queue counts and the queue rows together."
				)
			}}
		</div>

		<div v-if="!activeCompany" class="card-body">
			<EmptyState
				icon="ti-building-bank"
				accent-icon="ti-arrow-up"
				tone="secondary"
				:title="t('Select a company')"
				:subtitle="t('Remittance operations are scoped to one company at a time.')"
			/>
		</div>

		<template v-else>
			<div v-if="summaryError" class="card-body">
				<div class="alert alert-danger m-0">{{ summaryError }}</div>
			</div>

			<div v-else class="p-3 border-bottom">
				<div class="row row-cards">
					<div class="col-sm-6 col-lg">
						<KpiCard
							:label="t('Registered today')"
							:lines="registeredTodayLines"
							:badges="countBadge(scorecards?.registered_today?.count)"
							icon="ti-file-plus"
							tone="primary"
							:loading="summaryLoading"
						/>
					</div>
					<div class="col-sm-6 col-lg">
						<KpiCard
							:label="t('In transit / ready for payout')"
							:lines="inTransitLines"
							:badges="countBadge(scorecards?.in_transit_ready_payout?.count)"
							icon="ti-transfer-in"
							tone="azure"
							:loading="summaryLoading"
						/>
					</div>
					<div class="col-sm-6 col-lg">
						<KpiCard
							:label="t('Paid out today')"
							:lines="paidOutTodayLines"
							:badges="countBadge(scorecards?.paid_out_today?.count)"
							icon="ti-cash-banknote"
							tone="green"
							:loading="summaryLoading"
						/>
					</div>
					<div class="col-sm-6 col-lg">
						<KpiCard
							:label="t('Commission earned today')"
							:lines="commissionEarnedLines"
							icon="ti-percentage"
							tone="teal"
							:loading="summaryLoading"
						>
							<template #footer>
								<div class="w-100">
									<div class="text-secondary small">{{ t("Deferred, still open") }}</div>
									<div
										v-for="(line, i) in commissionDeferredLines || []"
										:key="i"
										class="text-secondary small font-monospace text-truncate"
									>
										{{ line }}
									</div>
									<div v-if="!commissionDeferredLines" class="text-secondary small font-monospace">
										—
									</div>
								</div>
							</template>
						</KpiCard>
					</div>
					<div class="col-sm-6 col-lg">
						<KpiCard
							:label="t('Exceptions')"
							:value="scorecards?.exceptions?.count ?? 0"
							value-tone="danger"
							icon="ti-alert-triangle"
							tone="red"
							clickable
							:active="activeQueue === REMITTANCE_QUEUES.ACCOUNTING_EXCEPTION"
							:loading="summaryLoading"
							:hint="t('Master record and journal entries disagree')"
							@click="selectQueue(REMITTANCE_QUEUES.ACCOUNTING_EXCEPTION)"
						/>
					</div>
				</div>
			</div>

			<!-- Region 2: the six work queues -->
			<div class="p-3 border-bottom">
				<div class="subheader mb-2">{{ t("Work Queues") }}</div>
				<div class="row row-cards">
					<div v-for="q in QUEUE_ORDER" :key="q" class="col-sm-6 col-lg-4 col-xxl-2">
						<KpiCard
							:label="queueMeta[q].title"
							:value="queueCount(q)"
							:icon="queueMeta[q].icon"
							:tone="queueMeta[q].tone"
							:hint="queueHint(q)"
							clickable
							:active="activeQueue === q"
							:loading="summaryLoading"
							@click="selectQueue(q)"
						/>
					</div>
				</div>
			</div>

			<!-- Region 3: the selected queue's rows -->
			<div class="d-flex align-items-center gap-2 flex-wrap px-3 py-2 border-bottom">
				<div class="fw-semibold">{{ queueMeta[activeQueue].title }}</div>
				<div class="text-secondary small">{{ queueMeta[activeQueue].note }}</div>
				<div class="ms-auto text-secondary small">
					{{ t("Count") }}:
					<strong class="font-monospace text-body">{{
						queue.policyConfigured ? queue.total : "—"
					}}</strong>
				</div>
			</div>

			<div v-if="queueError" class="card-body">
				<div class="alert alert-danger m-0">{{ queueError }}</div>
			</div>

			<template v-else>
				<div class="table-responsive">
					<table class="table table-vcenter card-table table-hover">
						<thead>
							<tr>
								<th>{{ t("Reference") }}</th>
								<th>{{ t("Sender") }}</th>
								<th>{{ t("Receiver") }}</th>
								<th>{{ t("Route") }}</th>
								<th class="text-end">{{ t("Sender pays") }}</th>
								<th class="text-end">{{ t("Receiver gets") }}</th>
								<th class="text-nowrap">{{ t("Age / expiry") }}</th>
								<th>{{ t("Owner") }}</th>
								<th>{{ t("Next action") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="queueLoading" :rows="5" :cols="9" />
						<tbody v-else-if="queue.policyConfigured && queue.rows.length">
							<tr v-for="r in queue.rows" :key="r.name">
								<td>
									<div class="fw-semibold font-monospace text-nowrap">{{ r.name }}</div>
									<div
										v-if="r.client_request_id"
										class="small text-secondary font-monospace text-truncate"
										:title="r.client_request_id"
									>
										{{ r.client_request_id }}
									</div>
									<span v-if="r.code_locked" class="badge bg-purple-lt text-purple mt-1">
										<i class="ti ti-lock me-1"></i>{{ t("Locked") }}
									</span>
									<!-- An approved refund is money the origin desk still has to count
									     back out. It reaches this queue beside a requested one, so the
									     row has to say which of the two it is. -->
									<span
										v-if="r.refund_status && r.refund_status !== 'None'"
										class="badge mt-1"
										:class="getStatusBadgeClass('Remittance Transfer', r.refund_status)"
									>
										<i class="ti ti-arrow-back-up me-1"></i>
										{{ t("Refund: {status}", { status: t(r.refund_status) }) }}
									</span>
								</td>
								<td>{{ r.sender_name || "—" }}</td>
								<td>{{ r.receiver_name || "—" }}</td>
								<td>{{ rowRoute(r) || "—" }}</td>
								<td class="text-end font-monospace text-nowrap">
									{{ formatMoney(r.tendered, r.send_currency, lang) }}
								</td>
								<td class="text-end font-monospace text-nowrap">
									{{ formatMoney(r.receiver_amount, r.receive_currency, lang) }}
								</td>
								<td class="text-nowrap">
									<div class="font-monospace">{{ formatDateTime(r.registered_at) }}</div>
									<div v-if="ageLabel(r.registered_at)" class="small text-secondary font-monospace">
										{{ ageLabel(r.registered_at) }}
									</div>
									<!-- Rendered only when the server actually sent a deadline. No
									     placeholder, no computed 72 hours: an expiry this screen made
									     up would put live transfers in a refund queue. -->
									<div v-if="r.expires_at" class="small text-orange font-monospace">
										<i class="ti ti-hourglass-low me-1"></i>{{ formatDateTime(r.expires_at) }}
									</div>
								</td>
								<td class="text-nowrap">{{ r.registered_by || "—" }}</td>
								<td>
									<div v-if="rowActions(r).length" class="btn-list flex-nowrap">
										<button
											v-for="(action, idx) in rowActions(r)"
											:key="action"
											type="button"
											class="btn btn-sm text-nowrap"
											:class="idx === 0 ? 'btn-outline-primary' : 'btn-outline-secondary'"
											@click.stop="openAction(r, action)"
										>
											{{ actionLabels[action] || action }}
										</button>
									</div>
									<span v-else class="text-secondary">—</span>
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<!-- "Not configured" and "nothing here" are different answers and get
				     different empty states. Collapsing them would let a screen report
				     an empty expiry queue it never actually evaluated. -->
				<EmptyState
					v-if="!queueLoading && !queue.policyConfigured"
					icon="ti-clock-off"
					accent-icon="ti-question-mark"
					tone="secondary"
					:title="t('Pickup expiry policy is not configured yet')"
					:subtitle="
						t(
							'Nothing sets an expiry deadline on transfers today, so this queue cannot be evaluated. That is not the same as it being empty.'
						)
					"
				/>
				<EmptyState
					v-else-if="!queueLoading && !queue.rows.length"
					icon="ti-checks"
					accent-icon="ti-check"
					tone="success"
					:title="t('Nothing in this queue')"
					:subtitle="queueMeta[activeQueue].note"
				/>

				<Pagination
					v-if="queue.policyConfigured && queue.total > 0"
					:total="queue.total"
					:limit-start="limitStart"
					:page-length="pageLength"
					:page-count="queue.rows.length"
					@update:limit-start="setOffset"
					@update:page-length="setPageLength"
				/>
			</template>
		</template>
	</div>
</template>

<style scoped>
/* Desktop keeps one compact density; the action buttons grow to a 40px touch
   target on phones, where a `btn-sm` row of them is otherwise ~31px tall. */
@media (max-width: 767.98px) {
	.stbl-remit-ops .btn {
		min-height: 40px;
	}
}
</style>
