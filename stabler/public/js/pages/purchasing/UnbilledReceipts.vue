<script setup>
/**
 * Unbilled Receipts — what we received and never got billed for.
 *
 * A submitted Purchase Receipt debits the warehouse and credits Stock Received
 * But Not Billed (SRBNB); the Purchase Invoice is the only thing that clears
 * SRBNB again. Nothing in this app ever asks anyone to raise that invoice, so a
 * shipment can be received, sold, and never billed while SRBNB quietly keeps
 * the credit. This page is the missing prompt: what is unbilled, how old it is,
 * whether the ledger agrees, and one click to raise the bill.
 *
 * Two currency rules the payload forces on this page (summing across them is
 * the exact mistake review already caught on this branch):
 *   - `grand_total` is in the row's OWN currency. Imports receipts are tagged
 *     USD, domestic ones UZS, and one shipment yields several receipts (one per
 *     truck) — so that column is per-row only and is never totalled.
 *   - `totals.*` and `unbilled_amount` are company currency, which is also the
 *     currency the SRBNB ledger balance is kept in. That is the only reason the
 *     reconciliation banner below is arithmetically legal.
 */
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney, moneyEpsilon } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import { useLatestRequest } from "../../composables/useLatestRequest.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Pagination from "../../components/Pagination.vue";
import KpiCard from "../../components/KpiCard.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const { confirm } = useConfirm();
const toast = useToast();
const latest = useLatestRequest();

// Aging buckets are a derived age grade, not a document status, so they are not
// in `composables/status.js` (that map is keyed by doctype status). The colour
// scale mirrors `AgingTable.vue`'s `bucketCls` so A/P aging and this page grade
// age identically — a receipt 95 days old must look as red here as its supplier
// balance does there.
const BUCKETS = [
	{ value: "b_0_30", label: t("0–30 days"), short: t("0–30"), tone: "secondary", valueTone: "", icon: "ti-clock-hour-4", text: "" },
	{ value: "b_31_60", label: t("31–60 days"), short: t("31–60"), tone: "yellow", valueTone: "yellow", icon: "ti-hourglass", text: "text-yellow-dark" },
	{ value: "b_61_90", label: t("61–90 days"), short: t("61–90"), tone: "orange", valueTone: "orange", icon: "ti-clock-exclamation", text: "text-orange fw-semibold" },
	{ value: "b_90_plus", label: t("90+ days"), short: t("90+"), tone: "red", valueTone: "red", icon: "ti-alert-triangle", text: "text-red fw-semibold" },
];
const BUCKET_BY_CODE = Object.fromEntries(BUCKETS.map((b) => [b.value, b]));

const SRBNB_STYLE = {
	// A non-zero difference is an accounting break, not a hint: SRBNB is
	// maintained by the receipt/invoice pair alone, so a residual balance means
	// stock value and payables are both misstated. Hence danger, not warning.
	break: { alert: "alert-danger", icon: "ti-alert-triangle" },
	clean: { alert: "alert-success", icon: "ti-checks" },
	// Nothing is broken yet — we simply cannot measure. That is a setup gap.
	unknown: { alert: "alert-warning", icon: "ti-alert-circle" },
	// Neither broken nor clean: the two sides are not comparable right now.
	filtered: { alert: "alert-info", icon: "ti-filter" },
	// Same family as `filtered` — not a break, just not measurable on this date.
	historical: { alert: "alert-info", icon: "ti-calendar-off" },
};

function blank() {
	return {
		rows: [],
		totals: { total_unbilled: 0, b_0_30: 0, b_31_60: 0, b_61_90: 0, b_90_plus: 0, receipts: 0 },
		// `comparable` defaults true so a new bundle running against an older
		// payload (assets rebuild before `bench restart`) does not show every
		// user the historical banner.
		srbnb: { account: null, gl_balance: null, difference: null, comparable: true },
		as_of: "",
		company_currency: "",
		has_more: false,
	};
}

