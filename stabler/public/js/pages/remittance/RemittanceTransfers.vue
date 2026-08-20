<script setup>
/**
 * Transfers — the searchable list of every remittance this company registered.
 *
 * It reads `remittance_queries.transfers` (via api/remittance.js), which answers
 * with the master row: both parties, both desks, both legs of money and all four
 * status axes. The legacy screen this replaces listed Journal Entries and could
 * therefore only ever show a docstatus — it could not say "paid out, but the
 * reversal never posted", because that sentence needs two axes at once.
 *
 * Three things this screen deliberately does NOT do:
 *
 *   - No multi-select and no bulk action. Every action on this domain moves cash
 *     at a desk, one transfer at a time (spec, "Transfers"): a checkbox column
 *     is an invitation to pay out fourteen people with one click.
 *   - No action buttons. The drawer is a read-only preview and the row shows the
 *     server's `next_action` as a label, not a control — the payout, unlock and
 *     refund surfaces own those, and each of them re-reads `allowed_actions`
 *     from the server. A button drawn from a status or a role here would be a
 *     second, weaker gate.
 *   - No pickup code, anywhere. `assert_no_pickup_code` guarantees the payload
 *     never carries it; nothing here writes a row into the URL or localStorage
 *     either. The attempt COUNTER is shown; the code is not a thing this screen
 *     can know.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { remittanceApi, REMITTANCE_ACTIONS } from "../../api/remittance.js";
import { t } from "../../composables/i18n.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { useLatestRequest } from "../../composables/useLatestRequest.js";
import ListToolbar from "../../components/ListToolbar.vue";
import FilterChips from "../../components/FilterChips.vue";
import Pagination from "../../components/Pagination.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const latest = useLatestRequest();

// The `operational_status` Select options, verbatim from the doctype
// (remittance_transfer.json). `status` on the endpoint filters this axis only —
// the other three are on every row and the detail page separates all four.
const OPERATIONAL_STATUSES = ["Draft", "Registered", "Paid Out", "Refunded", "Expired", "Exception"];

// The same three the register screen offers (NewRemittance.vue). The server
// filters the SEND leg with this — the leg the cashier took the cash in.
const CURRENCIES = ["USD", "EUR", "USDT"];

// Wire values from the API module, never typed as strings here: a Russian and a
// Turkish browser have to agree about what the server offered.
const ACTION_LABELS = {
	[REMITTANCE_ACTIONS.PAYOUT]: t("Pay out"),
	[REMITTANCE_ACTIONS.UNLOCK_PICKUP_CODE]: t("Unlock pickup code"),
	[REMITTANCE_ACTIONS.REQUEST_REFUND]: t("Request refund"),
	[REMITTANCE_ACTIONS.APPROVE_REFUND]: t("Approve refund"),
	[REMITTANCE_ACTIONS.REJECT_REFUND]: t("Reject refund"),
	[REMITTANCE_ACTIONS.COMPLETE_REFUND]: t("Complete refund"),
};

// `has_exception` is tri-state on the server: omitted ignores the axis, truthy
// narrows to the accounting exceptions, falsy excludes them. A two-state
// checkbox cannot express that, so it is a Select.
const EXCEPTION_ANY = "";
const EXCEPTION_ONLY = "only";
const EXCEPTION_NONE = "none";

const searchInput = ref("");
const query = ref("");
const status = ref("");
const currency = ref("");
const fromDate = ref("");
const toDate = ref("");
const exception = ref(EXCEPTION_ANY);
const limitStart = ref(0);
const pageLength = ref(50);

const loading = ref(false);
const error = ref("");
const forbidden = ref(false);
const data = ref({ rows: [], total: 0 });

const selected = ref(null);

const rows = computed(() => data.value.rows || []);
const total = computed(() => data.value.total || 0);

// A missing currency code renders as a plain number rather than defaulting to a
// symbol: "$120" on a row that is actually EUR is worse than "120.00".
const money = (value, code) => formatMoney(value, code || "", user.value.language);

const statusOptions = computed(() => [
	{ value: "", label: t("Any status") },
	...OPERATIONAL_STATUSES.map((s) => ({ value: s, label: t(s) })),
]);

const currencyOptions = computed(() => [
	{ value: "", label: t("Any currency") },
	...CURRENCIES.map((c) => ({ value: c, label: c })),
]);

const exceptionOptions = computed(() => [
	{ value: EXCEPTION_ANY, label: t("Exceptions: any") },
	{ value: EXCEPTION_ONLY, label: t("Exceptions only") },
	{ value: EXCEPTION_NONE, label: t("Exclude exceptions") },
]);

// null / true / false — `remittance.js` turns those into the digit Frappe's
// `cint` reads. Passing a JS boolean straight through would arrive as "true".
const hasException = computed(() => {
	if (exception.value === EXCEPTION_ONLY) return true;
	if (exception.value === EXCEPTION_NONE) return false;
	return null;
});

const filterChips = computed(() => {
	const chips = [];
	if (query.value) chips.push({ key: "query", label: query.value, icon: "ti-search" });
	if (status.value) chips.push({ key: "status", label: t(status.value), icon: "ti-flag" });
	if (currency.value) chips.push({ key: "currency", label: currency.value, icon: "ti-coin" });
	if (fromDate.value) chips.push({ key: "from", label: t("From {date}", { date: fromDate.value }), icon: "ti-calendar" });
	if (toDate.value) chips.push({ key: "to", label: t("To {date}", { date: toDate.value }), icon: "ti-calendar" });
	if (exception.value === EXCEPTION_ONLY) chips.push({ key: "exception", label: t("Exceptions only"), icon: "ti-alert-triangle" });
	if (exception.value === EXCEPTION_NONE) chips.push({ key: "exception", label: t("Exclude exceptions"), icon: "ti-alert-triangle" });
	return chips;
});

const hasFilters = computed(() => filterChips.value.length > 0);

function removeChip(key) {
	if (key === "query") {
		searchInput.value = "";
		query.value = "";
	}
	if (key === "status") status.value = "";
	if (key === "currency") currency.value = "";
	if (key === "from") fromDate.value = "";
	if (key === "to") toDate.value = "";
	if (key === "exception") exception.value = EXCEPTION_ANY;
}

function clearFilters() {
	searchInput.value = "";
	query.value = "";
	status.value = "";
	currency.value = "";
	fromDate.value = "";
	toDate.value = "";
	exception.value = EXCEPTION_ANY;
}

function applySearch(value) {
	query.value = (value || "").trim();
}

function detailPath(name) {
	// A path string rather than a named route: the detail route is registered by
	// the module's own wiring, and `router-link :to="{ name }"` against a route
	// that is not mounted yet throws while rendering the list.
	return `/remittance/transfers/${encodeURIComponent(name)}`;
}

// Every axis except the operational one, rendered as a flag next to the badge.
// A transfer can be Paid Out and still be an accounting exception, and the row
// has to be able to say both at once.
function flags(row) {
	const out = [];
	// Mirrors the server's exception shapes (`_EXCEPTION_SHAPES` in
	// remittance_queries): Unposted is only wrong once the transfer is Registered
	// — on a Draft it is simply the truth, and flagging it red would put a red
	// triangle on every row that has not been registered yet.
	const unposted = row.operational_status === "Registered" && row.accounting_status === "Unposted";
	if (row.accounting_status === "Posting Error" || unposted) {
		out.push({ key: "accounting", icon: "ti-alert-triangle", cls: "text-red", title: t("Accounting: {status}", { status: t(row.accounting_status) }) });
	}
	if (row.verification_status === "Locked") {
		out.push({ key: "locked", icon: "ti-lock", cls: "text-red", title: t("Pickup code is locked") });
	}
	if (row.refund_status && row.refund_status !== "None") {
		out.push({ key: "refund", icon: "ti-arrow-back-up", cls: "text-orange", title: t("Refund: {status}", { status: t(row.refund_status) }) });
	}
	return out;
}

async function load() {
	if (!activeCompany.value) return;
	const isCurrent = latest.take();
	loading.value = true;
	error.value = "";
	forbidden.value = false;
	try {
		const res = await remittanceApi.transfers({
			company: activeCompany.value,
			query: query.value || null,
			status: status.value || null,
			currency: currency.value || null,
			from_date: fromDate.value || null,
			to_date: toDate.value || null,
			has_exception: hasException.value,
			limit: pageLength.value,
			offset: limitStart.value,
		});
		if (!isCurrent()) return;
		data.value = { rows: res?.rows || [], total: res?.total || 0 };
	} catch (err) {
		if (!isCurrent()) return;
		data.value = { rows: [], total: 0 };
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) forbidden.value = true;
		else error.value = err?.message || t("Failed to load transfers.");
	} finally {
		if (isCurrent()) loading.value = false;
	}
}

// Auto-apply (.claude/rules/10-frontend.md): a filter change reloads on its own.
// Anything that changes the result set resets the offset first, so page 3 of the
// old filter cannot be served as page 3 of the new one.
function reload() {
	selected.value = null;
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

onMounted(load);
watch([query, status, currency, fromDate, toDate, exception], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div>
		<div v-if="forbidden" class="alert alert-warning" role="alert">
			<i class="ti ti-lock me-1"></i>{{ t("You need a remittance role to see transfers.") }}
		</div>

		<template v-else>
			<div class="card">
				<ListToolbar
					v-model="searchInput"
					:placeholder="t('Reference, sender, receiver or desk… ⌘K')"
					:count="total"
					search-width="260px"
					@search="applySearch"
				>
					<template #filters>
						<div class="d-flex align-items-center gap-2 flex-wrap">
							<Select v-model="status" size="sm" :options="statusOptions" style="width: 150px" />
							<Select v-model="currency" size="sm" :options="currencyOptions" style="width: 140px" />
							<Select v-model="exception" size="sm" :options="exceptionOptions" style="width: 170px" />
							<span class="text-secondary small">{{ t("Registered") }}</span>
							<DateInput v-model="fromDate" size="sm" style="width: 120px" />
							<span class="text-secondary small">–</span>
							<DateInput v-model="toDate" size="sm" style="width: 120px" />
						</div>
					</template>
				</ListToolbar>

				<FilterChips :chips="filterChips" @remove="removeChip" @clear="clearFilters" />

				<div v-if="error" class="card-body">
					<div class="alert alert-danger m-0" role="alert">{{ error }}</div>
				</div>
				<EmptyState
					v-else-if="!loading && !rows.length && hasFilters"
					icon="ti-send"
					accent-icon="ti-search"
					tone="info"
					:title="t('No transfer matches these filters')"
					:subtitle="t('Widen the date range, or clear the status, currency and exception filters.')"
				/>
				<EmptyState
					v-else-if="!loading && !rows.length"
					icon="ti-send"
					accent-icon="ti-plus"
					tone="primary"
					:title="t('No transfers registered yet')"
					:subtitle="t('Register the first transfer and it will appear here.')"
				/>
				<div v-else class="table-responsive">
					<table class="table table-vcenter card-table table-hover">
						<thead>
							<tr>
								<th>{{ t("Reference") }}</th>
								<th>{{ t("Sender → receiver") }}</th>
								<th class="d-none d-lg-table-cell">{{ t("Route") }}</th>
								<th class="text-end">{{ t("Sender pays") }}</th>
								<th class="text-end">{{ t("Receiver gets") }}</th>
								<th>{{ t("Status") }}</th>
								<th class="d-none d-md-table-cell">{{ t("Registered") }}</th>
								<th class="d-none d-xl-table-cell">{{ t("Next action") }}</th>
								<th style="width: 44px"></th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="8" :cols="9" />
						<tbody v-else>
							<tr
								v-for="row in rows"
								:key="row.name"
								class="stbl-row"
								:class="{ 'table-active': selected && selected.name === row.name }"
								@click="selected = row"
							>
								<td>
									<div class="font-monospace text-nowrap">{{ row.name }}</div>
									<div v-if="row.client_request_id" class="small text-secondary font-monospace text-truncate" style="max-width: 180px">
										{{ row.client_request_id }}
									</div>
								</td>
								<td>
									<div class="text-truncate" style="max-width: 220px">{{ row.sender_name || "—" }}</div>
									<div class="small text-secondary text-truncate" style="max-width: 220px">
										<i class="ti ti-arrow-narrow-right me-1"></i>{{ row.receiver_name || "—" }}
									</div>
								</td>
								<td class="d-none d-lg-table-cell small text-secondary">
									<div class="text-truncate" style="max-width: 200px">
										{{ row.origin_branch || "—" }}<template v-if="row.origin_city"> · {{ row.origin_city }}</template>
									</div>
									<div class="text-truncate" style="max-width: 200px">
										<i class="ti ti-arrow-narrow-right me-1"></i>{{ row.destination_branch || "—" }}<template v-if="row.destination_city"> · {{ row.destination_city }}</template>
									</div>
								</td>
								<td class="text-end font-monospace text-nowrap">{{ money(row.tendered, row.send_currency) }}</td>
								<td class="text-end font-monospace text-nowrap">{{ money(row.receiver_amount, row.receive_currency) }}</td>
								<td class="text-nowrap">
									<StatusBadge doctype="Remittance Transfer" :status="row.operational_status" />
									<i
										v-for="flag in flags(row)"
										:key="flag.key"
										class="ti ms-1"
										:class="[flag.icon, flag.cls]"
										:title="flag.title"
									></i>
								</td>
								<td class="d-none d-md-table-cell text-nowrap">
									<div class="font-monospace small">{{ formatDateTime(row.registered_at) }}</div>
									<div v-if="row.expires_at" class="small text-secondary font-monospace">
										<i class="ti ti-hourglass me-1"></i>{{ formatDateTime(row.expires_at) }}
									</div>
									<div v-else-if="row.registered_by" class="small text-secondary text-truncate" style="max-width: 160px">
										{{ row.registered_by }}
									</div>
								</td>
								<td class="d-none d-xl-table-cell small text-secondary text-nowrap">
									{{ ACTION_LABELS[row.next_action] || "—" }}
								</td>
								<td class="text-end">
									<router-link
										:to="detailPath(row.name)"
										class="btn btn-sm btn-ghost-secondary stbl-row-action"
										:title="t('Open full detail')"
										:aria-label="t('Open full detail')"
										@click.stop
									>
										<i class="ti ti-chevron-right"></i>
									</router-link>
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<Pagination
					v-model:limit-start="limitStart"
					v-model:page-length="pageLength"
					:total="total"
					:page-count="rows.length"
				/>
			</div>
		</template>

		<!-- Read-only preview. Everything below already came down with the list row,
		     so opening it costs no request and can show nothing the list did not
		     already have the right to show. The full record is its own page. -->
		<div v-if="selected" class="offcanvas-backdrop fade show" @click="selected = null"></div>
		<div
			v-if="selected"
			class="offcanvas offcanvas-end show"
			tabindex="-1"
			style="visibility: visible; width: 420px"
		>
			<div class="offcanvas-header">
				<h5 class="offcanvas-title font-monospace">{{ selected.name }}</h5>
				<button type="button" class="btn-close" :aria-label="t('Close')" @click="selected = null"></button>
			</div>
			<div class="offcanvas-body">
				<div class="text-secondary small mb-3">{{ t("Preview — read only.") }}</div>

				<div class="mb-3">
					<div class="text-secondary small">{{ t("Sender → receiver") }}</div>
					<div class="fw-semibold">{{ selected.sender_name || "—" }}</div>
					<div><i class="ti ti-arrow-narrow-right me-1"></i>{{ selected.receiver_name || "—" }}</div>
				</div>

				<div class="mb-3">
					<div class="text-secondary small">{{ t("Route") }}</div>
					<div class="small">
						{{ selected.origin_branch || "—" }}<template v-if="selected.origin_city"> · {{ selected.origin_city }}</template>
						<i class="ti ti-arrow-narrow-right mx-1"></i>
						{{ selected.destination_branch || "—" }}<template v-if="selected.destination_city"> · {{ selected.destination_city }}</template>
					</div>
				</div>

				<div class="row g-2 mb-3">
					<div class="col-6">
						<div class="text-secondary small">{{ t("Sender pays") }}</div>
						<div class="font-monospace">{{ money(selected.tendered, selected.send_currency) }}</div>
					</div>
					<div class="col-6">
						<div class="text-secondary small">{{ t("Receiver gets") }}</div>
						<div class="font-monospace">{{ money(selected.receiver_amount, selected.receive_currency) }}</div>
					</div>
				</div>

				<!-- Four axes, kept apart here too: collapsing them into one badge is
				     exactly what the legacy screen did. -->
				<div class="row g-2 mb-3">
					<div class="col-6">
						<div class="text-secondary small">{{ t("Operational") }}</div>
						<StatusBadge doctype="Remittance Transfer" :status="selected.operational_status" />
					</div>
					<div class="col-6">
						<div class="text-secondary small">{{ t("Accounting") }}</div>
						<StatusBadge doctype="Remittance Accounting" :status="selected.accounting_status" />
					</div>
					<div class="col-6">
						<div class="text-secondary small">{{ t("Pickup code") }}</div>
						<StatusBadge doctype="Remittance Verification" :status="selected.verification_status" />
					</div>
					<div class="col-6">
						<div class="text-secondary small">{{ t("Refund") }}</div>
						<StatusBadge doctype="Remittance Refund" :status="selected.refund_status" />
					</div>
				</div>

				<div class="mb-3">
					<div class="text-secondary small">{{ t("Registered") }}</div>
					<div class="font-monospace small">{{ formatDateTime(selected.registered_at) }}</div>
					<div v-if="selected.registered_by" class="small text-secondary">{{ selected.registered_by }}</div>
				</div>

				<div class="mb-3">
					<div class="text-secondary small">{{ t("Pickup expiry") }}</div>
					<!-- Zero and undefined are not the same thing: nothing writes an
					     expiry today, so a transfer without one has no deadline rather
					     than a deadline of now. -->
					<div v-if="selected.expires_at" class="font-monospace small">{{ formatDateTime(selected.expires_at) }}</div>
					<div v-else class="small text-secondary">{{ t("No pickup expiry policy is configured yet.") }}</div>
				</div>

				<div class="mb-3">
					<div class="text-secondary small">{{ t("Failed code attempts") }}</div>
					<div class="font-monospace">{{ selected.code_attempts || 0 }}</div>
					<div class="small text-secondary">{{ t("The pickup code itself is shown once, on the registration receipt, and is never retrievable again.") }}</div>
				</div>

				<router-link :to="detailPath(selected.name)" class="btn btn-primary w-100">
					<i class="ti ti-file-description me-1"></i>{{ t("Open full detail") }}
				</router-link>
			</div>
		</div>
	</div>
</template>

<style scoped>
.stbl-row {
	cursor: pointer;
}
/* Desktop stays compact; the one control in the row keeps a 40px touch target
   on small screens (spec: "tek kompakt desktop density; mobilde 40px hedefler"). */
@media (max-width: 767.98px) {
	.stbl-row-action {
		min-width: 2.5rem;
		min-height: 2.5rem;
	}
}
</style>
