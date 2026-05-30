<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import DateInput from "../../components/DateInput.vue";
import { t } from "../../composables/i18n.js";
import { computeRunning } from "../../composables/ledger.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const flat = ref([]);
const expanded = ref(new Set());
const balances = ref(new Map());
const balancesLoading = ref(false);
const search = ref("");

const ROOT_ICONS = {
	Asset: "ti-building-bank",
	Liability: "ti-receipt",
	Equity: "ti-shield-check",
	Income: "ti-trending-up",
	Expense: "ti-trending-down",
};

const tree = computed(() => {
	const byParent = new Map();
	for (const a of flat.value) {
		const k = a.parent_account || "__ROOT__";
		if (!byParent.has(k)) byParent.set(k, []);
		byParent.get(k).push(a);
	}
	function build(parentKey, depth) {
		const list = byParent.get(parentKey) || [];
		return list.map((node) => ({
			...node,
			depth,
			children: node.is_group ? build(node.name, depth + 1) : [],
		}));
	}
	return build("__ROOT__", 0);
});

const flattened = computed(() => {
	const out = [];
	const term = search.value.trim().toLowerCase();
	const matchesTerm = (n) =>
		!term ||
		(n.account_name || "").toLowerCase().includes(term) ||
		(n.name || "").toLowerCase().includes(term);
	function walk(node) {
		const expandedNow = term ? true : expanded.value.has(node.name);
		const matched = matchesTerm(node);
		if (matched || !term) out.push(node);
		if (expandedNow && node.children?.length) {
			for (const c of node.children) walk(c);
		}
	}
	for (const r of tree.value) walk(r);
	if (!term) return out;
	return out.filter(matchesTerm);
});

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const rows = await call("stabler.api.money.chart_of_accounts", {
			company: activeCompany.value,
		});
		flat.value = rows || [];
		// Expand every group by default — users want the full tree visible
		// without clicking. Search/collapse still works per-node.
		expanded.value = new Set(
			(rows || []).filter((r) => r.is_group).map((r) => r.name)
		);
		balances.value = new Map();
	} catch (err) {
		error.value = err?.message || "Failed to load chart of accounts.";
	} finally {
		loading.value = false;
	}
}

async function loadAllVisibleBalances() {
	const targets = flattened.value.filter((n) => !n.is_group);
	await Promise.all(targets.map((n) => loadBalance(n.name, { force: false })));
}

async function refreshAllBalances() {
	balancesLoading.value = true;
	try {
		const targets = flattened.value.filter((n) => !n.is_group);
		await Promise.all(targets.map((n) => loadBalance(n.name, { force: true })));
	} finally {
		balancesLoading.value = false;
	}
}

function toggle(name) {
	const next = new Set(expanded.value);
	if (next.has(name)) next.delete(name);
	else next.add(name);
	expanded.value = next;
}

async function loadBalance(account, { force = false } = {}) {
	if (!force && balances.value.has(account)) return;
	try {
		const res = await call("stabler.api.money.account_balance", {
			company: activeCompany.value,
			account,
		});
		const next = new Map(balances.value);
		next.set(account, {
			base: res.balance_base,
			acc: res.balance_acc,
			account_currency: res.account_currency,
			company_currency: res.company_currency,
		});
		balances.value = next;
	} catch {
		/* leave undefined */
	}
}

// --- Ledger drawer ---------------------------------------------------------

const detailOpen = ref(false);
const detailLoading = ref(false);
const detailError = ref("");
const detailAccount = ref(null);
const detailEntries = ref([]);
const detailClosingBase = ref(0);
const detailClosingAcc = ref(0);
const detailSummary = ref(null);
const detailFromDate = ref("");
const detailToDate = ref("");

const detailAccountCurrency = computed(
	() => detailAccount.value?.account_currency || currency.value
);

