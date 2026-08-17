<script setup>
/**
 * Transfer detail — one remittance, in full, and read only.
 *
 * The drawer on the Transfers list previews the row it already has. This page
 * calls `remittance_queries.transfer_detail`, which is the only read that
 * carries the frozen quote, the append-only event trail, the linked Journal
 * Entries and the refund decision trail.
 *
 * Two rules this page exists to honour:
 *
 *   1. FOUR STATUS AXES, NEVER COLLAPSED. Operational, accounting, verification
 *      and refund are independent. "Paid out" and "the reversal never posted"
 *      are both true at once often enough that a single badge is a lie; the
 *      server keeps them apart and so does this screen.
 *   2. THE PICKUP CODE IS NOT READABLE HERE. `code_state` is the attempt
 *      COUNTER and the lockout. The plaintext was shown once, on the
 *      registration receipt, and no read path in this product returns it or its
 *      digest — so nothing on this page can render, log or link it.
 *
 * No action buttons: unlocking a code, paying out and deciding a refund each
 * live on the surface that owns them, and each re-reads `allowed_actions` from
 * the server before offering anything. A control drawn here from a status or a
 * role would be a second gate that disagrees with the first.
 */
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { remittanceApi } from "../../api/remittance.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { useLatestRequest } from "../../composables/useLatestRequest.js";
import StatusBadge from "../../components/StatusBadge.vue";
import EmptyState from "../../components/EmptyState.vue";

const route = useRoute();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const latest = useLatestRequest();

// The four axes, in the order the server returns them, each with its own
// STATUS_MAP key so a green "Posted" and a green "Paid Out" can never be read
// off the same palette by accident.
const AXES = [
	{
		key: "operational",
		label: t("Operational"),
		doctype: "Remittance Transfer",
		hint: t("Where the transfer itself stands."),
	},
	{
		key: "accounting",
		label: t("Accounting"),
		doctype: "Remittance Accounting",
		hint: t("Whether the ledger agrees with it."),
	},
	{
		key: "verification",
		label: t("Pickup code"),
		doctype: "Remittance Verification",
		hint: t("The state of the code, never the code."),
	},
	{
		key: "refund",
		label: t("Refund"),
		doctype: "Remittance Refund",
		hint: t("The refund decision, independent of the rest."),
	},
];

// Visual treatment per event type, following the precedent set by
// AuditTrail.vue: this is an icon/colour map for an append-only event log, not
// a document status, so it does not belong in composables/status.js. Keys are
// the `event_type` Select options on Remittance Event.
const EVENT_STYLE = {
	Register: { icon: "ti-cash", cls: "bg-blue-lt text-blue" },
	"Failed code attempt": { icon: "ti-alert-triangle", cls: "bg-yellow-lt text-yellow" },
	Lock: { icon: "ti-lock", cls: "bg-red-lt text-red" },
	Unlock: { icon: "ti-lock-open", cls: "bg-green-lt text-green" },
	Payout: { icon: "ti-cash-banknote", cls: "bg-green-lt text-green" },
	"Refund request": { icon: "ti-arrow-back-up", cls: "bg-orange-lt text-orange" },
	"Refund approval": { icon: "ti-checks", cls: "bg-blue-lt text-blue" },
	"Refund rejection": { icon: "ti-x", cls: "bg-red-lt text-red" },
	"Refund completion": { icon: "ti-circle-check", cls: "bg-green-lt text-green" },
};
const eventStyle = (type) => EVENT_STYLE[type] || { icon: "ti-point", cls: "bg-secondary-lt" };

// The stages of a refund, in the order they can happen. `_refund_trail` fills
// whichever ones occurred and leaves the rest null.
const REFUND_STAGES = [
	{ key: "requested", label: t("Requested") },
	{ key: "approved", label: t("Approved") },
	{ key: "rejected", label: t("Rejected") },
	{ key: "completed", label: t("Completed") },
];

// Starts true: the first render happens before `onMounted`, and the honest
// placeholder for "we have not asked yet" is the skeleton, not "not found".
const loading = ref(true);
const error = ref("");
const forbidden = ref(false);
const detail = ref(null);

const name = computed(() => String(route.params.name || ""));
const transfer = computed(() => detail.value?.transfer || {});
const quote = computed(() => detail.value?.quote || {});
const statusAxes = computed(() => detail.value?.status || {});
const stages = computed(() => detail.value?.stages || []);
const journalEntries = computed(() => detail.value?.journal_entries || []);
const codeState = computed(() => detail.value?.code_state || {});
const refund = computed(() => detail.value?.refund || {});
const audit = computed(() => detail.value?.audit || {});

