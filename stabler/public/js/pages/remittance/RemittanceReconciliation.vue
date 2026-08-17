<script setup>
/**
 * Remittance Reconciliation — what the desks took in, what they paid out, what
 * they still owe, and every place the master record and the ledger disagree.
 *
 * Six blocks, in the order a reconciler works them:
 *   1. register cash-in            flow, send currency
 *   2. open in-transit liability   BALANCE, receive currency, all-time
 *   3. payout / refund cash-out    flows, receive / send currency
 *   4. deferred vs earned commission
 *   5. master ↔ journal-entry variance  — the exception, in red
 *   6. aged open / expired, plus the open liability per branch and currency
 *
 * Three rules this screen is built around, each because breaking it produces a
 * specific lie at a cash desk:
 *
 * **Flows and balances are never mixed.** Register cash-in, payout cash-out and
 * refund cash-out answer "in this period". The open in-transit liability does
 * not: it is all-time, because an obligation opened three months ago is still
 * owed today, and a liability that shrinks when you narrow a date filter is not
 * a liability. The card says so on its face.
 *
 * **Currencies are never summed.** Every money figure arrives as a list of rows,
 * one per currency, and is rendered as one line per currency. There is no grand
 * total anywhere on this page and there must never be one — USD, EUR and USDT
 * do not add up (ADR-011).
 *
 * **There is no FX revenue on this page, and its absence is deliberate.** ADR-009
 * cut the chart to three accounts and left no FX margin account, so the margin
 * between the cashier's rate and the market rate is not recognised per transfer
 * at all — it is carried inside the base valuation of a monetary balance and
 * surfaces at period-end revaluation (`_remittance_accounting.py:20-24,170-174`).
 * Only deferred and earned COMMISSION are positions this screen can honestly
 * report; a card labelled "FX revenue" would be reporting a number the ledger
 * does not contain.
 *
 * Nothing here is derived, guessed or defaulted: every figure is a field of the
 * `remittance_queries.reconciliation` payload. Where the server reports that it
 * cannot answer — `expired.policy_configured` is false because nothing writes
 * `expires_at` — the screen says the policy is not configured rather than
 * showing a zero. Zero and undefined are not the same claim.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { remittanceApi, REMITTANCE_ACTIONS } from "../../api/remittance.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useLatestRequest } from "../../composables/useLatestRequest.js";
import KpiCard from "../../components/KpiCard.vue";
import DateInput from "../../components/DateInput.vue";
import PeriodSelect from "../../components/PeriodSelect.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const latest = useLatestRequest();

// Human labels for the server's action identifiers. The identifiers are wire
// values (`_remittance_actions.ACTIONS`) and are deliberately untranslated, so
// the label is looked up here and never the other way round. This screen only
// READS them — it draws no action buttons, because reconciliation is a finding,
// not a decision, and every button belongs to the queue and detail screens
// where the row's own `allowed_actions` gates it.
const ACTION_LABELS = {
	[REMITTANCE_ACTIONS.PAYOUT]: t("Payout"),
	[REMITTANCE_ACTIONS.UNLOCK_PICKUP_CODE]: t("Unlock code"),
	[REMITTANCE_ACTIONS.REQUEST_REFUND]: t("Request refund"),
	[REMITTANCE_ACTIONS.APPROVE_REFUND]: t("Approve refund"),
	[REMITTANCE_ACTIONS.REJECT_REFUND]: t("Reject refund"),
	[REMITTANCE_ACTIONS.COMPLETE_REFUND]: t("Complete refund"),
};

function blank() {
	return {
		company: "",
		from_date: null,
		to_date: null,
		as_of: "",
		register_cash_in: [],
		payout_cash_out: [],
		refund_cash_out: [],
		open_in_transit_liability: [],
		commission: {
			denominated_in: "send_currency",
			deferred_open: [],
			earned_in_window: [],
			registered_in_window: [],
		},
		variance: { count: 0, truncated: false, rows: [] },
		aged_open: { count: 0, truncated: false, rows: [] },
		expired: { policy_configured: false, count: 0, truncated: false, rows: [] },
		by_branch: [],
	};
}

// No bounds by default. A month window would be a convenience that silently
// changes what every flow figure means, and the reconciler never asked for it.
const periodKey = ref("all");
const fromDate = ref("");
const toDate = ref("");

const loading = ref(false);
const error = ref("");
const forbidden = ref(false);
const loadedOnce = ref(false);
const data = ref(blank());

const lang = computed(() => user.value?.language || "en");
const commission = computed(() => data.value.commission || blank().commission);
const variance = computed(() => data.value.variance || blank().variance);
const agedOpen = computed(() => data.value.aged_open || blank().aged_open);
const expired = computed(() => data.value.expired || blank().expired);
const byBranch = computed(() => data.value.by_branch || []);

// A row carries its own currency code, so it is formatted with that code and
// never with the company default: labelling a USDT figure as USD is the exact
// mistake the per-currency payload exists to prevent. An empty code falls
// through to `formatMoney`'s plain-number path rather than borrowing one.
const money = (value, currency) => formatMoney(value, currency || "", lang.value);

// One pre-formatted line per currency, biggest first — `KpiCard` shows lines[0]
// as the hero value and the rest underneath. Sorting by magnitude puts the
// figure that matters at the top without ever adding two currencies together.
function moneyLines(rows) {
	return (rows || [])
		.slice()
		.sort((a, b) => Math.abs(Number(b.amount || 0)) - Math.abs(Number(a.amount || 0)))
		.map((row) => money(row.amount, row.currency));
}

function transferCount(rows) {
	// Counts ARE summable across currencies — a count is dimensionless.
	return (rows || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
}

const periodLabel = computed(() => {
	const from = data.value.from_date || fromDate.value;
	const to = data.value.to_date || toDate.value;
	if (from && to) return t("{from} – {to}", { from: formatDate(from), to: formatDate(to) });
	if (from) return t("from {from}", { from: formatDate(from) });
	if (to) return t("up to {to}", { to: formatDate(to) });
	return t("all time");
});

// Empty is reported as "—" and never as "0": with no rows there is no currency
// to denominate a zero in, and "0" would claim the desk took in nothing when
// what is true is that nothing matched the period.
function flowHint(rows) {
	const count = transferCount(rows);
	if (!count) return t("Nothing in this period ({period})", { period: periodLabel.value });
	return t("{count} transfers · {period}", { count, period: periodLabel.value });
}

// Which of the four exception shapes this row matched. The predicates mirror
// `remittance_queries._VARIANCE_SHAPES` (remittance_queries.py:249-254) in the
// same order, so the reason shown is the reason the row was selected — read off
// the row's own fields, not guessed at.
function varianceReason(row) {
	if (row.operational_status === "Registered" && row.accounting_status === "Unposted") {
		return t("Registered at the desk, but nothing was ever posted to the ledger.");
	}
	if (row.accounting_status === "Posted" && !row.register_journal_entry) {
		return t("Marked posted, but the transfer names no register journal entry.");
	}
	if (row.operational_status === "Paid Out" && !row.payout_journal_entry) {
		return t("Marked paid out, but the transfer names no payout journal entry.");
	}
	if (row.operational_status === "Refunded" && !row.refund_journal_entry) {
		return t("Marked refunded, but the transfer names no refund journal entry.");
	}
	return t("The transfer's status and the journal entries it names do not agree.");
}

function nextActionLabel(row) {
	const action = row.next_action;
	return action ? ACTION_LABELS[action] || action : "";
}

function truncationNote(block) {
	return t("Showing the first {shown} of {count}.", {
		shown: (block.rows || []).length,
		count: block.count,
	});
}

function onPeriodChange({ from, to }) {
	fromDate.value = from;
	toDate.value = to;
}

// Typing into either date box is a custom range; the preset must stop claiming
// otherwise or the dropdown and the boxes disagree about what is on screen.
function onDateEdited() {
	if (periodKey.value !== "custom") periodKey.value = "custom";
}

async function load() {
	if (!activeCompany.value) return;
	const isCurrent = latest.take();
	loading.value = true;
	error.value = "";
	forbidden.value = false;
	try {
		const res = await remittanceApi.reconciliation(
			activeCompany.value,
			fromDate.value || null,
			toDate.value || null
		);
		if (!isCurrent()) return;
		const base = blank();
		data.value = {
			...base,
			...(res || {}),
			commission: { ...base.commission, ...(res?.commission || {}) },
			variance: { ...base.variance, ...(res?.variance || {}) },
			aged_open: { ...base.aged_open, ...(res?.aged_open || {}) },
			expired: { ...base.expired, ...(res?.expired || {}) },
		};
		loadedOnce.value = true;
	} catch (err) {
		if (!isCurrent()) return;
		data.value = blank();
		loadedOnce.value = false;
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) forbidden.value = true;
		else error.value = err?.message || t("Failed to load the reconciliation.");
	} finally {
		if (isCurrent()) loading.value = false;
	}
}

onMounted(load);
// Auto-apply on every filter change — no Apply button (.claude/rules/10-frontend.md).
watch([fromDate, toDate, activeCompany], load);
</script>

<template>
	<div>
		<div v-if="forbidden" class="alert alert-warning" role="alert">
			<i class="ti ti-lock me-1"></i>
			{{ t("You need a remittance role to see the reconciliation.") }}
		</div>

		<template v-else>
			<!-- Period bar. The scope sentence is not decoration: three of the four
			     figures below move with these dates and one deliberately does not. -->
			<div class="card mb-3">
				<div class="card-body py-2 px-3 d-flex flex-wrap align-items-end gap-2 stbl-recon-filters">
					<div>
						<label class="form-label small mb-1">{{ t("Period") }}</label>
						<PeriodSelect v-model="periodKey" size="sm" @change="onPeriodChange" />
					</div>
					<div>
						<label class="form-label small mb-1">{{ t("From") }}</label>
						<DateInput v-model="fromDate" size="sm" style="width: 130px" @blur="onDateEdited" />
					</div>
					<div>
						<label class="form-label small mb-1">{{ t("To") }}</label>
						<DateInput v-model="toDate" size="sm" style="width: 130px" @blur="onDateEdited" />
					</div>
					<div class="ms-auto text-secondary small text-end">
						<div>
							{{ t("Cash in and cash out cover {period}.", { period: periodLabel }) }}
						</div>
						<div>
							{{ t("The open obligation is all-time and ignores these dates.") }}
						</div>
						<div v-if="data.as_of" class="font-monospace">
							{{ t("As of {stamp}", { stamp: formatDateTime(data.as_of) }) }}
						</div>
					</div>
				</div>
			</div>

			<div v-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

			<!-- Blocks 1-3: two flows in, one balance, two flows out. Each card is a
			     list of per-currency lines; nothing is totalled across them. -->
			<div class="row row-deck row-cards mb-3">
				<div class="col-sm-6 col-xl-3">
					<KpiCard
						:label="t('Register cash-in')"
						value="—"
						:lines="moneyLines(data.register_cash_in)"
						:hint="flowHint(data.register_cash_in)"
						icon="ti-cash-banknote"
						tone="green"
						:loading="loading"
					/>
				</div>
				<div class="col-sm-6 col-xl-3">
					<KpiCard
						:label="t('Open in-transit liability')"
						value="—"
						:lines="moneyLines(data.open_in_transit_liability)"
						:hint="
							t('{count} obligations open · all time', {
								count: transferCount(data.open_in_transit_liability),
							})
						"
						icon="ti-clock-pause"
						tone="yellow"
						value-tone="yellow"
						:loading="loading"
					/>
				</div>
				<div class="col-sm-6 col-xl-3">
					<KpiCard
						:label="t('Payout cash-out')"
						value="—"
						:lines="moneyLines(data.payout_cash_out)"
						:hint="flowHint(data.payout_cash_out)"
						icon="ti-cash-off"
						tone="azure"
						:loading="loading"
					/>
				</div>
				<div class="col-sm-6 col-xl-3">
					<KpiCard
						:label="t('Refund cash-out')"
						value="—"
						:lines="moneyLines(data.refund_cash_out)"
						:hint="flowHint(data.refund_cash_out)"
						icon="ti-arrow-back-up"
						tone="orange"
						:loading="loading"
					/>
				</div>
			</div>

			<!-- Block 4: commission, and the reason there is nothing beside it. -->
			<div class="card mb-3">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ t("Commission") }}</h3>
					<span class="ms-2 text-secondary small">
						{{ t("Denominated in the send currency") }}
					</span>
				</div>
				<div class="card-body py-3">
					<div class="d-flex flex-wrap gap-4">
						<div>
							<div class="small text-secondary">{{ t("Deferred (not yet earned)") }}</div>
							<div v-if="loading" class="placeholder-glow">
								<span class="placeholder col-7 py-2 rounded-1"></span>
							</div>
							<template v-else>
								<div
									v-for="row in commission.deferred_open"
									:key="`deferred-${row.currency}`"
									class="font-monospace fw-bold"
								>
									{{ money(row.amount, row.currency) }}
								</div>
								<div v-if="!commission.deferred_open.length" class="font-monospace fw-bold">—</div>
							</template>
							<div class="small text-secondary">
								{{ t("Balance · all time · sits against obligations nobody has collected") }}
							</div>
						</div>
						<div>
							<div class="small text-secondary">{{ t("Earned (paid out in period)") }}</div>
							<div v-if="loading" class="placeholder-glow">
								<span class="placeholder col-7 py-2 rounded-1"></span>
							</div>
							<template v-else>
								<div
									v-for="row in commission.earned_in_window"
									:key="`earned-${row.currency}`"
									class="font-monospace fw-bold"
								>
									{{ money(row.amount, row.currency) }}
								</div>
								<div v-if="!commission.earned_in_window.length" class="font-monospace fw-bold">
									—
								</div>
							</template>
							<div class="small text-secondary">
								{{ t("Flow · {period} · moved to income at payout", { period: periodLabel }) }}
							</div>
						</div>
						<div>
							<div class="small text-secondary">{{ t("Charged at registration") }}</div>
							<div v-if="loading" class="placeholder-glow">
								<span class="placeholder col-7 py-2 rounded-1"></span>
							</div>
							<template v-else>
								<div
									v-for="row in commission.registered_in_window"
									:key="`registered-${row.currency}`"
									class="font-monospace fw-bold"
								>
									{{ money(row.amount, row.currency) }}
								</div>
								<div v-if="!commission.registered_in_window.length" class="font-monospace fw-bold">
									—
								</div>
							</template>
							<div class="small text-secondary">
								{{ t("Flow · {period} · charged, earned only on payout", { period: periodLabel }) }}
							</div>
						</div>
					</div>

					<!-- Why there is no third position here. Someone will look for it. -->
					<div class="small text-secondary mt-3">
						{{
							t(
								"Commission is the only remittance position this page can report. The margin between the rate the cashier applied and the market rate is not recognised per transfer — there is no FX margin account, so it stays inside the base valuation of the cash and obligation balances and appears only at period-end exchange-rate revaluation."
							)
						}}
					</div>
				</div>
			</div>

			<!-- Block 5: the exception. A non-zero difference is a broken ledger, not
			     a hint — the master claims a posting it cannot name. -->
			<div class="card mb-3">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ t("Master ↔ journal entry difference") }}</h3>
					<span
						v-if="!loading && loadedOnce"
						class="badge ms-2"
						:class="variance.count ? 'bg-danger text-white' : 'bg-success-lt text-success'"
					>
						{{ variance.count }}
					</span>
				</div>

				<div v-if="!loading && loadedOnce" class="card-body py-3">
					<div
						class="alert m-0"
						:class="variance.count ? 'alert-danger' : 'alert-success'"
						role="alert"
					>
						<div class="d-flex align-items-start gap-2">
							<i
								class="ti fs-2 lh-1"
								:class="variance.count ? 'ti-alert-triangle' : 'ti-checks'"
							></i>
							<div>
								<div class="fw-semibold">
									<template v-if="variance.count">
										{{
											t("{count} transfers claim a posting the ledger cannot be matched to.", {
												count: variance.count,
											})
										}}
									</template>
									<template v-else>
										{{ t("Every posted stage names the journal entry that carries it.") }}
									</template>
								</div>
								<div class="small mt-1">
									{{
										t(
											"This compares each transfer against the journal entries it names. The ledger-side balances are not read here, so agreement means the master is self-consistent, not that the trial balance was checked."
										)
									}}
								</div>
							</div>
						</div>
					</div>
				</div>

				<div v-if="loading || variance.rows.length" class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Transfer") }}</th>
								<th>{{ t("Parties") }}</th>
								<th>{{ t("Route") }}</th>
								<th class="text-end text-nowrap">{{ t("Sender paid") }}</th>
								<th class="text-end text-nowrap">{{ t("Receiver gets") }}</th>
								<th class="text-nowrap">{{ t("Registered") }}</th>
								<th>{{ t("Why it is an exception") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="3" :cols="7" />
						<tbody v-else>
							<tr v-for="row in variance.rows" :key="row.name">
								<td class="font-monospace text-nowrap">{{ row.name }}</td>
								<td>
									<div>{{ row.sender_name }}</div>
									<div class="small text-secondary">{{ row.receiver_name }}</div>
								</td>
								<td class="small text-nowrap">
									{{ row.origin_branch || "—" }} → {{ row.destination_branch || "—" }}
								</td>
								<td class="text-end font-monospace">
									{{ money(row.tendered, row.send_currency) }}
								</td>
								<td class="text-end font-monospace">
									{{ money(row.receiver_amount, row.receive_currency) }}
								</td>
								<td class="text-nowrap">{{ formatDate(row.registered_at) }}</td>
								<td class="text-danger small">{{ varianceReason(row) }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div
					v-if="!loading && variance.truncated"
					class="px-3 py-2 small text-secondary border-top"
				>
					{{ truncationNote(variance) }}
				</div>
			</div>

			<!-- Block 6a: aged open obligations. Reported, never graded — nothing in
			     the app defines when an open obligation becomes overdue, so colouring
			     these by age would be this screen inventing a policy. -->
			<div class="card mb-3">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ t("Aged open obligations") }}</h3>
					<span class="ms-2 text-secondary small">
						{{ t("Oldest first · no overdue threshold is defined, so none is applied") }}
					</span>
				</div>

				<EmptyState
					v-if="!loading && loadedOnce && !agedOpen.rows.length"
					icon="ti-checks"
					accent-icon="ti-sparkles"
					tone="success"
					compact
					:title="t('No obligation is still open')"
					:subtitle="t('Every registered transfer has been paid out or refunded.')"
				/>
				<div v-else class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Transfer") }}</th>
								<th>{{ t("Parties") }}</th>
								<th>{{ t("Route") }}</th>
								<th class="text-end text-nowrap">{{ t("Receiver gets") }}</th>
								<th class="text-nowrap">{{ t("Registered") }}</th>
								<th class="text-end text-nowrap">{{ t("Age (days)") }}</th>
								<th class="text-nowrap">{{ t("Waiting on") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="4" :cols="7" />
						<tbody v-else>
							<tr v-for="row in agedOpen.rows" :key="row.name">
								<td class="font-monospace text-nowrap">{{ row.name }}</td>
								<td>
									<div>{{ row.sender_name }}</div>
									<div class="small text-secondary">{{ row.receiver_name }}</div>
								</td>
								<td class="small text-nowrap">
									{{ row.origin_branch || "—" }} → {{ row.destination_branch || "—" }}
								</td>
								<td class="text-end font-monospace">
									{{ money(row.receiver_amount, row.receive_currency) }}
								</td>
								<td class="text-nowrap">{{ formatDate(row.registered_at) }}</td>
								<td class="text-end font-monospace">{{ Number(row.age_days || 0) }}</td>
								<td class="small text-secondary text-nowrap">{{ nextActionLabel(row) || "—" }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div
					v-if="!loading && agedOpen.truncated"
					class="px-3 py-2 small text-secondary border-top"
				>
					{{ truncationNote(agedOpen) }}
				</div>
			</div>

			<!-- Block 6b: expired. The server reports whether an expiry policy exists
			     at all, and today it does not — nothing writes `expires_at`. An empty
			     table here would read as "nothing has expired", which is a different
			     and unproven claim. -->
			<div class="card mb-3">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ t("Expired transfers") }}</h3>
				</div>

				<EmptyState
					v-if="!loading && loadedOnce && !expired.policy_configured"
					icon="ti-calendar-off"
					accent-icon="ti-help-circle"
					tone="secondary"
					compact
					:title="t('Pickup expiry policy is not configured yet')"
					:subtitle="
						t(
							'No transfer carries an expiry date, so nothing can be reported as expired. This is not the same as nothing having expired.'
						)
					"
				/>
				<EmptyState
					v-else-if="!loading && loadedOnce && !expired.rows.length"
					icon="ti-checks"
					accent-icon="ti-sparkles"
					tone="success"
					compact
					:title="t('Nothing has expired')"
					:subtitle="t('No open transfer has passed its pickup deadline.')"
				/>
				<div v-else-if="loading || expired.rows.length" class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Transfer") }}</th>
								<th>{{ t("Parties") }}</th>
								<th>{{ t("Route") }}</th>
								<th class="text-end text-nowrap">{{ t("Receiver gets") }}</th>
								<th class="text-nowrap">{{ t("Expired at") }}</th>
								<th class="text-nowrap">{{ t("Waiting on") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="2" :cols="6" />
						<tbody v-else>
							<tr v-for="row in expired.rows" :key="row.name">
								<td class="font-monospace text-nowrap">{{ row.name }}</td>
								<td>
									<div>{{ row.sender_name }}</div>
									<div class="small text-secondary">{{ row.receiver_name }}</div>
								</td>
								<td class="small text-nowrap">
									{{ row.origin_branch || "—" }} → {{ row.destination_branch || "—" }}
								</td>
								<td class="text-end font-monospace">
									{{ money(row.receiver_amount, row.receive_currency) }}
								</td>
								<td class="text-nowrap">{{ formatDateTime(row.expires_at) }}</td>
								<td class="small text-secondary text-nowrap">{{ nextActionLabel(row) || "—" }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div v-if="!loading && expired.truncated" class="px-3 py-2 small text-secondary border-top">
					{{ truncationNote(expired) }}
				</div>
			</div>

			<!-- The open obligation split the way a branch reconciles it: per desk and
			     per currency, which is the pair a cash count is done against. -->
			<div class="card">
				<div class="card-header py-2">
					<h3 class="card-title mb-0">{{ t("Open obligation by branch and currency") }}</h3>
					<span class="ms-2 text-secondary small">
						{{ t("All time · the same balance as the card above, split by desk") }}
					</span>
				</div>

				<EmptyState
					v-if="!loading && loadedOnce && !byBranch.length"
					icon="ti-building-bank"
					tone="secondary"
					compact
					:title="t('No desk is carrying an open obligation')"
					:subtitle="t('Nothing registered is still waiting to be collected.')"
				/>
				<div v-else class="table-responsive">
					<table class="table table-vcenter card-table">
						<thead>
							<tr>
								<th>{{ t("Branch") }}</th>
								<th>{{ t("Currency") }}</th>
								<th class="text-end text-nowrap">{{ t("Transfers") }}</th>
								<th class="text-end text-nowrap">{{ t("Open amount") }}</th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="3" :cols="4" />
						<tbody v-else>
							<tr v-for="row in byBranch" :key="`${row.branch}-${row.currency}`">
								<td>{{ row.branch || t("Unassigned") }}</td>
								<td class="font-monospace">{{ row.currency || "—" }}</td>
								<td class="text-end font-monospace">{{ Number(row.count || 0) }}</td>
								<td class="text-end font-monospace fw-semibold">
									{{ money(row.open_amount, row.currency) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
/* Desktop keeps the compact `sm` control density the rest of the SPA uses; on a
   phone the same controls have to clear the 40px touch target. */
@media (max-width: 767.98px) {
	/* Targeted by class, not by element: the filter bar's three controls are
	   `PeriodSelect` (a `.form-select` trigger button), and two `DateInput`s
	   (a `.form-control` text field plus a `.btn` calendar toggle). Matching
	   the classes also skips `DateInput`'s 1px visually-hidden native date
	   input — it carries no class, and a min-height would inflate it. */
	.stbl-recon-filters :deep(.form-control),
	.stbl-recon-filters :deep(.form-select),
	.stbl-recon-filters :deep(.btn) {
		min-height: 40px;
	}
	/* One control per row, each filling it — the inline desktop widths sit on the
	   component roots, so the override has to reach the child, not the wrapper. */
	.stbl-recon-filters > div {
		flex: 1 1 100%;
	}
	.stbl-recon-filters > div > * {
		width: 100% !important;
	}
}
</style>