const isMultiCurrency = computed(
	() => detailAccountCurrency.value && detailAccountCurrency.value !== currency.value
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

function defaultDateRange() {
	const to = new Date();
	const from = new Date();
	from.setDate(from.getDate() - 90);
	const iso = (d) => d.toISOString().slice(0, 10);
	return { from: iso(from), to: iso(to) };
}

async function openLedger(node) {
	if (!node || node.is_group) return;
	detailAccount.value = node;
	detailOpen.value = true;
	const range = defaultDateRange();
	detailFromDate.value = range.from;
	detailToDate.value = range.to;
	await fetchLedger();
}

async function fetchLedger() {
	if (!detailAccount.value) return;
	detailLoading.value = true;
	detailError.value = "";
	detailEntries.value = [];
	detailSummary.value = null;
	try {
		const params = {
			company: activeCompany.value,
			account: detailAccount.value.name,
			limit: 500,
		};
		if (detailFromDate.value) params.from_date = detailFromDate.value;
		if (detailToDate.value) params.to_date = detailToDate.value;
		const [entriesRes, summaryRes] = await Promise.all([
			call("stabler.api.money.gl_entries", params),
			call("stabler.api.money.account_summary", params),
		]);
		detailClosingBase.value = entriesRes.closing_base || 0;
		detailClosingAcc.value = entriesRes.closing_account || 0;
		detailSummary.value = summaryRes;
		detailEntries.value = computeRunning(
			entriesRes.entries || [],
			entriesRes.closing_account || 0,
			entriesRes.closing_base || 0
		);
		const next = new Map(balances.value);
		next.set(detailAccount.value.name, {
			base: detailClosingBase.value,
			acc: detailClosingAcc.value,
			account_currency: detailAccountCurrency.value,
			company_currency: currency.value,
		});
		balances.value = next;
	} catch (err) {
		detailError.value = err?.message || t("Failed to load ledger.");
	} finally {
		detailLoading.value = false;
	}
}

function closeLedger() {
	detailOpen.value = false;
	detailAccount.value = null;
	detailEntries.value = [];
	detailSummary.value = null;
}

function rootIcon(t) {
	return ROOT_ICONS[t] || "ti-circle";
}

onMounted(async () => {
	await load();
	await loadAllVisibleBalances();
});
watch(activeCompany, async () => {
	await load();
	await loadAllVisibleBalances();
});
// Lazy-load balances for any newly-revealed rows when user expands a group.
watch(flattened, (rows) => {
	const todo = rows.filter((n) => !n.is_group && !balances.value.has(n.name));
	if (todo.length) {
		for (const n of todo) loadBalance(n.name);
	}
});
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Chart of Accounts") }}</div>
			<button
				type="button"
				class="btn btn-sm btn-outline-secondary ms-2"
				:disabled="balancesLoading"
				@click="refreshAllBalances"
				:title="t('Re-fetch balances for all visible accounts')"
			>
				<span v-if="balancesLoading" class="spinner-border spinner-border-sm me-1"></span>
				<i v-else class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
			<div class="ms-auto" style="max-width: 320px; width: 100%">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					:placeholder="t('Search account…')"
				/>
			</div>
		</div>
		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!flat.length"
			icon="ti-list-tree"
			accentIcon="ti-coin"
			tone="primary"
			title="No accounts yet"
			:subtitle="`Set up the chart of accounts for ${activeCompany} to see it here.`"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Account") }}</th>
						<th class="w-1">{{ t("Type") }}</th>
						<th class="w-1 text-end text-nowrap">{{ t("Balance (Account Currency)") }}</th>
						<th class="w-1 text-end text-nowrap">{{ t("Balance") }} ({{ currency }})</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="n in flattened"
						:key="n.name"
						:class="{ 'cursor-pointer': !n.is_group }"
						:style="!n.is_group ? 'cursor: pointer;' : null"
						@click="!n.is_group && openLedger(n)"
					>
						<td>
							<div
								class="d-flex align-items-center gap-1"
								:style="{ paddingLeft: `${n.depth * 1.25}rem` }"
							>
								<button
									v-if="n.is_group"
									type="button"
									class="btn btn-icon btn-sm btn-ghost-secondary"
									@click.stop="toggle(n.name)"
									:aria-label="expanded.has(n.name) ? 'Collapse' : 'Expand'"
								>
									<i class="ti" :class="expanded.has(n.name) ? 'ti-chevron-down' : 'ti-chevron-right'"></i>
								</button>
								<span v-else class="d-inline-block" style="width: 1.75rem"></span>
								<i class="ti me-1 text-secondary" :class="rootIcon(n.root_type)"></i>
								<span v-if="n.is_group" class="fw-semibold">
									<span v-if="n.account_number" class="text-secondary me-1">{{ n.account_number }}</span>
									{{ n.account_name || n.name }}
								</span>
								<a
									v-else
									href="#"
									class="link-body-emphasis text-decoration-none"
									:title="t('View ledger')"
									@click.stop.prevent="openLedger(n)"
								>
									<span v-if="n.account_number" class="text-secondary me-1">{{ n.account_number }}</span>
									{{ n.account_name || n.name }}
								</a>
							</div>
						</td>
						<td>
							<span class="badge bg-secondary-lt">{{ n.root_type || "—" }}</span>
							<span v-if="n.account_type" class="badge bg-blue-lt ms-1">{{ n.account_type }}</span>
						</td>
						<td class="text-end font-monospace">
							<span v-if="n.is_group" class="text-secondary">—</span>
							<span v-else-if="balances.has(n.name) && balances.get(n.name).acc !== null">
								{{ formatMoney(balances.get(n.name).acc, balances.get(n.name).account_currency || n.account_currency || currency, user.language) }}
							</span>
							<span v-else-if="balances.has(n.name)" class="text-secondary">—</span>
							<span v-else class="text-secondary placeholder-glow">
								<span class="placeholder col-6"></span>
							</span>
						</td>
						<td class="text-end font-monospace">
							<span v-if="balances.has(n.name)">
								{{ formatMoney(balances.get(n.name).base, balances.get(n.name).company_currency || currency, user.language) }}
							</span>
							<span v-else-if="n.is_group" class="text-secondary">—</span>
							<span v-else class="text-secondary placeholder-glow">
								<span class="placeholder col-6"></span>
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Ledger drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeLedger"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 760px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title d-flex align-items-center gap-2 flex-wrap">
				<i class="ti ti-list-details me-1"></i>
				<span>{{ detailAccount?.account_name || detailAccount?.name }}</span>
				<span class="badge bg-blue-lt">{{ detailAccountCurrency }}</span>
				<div class="w-100 text-secondary small font-monospace">{{ detailAccount?.name }}</div>
			</h5>
			<button type="button" class="btn-close" @click="closeLedger"></button>
		</div>
		<div class="offcanvas-body">
			<div class="row g-2 mb-3 align-items-end">
				<div class="col-auto">
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput
						v-model="detailFromDate"
						size="sm"
						@blur="fetchLedger"
					/>
				</div>
				<div class="col-auto">
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput
						v-model="detailToDate"
						size="sm"
						@blur="fetchLedger"
					/>
				</div>
				<div class="col-auto">
					<button
						type="button"
						class="btn btn-sm btn-outline-secondary"
						@click="fetchLedger"
						:disabled="detailLoading"
					>
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
				</div>
			</div>

			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detailError" class="alert alert-danger">{{ detailError }}</div>
			<template v-else>
				<div class="row g-2 mb-3">
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Opening") }}</div>
						<div class="font-monospace">
							{{ formatMoney(detailSummary?.opening_balance ?? 0, detailAccountCurrency, user.language) }}
						</div>
					</div>
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Period Debit") }}</div>
						<div class="font-monospace text-green">
							{{ formatMoney(detailSummary?.period_debit ?? 0, detailAccountCurrency, user.language) }}
						</div>
					</div>
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Period Credit") }}</div>
						<div class="font-monospace text-red">
							{{ formatMoney(detailSummary?.period_credit ?? 0, detailAccountCurrency, user.language) }}
						</div>
					</div>
					<div class="col-6 col-md-3">
						<div class="text-secondary small">{{ t("Closing") }}</div>
						<div class="font-monospace fw-semibold">
							{{ formatMoney(detailSummary?.closing_balance ?? detailClosingAcc, detailAccountCurrency, user.language) }}
						</div>
					</div>
					<div v-if="isMultiCurrency" class="col-12">
						<div class="text-secondary small">{{ t("Closing in") }} {{ currency }}</div>
						<div class="font-monospace">
							{{ formatMoney(detailClosingBase, currency, user.language) }}
						</div>
					</div>
				</div>

				<div v-if="!detailEntries.length" class="text-secondary text-center py-4">
					{{ t("No transactions yet.") }}
				</div>
				<div v-else class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Date") }}</th>
								<th>{{ t("Voucher") }}</th>
								<th>{{ t("Against") }}</th>
								<th class="text-end">{{ t("Debit") }}</th>
								<th class="text-end">{{ t("Credit") }}</th>
								<th class="text-end">{{ t("Balance") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="e in detailEntries" :key="e.name">
								<td class="text-nowrap">{{ formatDateTime(`${e.posting_date} ${e.posting_time}`) }}</td>
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
									<div v-else-if="e.against" class="text-secondary text-truncate" style="max-width: 220px" :title="e.against">
										{{ e.against }}
									</div>
									<span v-else class="text-secondary">—</span>
								</td>
								<td class="text-end font-monospace">
									<span v-if="Number(e.debit_in_account_currency) > 0">
										{{ formatMoney(e.debit_in_account_currency, detailAccountCurrency, user.language) }}
									</span>
									<span v-else class="text-secondary">—</span>
								</td>
								<td class="text-end font-monospace">
									<span v-if="Number(e.credit_in_account_currency) > 0">
										{{ formatMoney(e.credit_in_account_currency, detailAccountCurrency, user.language) }}
									</span>
									<span v-else class="text-secondary">—</span>
								</td>
								<td class="text-end font-monospace fw-semibold">
									{{ formatMoney(e.running_balance, detailAccountCurrency, user.language) }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</template>
		</div>
	</div>
</template>