const supplier = ref("");
const supplierName = ref("");
const bucket = ref("");
const asOf = ref(todayIso());
const search = ref("");
const limitStart = ref(0);
const pageLength = ref(50);

const loading = ref(false);
const error = ref("");
const forbidden = ref(false);
const loadedOnce = ref(false);
const data = ref(blank());
const creating = ref("");

const rows = computed(() => data.value.rows || []);
const totals = computed(() => data.value.totals || {});
const srbnb = computed(() => data.value.srbnb || {});
const companyCurrency = computed(() => data.value.company_currency || session.currency);
const asOfShown = computed(() => data.value.as_of || asOf.value);

const money = (value, currency) => formatMoney(value, currency || companyCurrency.value, user.value.language);

const bucketOptions = computed(() => [
	{ value: "", label: t("Any age") },
	...BUCKETS.map((b) => ({ value: b.value, label: b.label })),
]);

const bucketShort = (code) => BUCKET_BY_CODE[code]?.short || "—";
const bucketBadgeClass = (code) => `bg-${BUCKET_BY_CODE[code]?.tone || "secondary"}-lt`;
const ageClass = (code) => BUCKET_BY_CODE[code]?.text || "";

// The Purchase Receipt drawer lives on the purchasing list page. An
// imports-only tenant reaching this screen through /imports would be bounced by
// the module guard, so the receipt id only becomes a link when it can be opened.
const canOpenReceipts = computed(() => session.canAccessModule("purchasing"));

// The endpoint takes no search argument, so search narrows the page already
// loaded — same contract as PurchaseReceipts.vue's `filteredRows`.
const visibleRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter(
		(r) =>
			(r.name || "").toLowerCase().includes(q) ||
			(r.supplier || "").toLowerCase().includes(q) ||
			(r.supplier_name || "").toLowerCase().includes(q)
	);
});

const hasNarrowedFilters = computed(() => Boolean(supplier.value || bucket.value || search.value.trim()));

// `Pagination` wants a row count; the contract guarantees `has_more`, not one.
// So the count is derived from `has_more` and never allowed to contradict it:
// on the last page (`has_more` false) what we have seen IS the total, whatever
// `totals.receipts` claims — otherwise Next would offer a page the server will
// not send. Before that, `totals.receipts` supplies the real "of N".
const pagerTotal = computed(() => {
	const seen = limitStart.value + rows.value.length;
	if (!data.value.has_more) return seen;
	return Math.max(Number(totals.value.receipts || 0), seen + 1);
});

// The banner reconciles the WHOLE company ledger against the WHOLE list. A
// supplier or bucket filter shrinks `total_unbilled` while the ledger balance
// stays company-wide, so subtracting the two would then measure the filter, not
// a break — and telling an accountant someone posted a rogue Journal Entry
// because they filtered by supplier is the one mistake this banner must never
// make. The date box is NOT in here — it is a separate reason the two sides stop
// lining up, and the server decides that one (`srbnb.comparable`) because only
// the server knows that the ledger half is dated and the billing half is not.
const reconcilable = computed(() => !supplier.value && !bucket.value);

const srbnbConfigured = computed(() => Boolean(srbnb.value.account));
const srbnbDifference = computed(() => {
	const raw = srbnb.value.difference;
	return raw === null || raw === undefined || raw === "" ? null : Number(raw);
});
// Order matters. `unknown` (no account / unreadable ledger) is a setup gap and
// must be reported even on a back-dated run, so it is checked before
// `historical`; otherwise a date banner would hide a company that has never
// configured the account at all.
const srbnbState = computed(() => {
	if (!reconcilable.value) return "filtered";
	if (!srbnbConfigured.value) return "unknown";
	if (srbnb.value.comparable === false) return "historical";
	if (srbnbDifference.value === null) return "unknown";
	return Math.abs(srbnbDifference.value) < moneyEpsilon(companyCurrency.value) ? "clean" : "break";
});
const srbnbStyle = computed(() => SRBNB_STYLE[srbnbState.value]);
// The two signs accuse different documents, and only one of the two lists is
// true at a time. Positive means something CREDITED the account outside the
// receipt chain; negative means something DEBITED it that this list cannot see.
// Offering both lists at once is how an accountant ends up checking four
// documents to explain one number, three of which cannot produce its sign.
const srbnbSign = computed(() => Math.sign(srbnbDifference.value || 0));

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 10,
	});
}
function pickSupplier(s) {
	supplier.value = s.name;
	supplierName.value = s.supplier_name;
}
function clearSupplier() {
	supplier.value = "";
	supplierName.value = "";
}