// A missing currency code renders as a plain number rather than defaulting to a
// symbol: "$120" on a quote that is actually EUR is worse than "120.00".
const money = (value, code) => formatMoney(value, code || "", user.value.language);

const isCrossCurrency = computed(() => quote.value.send_currency !== quote.value.receive_currency);

// Journal Entry totals are stored in the POSTING company's currency, and the
// only currency this session knows is the active company's. When the record
// belongs to another company the figures render as plain numbers rather than
// carrying a symbol they may not be denominated in.
const ledgerCurrency = computed(() =>
	transfer.value.company && transfer.value.company === activeCompany.value ? session.currency : "",
);
const ledgerAmount = (value) => formatMoney(value, ledgerCurrency.value, user.value.language);

const refundTrail = computed(() =>
	REFUND_STAGES.map((stage) => ({ ...stage, entry: refund.value[stage.key] })).filter((s) => s.entry),
);

async function load() {
	if (!name.value) {
		loading.value = false;
		return;
	}
	const isCurrent = latest.take();
	loading.value = true;
	error.value = "";
	forbidden.value = false;
	try {
		const res = await remittanceApi.transferDetail(name.value);
		if (!isCurrent()) return;
		detail.value = res || null;
	} catch (err) {
		if (!isCurrent()) return;
		detail.value = null;
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) forbidden.value = true;
		else error.value = err?.message || t("Failed to load the transfer.");
	} finally {
		if (isCurrent()) loading.value = false;
	}
}

onMounted(load);
watch(name, load);
</script>

