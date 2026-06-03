<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import { t } from "../../composables/i18n.js";
import { computeRunning } from "../../composables/ledger.js";
import EmptyState from "../../components/EmptyState.vue";

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

const LEDGER_LIMIT = 2000; // backend clamps to this same max (money.py:69)

const loading = ref(false);
const error = ref("");
const entries = ref([]);
const closingBase = ref(0);
const closingAcc = ref(0);
const summary = ref(null);
const fromDate = ref("");
const toDate = ref("");

const accountCurrency = computed(() => summary.value?.account_currency || currency.value);
const accountTitle = computed(() => summary.value?.account_name || accountName.value);
const isMultiCurrency = computed(
	() => accountCurrency.value && accountCurrency.value !== currency.value
);

const VOUCHER_ROUTES = {
	"Journal Entry": "/money/journals",
	"Payment Entry": "/money/payments",
	"Sales Invoice": "/sales/invoices",
	"Purchase Invoice": "/purchasing/invoices",
};

function voucherLinkTo(entry) {
	const path = VOUCHER_ROUTES[entry?.voucher_type];
	if (!path || !entry?.voucher_no) return null;
	return { path, query: { open: entry.voucher_no } };
}

async function fetchLedger() {
	if (!accountName.value) return;
	loading.value = true;
	error.value = "";
	entries.value = [];
	summary.value = null;
	try {
		const params = {
			company: activeCompany.value,
			account: accountName.value,
			limit: LEDGER_LIMIT,
		};
		if (fromDate.value) params.from_date = fromDate.value;
		if (toDate.value) params.to_date = toDate.value;
		const [entriesRes, summaryRes] = await Promise.all([
			call("stabler.api.money.gl_entries", params),
			call("stabler.api.money.account_summary", params),
		]);
		closingBase.value = entriesRes.closing_base || 0;
		closingAcc.value = entriesRes.closing_account || 0;
		summary.value = summaryRes;
		entries.value = computeRunning(
			entriesRes.entries || [],
			entriesRes.closing_account || 0,
			entriesRes.closing_base || 0
		);
	} catch (err) {
		error.value = err?.message || t("Failed to load ledger.");
	} finally {
		loading.value = false;
	}
}

function goBack() {
	router.push({ name: "money-accounts" });
}

const dateDir = ref("desc"); // desc = newest first (matches API order)

function toggleDateDir() {
	dateDir.value = dateDir.value === "desc" ? "asc" : "desc";
}

// entries from API are already in DESC order with running_balance attached per row.
// Reversing for ASC display is safe — running_balance is a per-entry property,
// not a positional value, so it stays correct in either direction.
const sortedEntries = computed(() =>
	dateDir.value === "desc" ? entries.value : [...entries.value].reverse()
);

// Show a warning when the result was capped — fail loud (Rule 12).
const truncated = computed(() => entries.value.length >= LEDGER_LIMIT);

onMounted(fetchLedger);
watch(activeCompany, fetchLedger);
watch(
	() => route.params.account,
	fetchLedger
);
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
			<div class="row g-2 align-items-end">
				<div class="col-auto">
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" @blur="fetchLedger" />
				</div>
				<div class="col-auto">
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" @blur="fetchLedger" />
				</div>
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
							{{ formatMoney(summary?.closing_balance ?? closingAcc, accountCurrency, user.language) }}
						</div>
					</div>
					<div v-if="isMultiCurrency" class="col-12">
						<div class="text-secondary small">{{ t("Closing in") }} {{ currency }}</div>
						<div class="font-monospace">
							{{ formatMoney(closingBase, currency, user.language) }}
						</div>
					</div>
				</div>
			</div>

			<div v-if="truncated" class="card-body py-2">
				<div class="alert alert-warning d-flex align-items-center m-0 py-2">
					<i class="ti ti-alert-triangle me-2"></i>
					<div class="small">
						{{ t("Showing the newest") }} {{ LEDGER_LIMIT }}
						{{ t("entries. Narrow the date range to see older ones.") }}
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
								<i class="ti ms-1" :class="dateDir === 'asc' ? 'ti-chevron-up' : 'ti-chevron-down'"></i>
							</th>
							<th>{{ t("Voucher") }}</th>
							<th>{{ t("Against") }}</th>
							<th class="text-end">{{ t("Debit") }}</th>
							<th class="text-end">{{ t("Credit") }}</th>
							<th class="text-end">{{ t("Balance") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="e in sortedEntries" :key="e.name">
							<td class="text-nowrap">{{ formatDate(e.posting_date) }}</td>
							<td>
								<div class="small">{{ e.voucher_type }}</div>
								<router-link
									v-if="voucherLinkTo(e)"
									:to="voucherLinkTo(e)"
									class="font-monospace small text-decoration-none"
								>
									{{ e.voucher_no }}
								</router-link>
								<div v-else class="font-monospace small text-secondary">{{ e.voucher_no }}</div>
							</td>
							<td class="small">
								<div v-if="e.party" class="text-body">
									<span class="text-secondary me-1">{{ e.party_type }}:</span>{{ e.party }}
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
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</template>
	</div>
</template>