// Restores the comparable state the banner needs. `search` is left alone: it
// filters the loaded page client-side and never touches the server totals.
function clearNarrowingFilters() {
	clearSupplier();
	bucket.value = "";
}

async function load() {
	if (!activeCompany.value) return;
	const isCurrent = latest.take();
	loading.value = true;
	error.value = "";
	forbidden.value = false;
	try {
		const res = await call("stabler.api.purchasing.unbilled_receipts", {
			company: activeCompany.value,
			supplier: supplier.value || undefined,
			bucket: bucket.value || undefined,
			as_of: asOf.value || undefined,
			limit_start: limitStart.value,
			limit_page_length: pageLength.value,
		});
		if (!isCurrent()) return;
		const base = blank();
		data.value = {
			...base,
			...(res || {}),
			totals: { ...base.totals, ...(res?.totals || {}) },
			srbnb: { ...base.srbnb, ...(res?.srbnb || {}) },
		};
		loadedOnce.value = true;
	} catch (err) {
		if (!isCurrent()) return;
		data.value = blank();
		loadedOnce.value = false;
		if (err?.status === 403 || /role|permission/i.test(err?.message || "")) forbidden.value = true;
		else error.value = err?.message || t("Failed to load unbilled receipts.");
	} finally {
		if (isCurrent()) loading.value = false;
	}
}

// Auto-apply: a filter change reloads immediately, no Apply button
// (.claude/rules/10-frontend.md). Anything that changes the result set resets
// the offset first so page 3 of the old filter cannot show as page 3 of the new.
function reload() {
	if (limitStart.value !== 0) limitStart.value = 0;
	else load();
}

