<script setup>
import { computed, onMounted, onUnmounted, ref, watch, nextTick } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso, startOfYearIso, presetRange } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import PeriodSelect from "../../components/PeriodSelect.vue";
import VoucherDrawer from "../../components/VoucherDrawer.vue";
import EmptyState from "../../components/EmptyState.vue";
import { t } from "../../composables/i18n.js";
import { useVoucherDrill } from "../../composables/useVoucherDrill.js";

const route = useRoute();
const router = useRouter();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const accountName = computed(() => route.params.account);

// ---------------------------------------------------------------------------
// Pagination state
// ---------------------------------------------------------------------------
const PAGE_SIZE = 100;

const loading = ref(false);
const loadingMore = ref(false);
const error = ref("");
const entries = ref([]);
const totalCount = ref(0);
const hasMore = ref(false);
const start = ref(0);

// ---------------------------------------------------------------------------
// Filter / sort state
// ---------------------------------------------------------------------------
const fromDate = ref("");
const toDate = ref("");
const periodKey = ref("custom");
const dateDir = ref("desc"); // "desc" = newest first, "asc" = oldest first

const summary = ref(null);
// True when the backend confirms this account is eligible for USD display.
// Value is invariant across pages for a given account; set from the first (and any) page response.
const usdApplicable = ref(false);
// "revalued" (Case A: сўм ÷ CBU rate) or "book" (Case B: GL historical-cost USD).
const usdMode = ref(null);

const accountCurrency = computed(() => summary.value?.account_currency || currency.value);
const accountTitle = computed(() => summary.value?.account_name || accountName.value);
const isMultiCurrency = computed(
	() => accountCurrency.value && accountCurrency.value !== currency.value
);
// USD closing balance: the newest row's running_balance_usd.
// In desc order (default) that's entries[0]; in asc order it's the last entry.
const closingUsd = computed(() => {
	if (!usdApplicable.value || !entries.value.length) return null;
	const newest =
		dateDir.value === "desc"
			? entries.value[0]
			: entries.value[entries.value.length - 1];
	return newest?.running_balance_usd ?? null;
});

// ---------------------------------------------------------------------------
// Voucher drawer state (in-place view for JE / Payment)
// ---------------------------------------------------------------------------
// Source-voucher drill — shared with StockLedger and the financial statements.
const { open: drawerOpen, loading: drawerLoading, detail: drawerDetail, close: closeDrawer, openVoucher, canOpen } = useVoucherDrill();

// ---------------------------------------------------------------------------
// Data fetching
// ---------------------------------------------------------------------------
async function fetchPage(append = false) {
	if (!accountName.value) return;

	if (append) {
		loadingMore.value = true;
	} else {
		loading.value = true;
		error.value = "";
		entries.value = [];
		summary.value = null;
		start.value = 0;
		hasMore.value = false;
		totalCount.value = 0;
	}

	try {
		const params = {
			company: activeCompany.value,
			account: accountName.value,
			limit: PAGE_SIZE,
			start: start.value,
			order: dateDir.value,
		};
		if (fromDate.value) params.from_date = fromDate.value;
		if (toDate.value) params.to_date = toDate.value;

		// Fetch ledger page + summary in parallel on first load; page-only on append.
		const fetches = [call("stabler.api.money.gl_entries", params)];
		if (!append) {
			fetches.push(
				call("stabler.api.money.account_summary", {
					company: activeCompany.value,
					account: accountName.value,
					from_date: fromDate.value || undefined,
					to_date: toDate.value || undefined,
				})
			);
		}
		const [entriesRes, summaryRes] = await Promise.all(fetches);

		hasMore.value = entriesRes.has_more ?? false;
		totalCount.value = entriesRes.total_count ?? 0;
		usdApplicable.value = entriesRes.usd_applicable === true;
		usdMode.value = entriesRes.usd_mode || null;

		if (append) {
			entries.value = [...entries.value, ...(entriesRes.entries || [])];
		} else {
			entries.value = entriesRes.entries || [];
			summary.value = summaryRes ?? null;
		}

		// Advance the offset for the next page.
		start.value = entries.value.length;
	} catch (err) {
		error.value = err?.message || t("Failed to load ledger.");
	} finally {
		loading.value = false;
		loadingMore.value = false;
	}
}

function fetchLedger() {
	fetchPage(false);
}

function loadNextPage() {
	if (!hasMore.value || loadingMore.value || loading.value) return;
	fetchPage(true);
}