<template>
	<div>
		<div class="d-flex align-items-center gap-2 mb-3">
			<router-link to="/remittance/transfers" class="btn btn-sm btn-ghost-secondary">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Transfers") }}
			</router-link>
			<h3 class="m-0 font-monospace">{{ name }}</h3>
		</div>

		<div v-if="forbidden" class="alert alert-warning" role="alert">
			<i class="ti ti-lock me-1"></i>{{ t("You need a remittance role to see this transfer.") }}
		</div>
		<div v-else-if="error" class="alert alert-danger" role="alert">{{ error }}</div>

		<!-- No spinner in a void: the page skeleton keeps the layout it is about
		     to fill (.claude/rules/10-frontend.md). -->
		<div v-else-if="loading" class="card placeholder-glow">
			<div class="card-body">
				<div class="placeholder col-4 py-2 rounded-1 mb-3"></div>
				<div class="placeholder col-8 py-2 rounded-1 mb-2"></div>
				<div class="placeholder col-6 py-2 rounded-1 mb-2"></div>
				<div class="placeholder col-7 py-2 rounded-1"></div>
			</div>
		</div>

		<EmptyState
			v-else-if="!detail"
			icon="ti-file-off"
			tone="info"
			:title="t('Transfer not found')"
			:subtitle="t('It may have been removed, or the reference in the address is wrong.')"
		/>

		<template v-else>
			<!-- Four axes, side by side and never merged. -->
			<div class="row row-deck row-cards mb-3">
				<div v-for="axis in AXES" :key="axis.key" class="col-sm-6 col-lg-3">
					<div class="card">
						<div class="card-body py-2">
							<div class="text-secondary small">{{ axis.label }}</div>
							<div class="mt-1">
								<StatusBadge :doctype="axis.doctype" :status="statusAxes[axis.key] || ''" />
							</div>
							<div class="small text-secondary mt-1">{{ axis.hint }}</div>
						</div>
					</div>
				</div>
			</div>

			<div class="row row-cards">
				<div class="col-lg-7">
					<!-- The quote, frozen at registration (ADR-009). Nothing here is
					     recomputed: `register_base_rate` is the rate the register leg
					     actually posted at, and a rate derived now would be a number the
					     ledger does not contain. -->
					<div class="card mb-3">
						<div class="card-header">
							<div class="card-title">{{ t("Quote") }}</div>
							<div class="ms-auto small text-secondary">{{ t("Frozen at registration") }}</div>
						</div>
						<table class="table table-sm card-table">
							<tbody>
								<tr>
									<td class="text-secondary">{{ t("Commission mode") }}</td>
									<td class="text-end">
										{{ quote.commission_mode ? t(quote.commission_mode) : "—" }}
										<span v-if="quote.commission_pct !== null && quote.commission_pct !== undefined" class="font-monospace ms-1">
											{{ quote.commission_pct }}%
										</span>
									</td>
								</tr>
								<tr>
									<td class="text-secondary">{{ t("Principal") }}</td>
									<td class="text-end font-monospace">{{ money(quote.principal, quote.send_currency) }}</td>
								</tr>
								<tr>
									<td class="text-secondary">{{ t("Commission") }}</td>
									<td class="text-end font-monospace">{{ money(quote.commission, quote.send_currency) }}</td>
								</tr>
								<tr>
									<td class="text-secondary fw-semibold">{{ t("Sender handed over") }}</td>
									<td class="text-end font-monospace fw-semibold">{{ money(quote.tendered, quote.send_currency) }}</td>
								</tr>
								<tr>
									<td class="text-secondary fw-semibold">{{ t("Receiver gets") }}</td>
									<td class="text-end font-monospace fw-semibold">{{ money(quote.receiver_amount, quote.receive_currency) }}</td>
								</tr>
								<tr v-if="isCrossCurrency">
									<td class="text-secondary">{{ t("Exchange rate") }}</td>
									<td class="text-end font-monospace">
										<template v-if="quote.exchange_rate">
											1 {{ quote.send_currency }} = {{ quote.exchange_rate }} {{ quote.receive_currency }}
										</template>
										<template v-else>—</template>
									</td>
								</tr>
								<tr v-if="quote.register_base_rate">
									<td class="text-secondary">{{ t("Rate the register leg posted at") }}</td>
									<td class="text-end font-monospace">{{ quote.register_base_rate }}</td>
								</tr>
							</tbody>
						</table>
					</div>

					<!-- Append-only. Every line is a Remittance Event; nothing in this
					     product edits or deletes one, which is what makes the trail
					     usable as evidence. -->
					<div class="card mb-3">
						<div class="card-header">
							<div class="card-title">{{ t("Stage timeline") }}</div>
							<div class="ms-auto small text-secondary">{{ t("Append-only") }}</div>
						</div>
						<div class="card-body">
							<div v-if="!stages.length" class="text-secondary small">
								{{ t("No stage has been recorded for this transfer.") }}
							</div>
							<ul v-else class="list-unstyled m-0">
								<li v-for="event in stages" :key="event.name" class="d-flex gap-2 mb-3">
									<span class="stbl-event-dot" :class="eventStyle(event.event_type).cls">
										<i class="ti" :class="eventStyle(event.event_type).icon"></i>
									</span>
									<div class="flex-fill">
										<div class="d-flex flex-wrap gap-2 align-items-baseline">
											<span class="fw-semibold">{{ t(event.event_type) }}</span>
											<span class="small text-secondary font-monospace">{{ formatDateTime(event.occurred_at) }}</span>
										</div>
										<div class="small text-secondary">
											{{ event.actor || "—" }}<template v-if="event.branch"> · {{ event.branch }}</template>
										</div>
										<div v-if="event.details" class="small mt-1">{{ event.details }}</div>
									</div>
								</li>
							</ul>
						</div>
					</div>

					<div class="card mb-3">
						<div class="card-header">
							<div class="card-title">{{ t("Journal Entries") }}</div>
						</div>
						<div v-if="!journalEntries.length" class="card-body text-secondary small">
							{{ t("No journal entry is linked to this transfer.") }}
						</div>
						<div v-else class="table-responsive">
							<table class="table table-sm table-vcenter card-table">
								<thead>
									<tr>
										<th>{{ t("Entry") }}</th>
										<th>{{ t("Stage") }}</th>
										<th>{{ t("Date") }}</th>
										<th>{{ t("Status") }}</th>
										<th class="text-end">{{ t("Debit") }}</th>
										<th class="text-end">{{ t("Credit") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="entry in journalEntries" :key="entry.name">
										<td class="font-monospace small text-nowrap">{{ entry.name }}</td>
										<td class="small">{{ entry.stabler_remittance_stage ? t(entry.stabler_remittance_stage) : "—" }}</td>
										<td class="font-monospace small text-nowrap">{{ formatDate(entry.posting_date) }}</td>
										<td><StatusBadge doctype="Journal Entry" :docstatus="entry.docstatus" /></td>
										<td class="text-end font-monospace small">{{ ledgerAmount(entry.total_debit) }}</td>
										<td class="text-end font-monospace small">{{ ledgerAmount(entry.total_credit) }}</td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>

				<div class="col-lg-5">
					<div class="card mb-3">
						<div class="card-header">
							<div class="card-title">{{ t("Parties and route") }}</div>
						</div>
						<div class="card-body">
							<div class="mb-3">
								<div class="text-secondary small">{{ t("Sender") }}</div>
								<div class="fw-semibold">{{ transfer.sender_name || "—" }}</div>
								<div class="small text-secondary">
									{{ transfer.origin_branch || "—" }}<template v-if="transfer.origin_city"> · {{ transfer.origin_city }}</template>
								</div>
							</div>
							<div>
								<div class="text-secondary small">{{ t("Receiver") }}</div>
								<div class="fw-semibold">{{ transfer.receiver_name || "—" }}</div>
								<div class="small text-secondary">
									{{ transfer.destination_branch || "—" }}<template v-if="transfer.destination_city"> · {{ transfer.destination_city }}</template>
								</div>
							</div>
						</div>
					</div>

					<!-- The counter and the lockout. Never the code, never its digest:
					     the plaintext is shown exactly once, by the registration
					     receipt, and no read endpoint can hand it back. -->
					<div class="card mb-3">
						<div class="card-header">
							<div class="card-title">{{ t("Pickup code state") }}</div>
						</div>
						<div class="card-body">
							<div class="d-flex align-items-baseline gap-2 mb-2">
								<span class="text-secondary small">{{ t("Failed attempts") }}</span>
								<span class="font-monospace fs-3">{{ codeState.attempts || 0 }}</span>
								<span v-if="codeState.max_attempts" class="text-secondary font-monospace">
									/ {{ codeState.max_attempts }}
								</span>
							</div>
							<div class="mb-2">
								<span v-if="codeState.locked" class="badge bg-red-lt">
									<i class="ti ti-lock me-1"></i>{{ t("Locked") }}
								</span>
								<span v-else class="badge bg-green-lt">
									<i class="ti ti-lock-open me-1"></i>{{ t("Not locked") }}
								</span>
								<span v-if="codeState.locked_at" class="small text-secondary font-monospace ms-2">
									{{ formatDateTime(codeState.locked_at) }}
								</span>
							</div>
							<div class="mb-2">
								<div class="text-secondary small">{{ t("Pickup expiry") }}</div>
								<!-- Zero and undefined are not the same claim. Nothing writes an
								     expiry yet, so an empty field means no deadline exists — not
								     that the deadline has passed. -->
								<div v-if="transfer.expires_at" class="font-monospace small">
									{{ formatDateTime(transfer.expires_at) }}
								</div>
								<div v-else class="small text-secondary">
									{{ t("No pickup expiry policy is configured yet.") }}
								</div>
							</div>
							<div class="small text-secondary">
								{{ t("The pickup code is shown once, on the registration receipt. It cannot be read back here or anywhere else.") }}
							</div>
						</div>
					</div>

					<div class="card mb-3">
						<div class="card-header">
							<div class="card-title">{{ t("Refund") }}</div>
							<div class="ms-auto">
								<StatusBadge doctype="Remittance Refund" :status="refund.status || ''" />
							</div>
						</div>
						<div class="card-body">
							<div v-if="!refundTrail.length" class="text-secondary small">
								{{ t("No refund has been requested for this transfer.") }}
							</div>
							<div v-for="stage in refundTrail" :key="stage.key" class="mb-3">
								<div class="d-flex flex-wrap gap-2 align-items-baseline">
									<span class="fw-semibold">{{ stage.label }}</span>
									<span class="small text-secondary font-monospace">{{ formatDateTime(stage.entry.at) }}</span>
								</div>
								<div class="small text-secondary">
									{{ stage.entry.actor || "—" }}<template v-if="stage.entry.branch"> · {{ stage.entry.branch }}</template>
								</div>
								<div v-if="stage.entry.details" class="small mt-1">{{ stage.entry.details }}</div>
							</div>
						</div>
					</div>

					<div class="card">
						<div class="card-header">
							<div class="card-title">{{ t("Audit") }}</div>
						</div>
						<table class="table table-sm card-table">
							<tbody>
								<tr>
									<td class="text-secondary">{{ t("Created by") }}</td>
									<td class="text-end">{{ audit.created_by || "—" }}</td>
								</tr>
								<tr>
									<td class="text-secondary">{{ t("Created at") }}</td>
									<td class="text-end font-monospace small">{{ formatDateTime(audit.created_at) }}</td>
								</tr>
								<tr>
									<td class="text-secondary">{{ t("Registered by") }}</td>
									<td class="text-end">{{ audit.registered_by || "—" }}</td>
								</tr>
								<tr>
									<td class="text-secondary">{{ t("Registered at") }}</td>
									<td class="text-end font-monospace small">{{ formatDateTime(audit.registered_at) }}</td>
								</tr>
								<tr>
									<td class="text-secondary">{{ t("Last modified") }}</td>
									<td class="text-end font-monospace small">{{ formatDateTime(audit.last_modified_at) }}</td>
								</tr>
								<tr v-if="transfer.client_request_id">
									<td class="text-secondary">{{ t("Client request id") }}</td>
									<td class="text-end font-monospace small">{{ transfer.client_request_id }}</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>
			</div>
		</template>
	</div>
</template>

<style scoped>
.stbl-event-dot {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	flex: 0 0 auto;
	width: 1.75rem;
	height: 1.75rem;
	border-radius: 50%;
	font-size: 0.9rem;
}
</style>