async function createInvoice(row) {
	const ok = await confirm({
		title: t("Create purchase invoice"),
		body: t("Raise a draft purchase invoice for {receipt} from {supplier}? It creates a payable draft — nothing posts to the ledger until you submit it.", {
			receipt: row.name,
			supplier: row.supplier_name || row.supplier,
		}),
		confirmLabel: t("Create invoice"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	creating.value = row.name;
	try {
		const res = await call("stabler.api.purchasing.create_purchase_invoice_from_pr", { name: row.name });
		if (res?.name) toast.success(t("Draft invoice {name} created.", { name: res.name }));
		else toast.success(t("Draft invoice created."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Failed to create the invoice."));
	} finally {
		creating.value = "";
	}
}

onMounted(load);
watch([supplier, bucket, asOf], reload);
watch(limitStart, load);
watch(pageLength, reload);
watch(activeCompany, reload);
</script>

<template>
	<div>
		<div v-if="forbidden" class="alert alert-warning" role="alert">
			<i class="ti ti-lock me-1"></i>{{ t("You need a purchasing or accounts role to see unbilled receipts.") }}
		</div>

		<template v-else>
			<!-- Aging strip — company currency throughout, and a segmented filter:
			     clicking a bucket narrows the list to it, clicking the total clears. -->
			<div class="row row-deck row-cards mb-3">
				<div class="col-sm-6 col-lg-4">
					<KpiCard
						:label="t('Unbilled total')"
						:value="money(totals.total_unbilled)"
						icon="ti-receipt-off"
						tone="red"
						:loading="loading"
						clickable
						:active="!bucket"
						:hint="t('{count} receipts, as of {date}', { count: totals.receipts, date: formatDate(asOfShown) })"
						@click="bucket = ''"
					/>
				</div>
				<!-- `totals` is computed over the bucket-filtered scan, so once a bucket is
				     picked every other bucket sums to zero. Printing that as money reads as
				     "there is nothing in 90+" to someone working the 31-60 list, which is the
				     opposite of true and hides exactly the exposure this strip exists to
				     escalate. Until the endpoint returns bucket-independent totals
				     (stabler-mn8r), the unselected buckets say "not measured here" rather
				     than a number that is wrong. -->
				<div v-for="b in BUCKETS" :key="b.value" class="col-sm-6 col-lg-2">
					<KpiCard
						:label="b.label"
						:value="bucket && bucket !== b.value ? '—' : money(totals[b.value])"
						:icon="b.icon"
						:tone="b.tone"
						:value-tone="b.valueTone"
						:loading="loading"
						clickable
						:active="bucket === b.value"
						@click="bucket = bucket === b.value ? '' : b.value"
					/>
				</div>
			</div>

			<!-- SRBNB reconciliation — the reason this page exists. -->
			<div v-if="!error && loadedOnce" class="alert" :class="srbnbStyle.alert" role="alert">
				<div class="d-flex align-items-start gap-2">
					<i class="ti fs-2 lh-1" :class="srbnbStyle.icon"></i>
					<div class="flex-fill">
						<div class="fw-semibold">
							<template v-if="srbnbState === 'break'">{{ t("Stock Received But Not Billed does not agree with this list.") }}</template>
							<template v-else-if="srbnbState === 'clean'">{{ t("Stock Received But Not Billed agrees with this list.") }}</template>
							<template v-else-if="srbnbState === 'filtered'">{{ t("Reconciliation is paused while this list is filtered.") }}</template>
							<template v-else-if="srbnbState === 'historical'">{{ t("Reconciliation is paused on a past date.") }}</template>
							<template v-else>{{ t("This list cannot be reconciled against the ledger.") }}</template>
						</div>

						<div class="d-flex flex-wrap gap-4 mt-2">
							<div>
								<div class="small text-secondary">{{ t("SRBNB ledger balance") }}</div>
								<div class="font-monospace fw-bold">{{ srbnbConfigured ? money(srbnb.gl_balance) : "—" }}</div>
								<div class="small text-secondary font-monospace">{{ srbnb.account || t("account not set") }}</div>
							</div>
							<div>
								<div class="small text-secondary">{{ t("Unbilled on this list") }}</div>
								<div class="font-monospace fw-bold">{{ money(totals.total_unbilled) }}</div>
								<div class="small text-secondary">{{ t("{count} receipts", { count: totals.receipts }) }}</div>
							</div>
							<div>
								<div class="small text-secondary">{{ t("Difference") }}</div>
								<div class="font-monospace fw-bold">
									{{ srbnbState === "filtered" || srbnbDifference === null ? "—" : money(srbnbDifference) }}
								</div>
								<div class="small text-secondary">{{ t("as of {date}", { date: formatDate(asOfShown) }) }}</div>
							</div>
						</div>

						<div v-if="srbnbState === 'break'" class="small mt-2">
							<div>
								{{ t("Only two documents may move this account — the Purchase Receipt that credits it and the Purchase Invoice that clears it. A balance no receipt on this list explains means something else wrote to it:") }}
							</div>
							<ul v-if="srbnbSign > 0" class="mb-0 mt-1 ps-3">
								<li>{{ t("a Journal Entry posted straight to Stock Received But Not Billed, which is not an accepted way to move this account.") }}</li>
							</ul>
							<ul v-else class="mb-0 mt-1 ps-3">
								<li>{{ t("a Purchase Invoice booked to this account without naming the receipt it settles, so the ledger is cleared while the receipt still counts as unbilled here; or") }}</li>
								<li>{{ t("a return receipt, which debits this account and is deliberately left out of this list; or") }}</li>
								<li>{{ t("tax or charges inside a receipt total — only the net goes into this account, so anything the tax table added was never there to clear; or") }}</li>
								<li>{{ t("a Journal Entry posted straight to Stock Received But Not Billed, which is not an accepted way to move this account.") }}</li>
							</ul>
							<div class="mt-1">
								{{ t("Until it is explained, stock value and trade payables are both misstated by the difference.") }}
							</div>
						</div>
						<div v-else-if="srbnbState === 'clean'" class="small mt-2">
							{{ t("Every amount sitting in Stock Received But Not Billed is explained by a receipt on this list.") }}
						</div>
						<div v-else-if="srbnbState === 'historical'" class="small mt-2 d-flex flex-wrap align-items-center gap-2">
							<span class="flex-fill">
								{{ t("The ledger balance is taken on that date, but whether a receipt is billed is only known as it stands today — so this list shows current billing status, not the position on that date. Subtracting the two would report the invoices raised since then as a ledger break.") }}
							</span>
							<button type="button" class="btn btn-sm btn-outline-secondary text-nowrap" @click="asOf = todayIso()">
								<i class="ti ti-calendar-up me-1"></i>{{ t("Reconcile as of today") }}
							</button>
						</div>
						<div v-else-if="srbnbState === 'filtered'" class="small mt-2 d-flex flex-wrap align-items-center gap-2">
							<span class="flex-fill">
								{{ t("The ledger balance covers the whole company, while the total beside it covers only the filtered receipts — subtracting them would measure the filter, not a ledger break.") }}
							</span>
							<button type="button" class="btn btn-sm btn-outline-secondary text-nowrap" @click="clearNarrowingFilters">
								<i class="ti ti-filter-off me-1"></i>{{ t("Reconcile the full list") }}
							</button>
						</div>
						<div v-else class="small mt-2">
							<template v-if="!srbnbConfigured">
								{{ t("No Stock Received But Not Billed account is configured on this company, so the ledger side cannot be read. The difference is not zero — it is unknown. Set the account on the Company, then reload.") }}
							</template>
							<template v-else>
								{{ t("The balance of {account} could not be read, so the difference is unknown rather than zero.", { account: srbnb.account }) }}
							</template>
						</div>
					</div>
				</div>
			</div>

			<div class="card">
				<ListToolbar
					v-model="search"
					:placeholder="t('Receipt or supplier… ⌘K')"
				>
					<template #filters>
						<div class="d-flex align-items-center gap-2">
							<div style="width: 190px">
								<Typeahead
									v-model="supplier"
									:search="searchSuppliers"
									:display="supplierName"
									:placeholder="t('All suppliers')"
									size="sm"
									open-on-focus
									@pick="pickSupplier"
									@clear="clearSupplier"
								>
									<template #option="{ item }">
										<div class="fw-semibold small">{{ item.supplier_name }}</div>
										<div class="small text-secondary font-monospace">{{ item.name }}</div>
									</template>
								</Typeahead>
							</div>
							<Select v-model="bucket" size="sm" :options="bucketOptions" style="width: 150px" />
							<span class="text-secondary small">{{ t("As of") }}</span>
							<!-- A future cut-off would age every receipt by the gap and mis-grade
							     the buckets, so the box stops at today. -->
							<DateInput v-model="asOf" :max="todayIso()" size="sm" style="width: 120px" />
						</div>
					</template>

					<template #summary>
						<div class="d-flex gap-3 small text-secondary align-items-center flex-wrap">
							<div>{{ t("Receipts") }}: <strong class="font-monospace text-body">{{ totals.receipts }}</strong></div>
							<div>
								{{ t("Unbilled") }}:
								<strong class="font-monospace text-body">{{ money(totals.total_unbilled) }}</strong>
							</div>
						</div>
					</template>
				</ListToolbar>

				<div v-if="error" class="card-body">
					<div class="alert alert-danger m-0" role="alert">{{ error }}</div>
				</div>
				<EmptyState
					v-else-if="!loading && !visibleRows.length && hasNarrowedFilters"
					icon="ti-receipt-off"
					accent-icon="ti-search"
					tone="info"
					:title="t('No unbilled receipts match these filters')"
					:subtitle="t('Clear the supplier, age or search filter, or move the as-of date forward.')"
				/>
				<EmptyState
					v-else-if="!loading && !visibleRows.length"
					icon="ti-checks"
					accent-icon="ti-sparkles"
					tone="success"
					:title="t('Nothing received is waiting for a bill')"
					:subtitle="t('Every submitted purchase receipt is fully billed as of {date}.', { date: formatDate(asOfShown) })"
				/>
				<div v-else class="table-responsive">
					<table class="table table-vcenter card-table table-hover">
						<thead>
							<tr>
								<th>{{ t("Supplier") }}</th>
								<th class="text-nowrap">{{ t("Receipt") }}</th>
								<th class="text-nowrap">{{ t("Date") }}</th>
								<th class="text-end text-nowrap">{{ t("Age (days)") }}</th>
								<th>{{ t("Bucket") }}</th>
								<th class="text-end text-nowrap">{{ t("Received value") }}</th>
								<th class="text-end text-nowrap">{{ t("Billed") }}</th>
								<th class="text-end text-nowrap">
									{{ t("Unbilled") }}
									<span class="text-secondary fw-normal">{{ companyCurrency }}</span>
								</th>
								<th></th>
							</tr>
						</thead>
						<SkeletonRows v-if="loading" :rows="6" :cols="9" />
						<tbody v-else>
							<tr v-for="r in visibleRows" :key="r.name">
								<td>
									<div class="fw-semibold">{{ r.supplier_name || r.supplier }}</div>
									<div class="small text-secondary font-monospace">{{ r.supplier }}</div>
								</td>
								<td class="text-nowrap">
									<router-link
										v-if="canOpenReceipts"
										:to="{ path: '/purchasing/receipts', query: { open: r.name } }"
										class="font-monospace"
									>{{ r.name }}</router-link>
									<span v-else class="font-monospace">{{ r.name }}</span>
								</td>
								<td class="text-nowrap">{{ formatDate(r.posting_date) }}</td>
								<td class="text-end font-monospace" :class="ageClass(r.bucket)">{{ Number(r.age_days || 0) }}</td>
								<td><span class="badge" :class="bucketBadgeClass(r.bucket)">{{ bucketShort(r.bucket) }}</span></td>
								<td class="text-end font-monospace">{{ money(r.grand_total, r.currency) }}</td>
								<td class="text-end font-monospace" :class="Number(r.per_billed || 0) > 0 ? 'text-orange' : 'text-secondary'">
									{{ Number(r.per_billed || 0).toFixed(0) }}%
								</td>
								<td class="text-end font-monospace fw-semibold">{{ money(r.unbilled_amount) }}</td>
								<td class="text-end">
									<button
										type="button"
										class="btn btn-sm btn-outline-secondary text-nowrap"
										:disabled="Boolean(creating)"
										@click="createInvoice(r)"
									>
										<span v-if="creating === r.name" class="spinner-border spinner-border-sm me-1"></span>
										<i v-else class="ti ti-file-invoice me-1"></i>{{ t("Create invoice") }}
									</button>
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div
					v-if="!error && !loading && search.trim() && visibleRows.length !== rows.length"
					class="px-3 py-2 small text-secondary border-top"
				>
					{{ t("Search matches {shown} of the {loaded} receipts on this page.", { shown: visibleRows.length, loaded: rows.length }) }}
				</div>

				<Pagination
					v-if="!error && pagerTotal > 0"
					v-model:limit-start="limitStart"
					v-model:page-length="pageLength"
					:total="pagerTotal"
					:page-count="rows.length"
				/>
			</div>
		</template>
	</div>
</template>