// ---------------------------------------------------------------------------
// Sort toggle — resets to page 0 so we get genuine oldest/newest rows.
// ---------------------------------------------------------------------------
function toggleDateDir() {
	dateDir.value = dateDir.value === "desc" ? "asc" : "desc";
	fetchLedger();
}

// ---------------------------------------------------------------------------
// Period preset selection
// ---------------------------------------------------------------------------
function onPeriodChange({ from, to }) {
	if (periodKey.value === "custom") return;
	fromDate.value = from;
	toDate.value = to;
	fetchLedger();
}

// ---------------------------------------------------------------------------
// Infinite scroll via IntersectionObserver on a sentinel element.
// ---------------------------------------------------------------------------
const sentinel = ref(null);
let observer = null;

function setupObserver() {
	if (observer) {
		observer.disconnect();
		observer = null;
	}
	if (!sentinel.value) return;
	observer = new IntersectionObserver(
		(entries) => {
			if (entries[0]?.isIntersecting) loadNextPage();
		},
		{ rootMargin: "200px" } // start loading a bit before the sentinel is visible
	);
	observer.observe(sentinel.value);
}

// Re-wire observer whenever sentinel mounts/unmounts (v-if removes the element).
watch(sentinel, () => nextTick(setupObserver));

onUnmounted(() => {
	if (observer) observer.disconnect();
});

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function goBack() {
	router.push({ name: "money-accounts" });
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(fetchLedger);
watch(activeCompany, fetchLedger);
watch(() => route.params.account, fetchLedger);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2 flex-wrap">
			<button type="button" class="btn btn-sm btn-ghost-secondary" @click="goBack">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
			</button>
			<h3 class="card-title mb-0 d-flex align-items-center gap-2">
				<i class="ti ti-list-details text-secondary"></i>
				{{ accountTitle }}
				<span class="badge bg-blue-lt">{{ accountCurrency }}</span>
			</h3>
			<div class="text-secondary small font-monospace ms-1">{{ accountName }}</div>
		</div>

		<div class="card-body border-bottom">
			<div class="row g-2 align-items-end flex-wrap">
				<div class="col-auto">
					<label class="form-label small mb-1">{{ t("Period") }}</label>
					<PeriodSelect
						v-model="periodKey"
						size="sm"
						@change="onPeriodChange"
					/>
				</div>
				<template v-if="periodKey === 'custom'">
					<div class="col-auto">
						<label class="form-label small mb-1">{{ t("From") }}</label>
						<DateInput v-model="fromDate" size="sm" @blur="fetchLedger" />
					</div>
					<div class="col-auto">
						<label class="form-label small mb-1">{{ t("To") }}</label>
						<DateInput v-model="toDate" size="sm" @blur="fetchLedger" />
					</div>
				</template>
				<div class="col-auto">
					<button
						type="button"
						class="btn btn-sm btn-outline-secondary"
						:disabled="loading"
						@click="fetchLedger"
					>
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
				</div>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<template v-else>
			<!-- Opening / Period / Closing summary -->
			<div class="card-body border-bottom">
				<div class="row g-3">
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Opening") }}</div>
						<div class="font-monospace">
							{{ formatMoney(summary?.opening_balance ?? 0, accountCurrency, user.language) }}
						</div>
					</div>
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Period Debit") }}</div>
						<div class="font-monospace text-green">
							{{ formatMoney(summary?.period_debit ?? 0, accountCurrency, user.language) }}
						</div>
					</div>
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Period Credit") }}</div>
						<div class="font-monospace text-red">
							{{ formatMoney(summary?.period_credit ?? 0, accountCurrency, user.language) }}
						</div>
					</div>
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Closing") }}</div>
						<div class="font-monospace fw-semibold">
							{{ formatMoney(summary?.closing_balance ?? 0, accountCurrency, user.language) }}
						</div>
					</div>
					<div v-if="isMultiCurrency && !usdApplicable" class="col-12">
						<div class="text-secondary small">{{ t("Closing in") }} {{ currency }}</div>
						<div class="font-monospace">
							{{ formatMoney(summary?.closing_balance ?? 0, currency, user.language) }}
						</div>
					</div>
					<!-- USD closing (mutually exclusive with isMultiCurrency block above) -->
					<div v-if="usdApplicable && closingUsd != null" class="col-12">
						<div class="text-secondary small">{{ t("Closing in") }} USD</div>
						<div
							class="font-monospace"
							:title="usdMode === 'book' ? t('GL booked USD (historical cost)') : undefined"
						>{{ usdMode === "book" ? "= " : "≈ " }}{{ formatMoney(closingUsd, "USD", user.language) }}</div>
					</div>
				</div>
			</div>

			<EmptyState
				v-if="!entries.length"
				icon="ti-list-details"
				:title="t('No transactions')"
				:description="t('No ledger entries found for the selected period.')"
			/>
			<div v-else class="table-responsive">
				<table class="table table-sm table-vcenter card-table">
					<thead>
						<tr>
							<th
								style="cursor: pointer; user-select: none; white-space: nowrap"
								@click="toggleDateDir"
							>
								{{ t("Date") }}
								<i
									class="ti ms-1"
									:class="dateDir === 'asc' ? 'ti-chevron-up' : 'ti-chevron-down'"
								></i>
							</th>
							<th>{{ t("Voucher") }}</th>
							<th>{{ t("Against") }}</th>
							<th class="text-end">{{ t("Debit") }}</th>
							<th class="text-end">{{ t("Credit") }}</th>
							<th class="text-end">{{ t("Balance") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="e in entries" :key="e.name">
							<td class="text-nowrap">
							{{ formatDate(e.posting_date) }}
							<div
								v-if="usdApplicable && e.usd_rate"
								class="small text-secondary font-monospace"
								:title="t('USD rate on this date')"
							>
								{{ t("1 USD =") }} {{ formatMoney(e.usd_rate, accountCurrency, user.language) }}
							</div>
						</td>
							<td>
								<div class="small">{{ e.voucher_type }}</div>
								<!-- JE/PE open in a drawer; other docs route to their page -->
								<button
									v-if="canOpen(e)"
									type="button"
									class="btn btn-link p-0 font-monospace small text-decoration-none"
									@click="openVoucher(e)"
								>
									{{ e.voucher_no }}
								</button>
								<div v-else class="font-monospace small text-secondary">{{ e.voucher_no }}</div>
							</td>
							<td class="small">
								<div v-if="e.party" class="text-body">
									<span class="text-secondary me-1">{{ e.party_type }}:</span>{{ e.party_name || e.party }}
								</div>
								<div
									v-else-if="e.against"
									class="text-secondary text-truncate"
									style="max-width: 320px"
									:title="e.against"
								>
									{{ e.against }}
								</div>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="text-end font-monospace">
								<span v-if="Number(e.debit_in_account_currency) > 0">
									{{ formatMoney(e.debit_in_account_currency, accountCurrency, user.language) }}
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="text-end font-monospace">
								<span v-if="Number(e.credit_in_account_currency) > 0">
									{{ formatMoney(e.credit_in_account_currency, accountCurrency, user.language) }}
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="text-end font-monospace fw-semibold">
								{{ formatMoney(e.running_balance, accountCurrency, user.language) }}
								<div
									v-if="usdApplicable"
									class="small fw-normal text-secondary"
									:title="usdMode === 'book' ? t('GL booked USD (historical cost)') : undefined"
								>
									<template v-if="e.running_balance_usd != null">
										{{ usdMode === "book" ? "= " : "≈ " }}{{ formatMoney(e.running_balance_usd, "USD", user.language) }}
										<template v-if="usdMode === 'book'">
											<span
												v-if="e.fx_check === 'ok'"
												class="text-success ms-1"
												:title="t('FX rate looks correct')"
											>✓</span>
											<span
												v-else-if="e.fx_check === 'warn'"
												class="text-warning fw-bold ms-1"
												:title="t('FX rate looks wrong') + ' — ' + t('Expected') + ' ≈ ' + formatMoney(e.fx_expected_usd, 'USD', user.language)"
											>⚠</span>
										</template>
									</template>
									<template v-else>—</template>
								</div>
							</td>
						</tr>
					</tbody>
				</table>

				<!-- Infinite-scroll sentinel + load-more affordance -->
				<div ref="sentinel" class="py-1">
					<div v-if="loadingMore" class="text-center py-3">
						<div class="spinner-border spinner-border-sm text-secondary" role="status"></div>
						<span class="ms-2 small text-secondary">{{ t("Loading more…") }}</span>
					</div>
					<div v-else-if="!hasMore && entries.length > 0" class="text-center py-2">
						<span class="small text-secondary">
							{{ t("End of ledger") }} · {{ entries.length.toLocaleString() }}
							{{ t("entries") }}
						</span>
					</div>
				</div>
			</div>
		</template>
	</div>

	<!-- In-place voucher detail drawer -->
	<VoucherDrawer
		:open="drawerOpen"
		:loading="drawerLoading"
		:detail="drawerDetail"
		:currency="currency"
		@close="closeDrawer"
	/>
</template>
