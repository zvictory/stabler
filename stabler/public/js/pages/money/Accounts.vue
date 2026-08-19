<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import {
	accountAncestorPath,
	accountLabel,
	accountOptionPath,
	accountTypeLabel,
	applyRootTypeSign,
	defaultExpandedGroups,
	isAbnormalBalance,
	matchesAccountSearch,
	newAccountCurrency,
} from "../../composables/accounts.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();
const { confirm } = useConfirm();
const toast = useToast();

useEscapeBack(() => {
	if (createOpen.value) {
		closeCreate();
		return true;
	}
	return false;
}, "/money");

const loading = ref(false);
const error = ref("");
const flat = ref([]);
const expanded = ref(new Set());
const balances = ref(new Map());
const balancesLoading = ref(false);
// The date chart_balances actually priced its numbers as of. The endpoint
// already supports an `as_of` request param, but there is no UI here to pick
// one (that's a separate feature) — so rather than have the frontend guess
// its own "today" and risk a client/server clock/timezone mismatch, the
// header shows the date the SERVER used, echoed straight back in the response.
const asOfDate = ref("");
const search = ref("");
const includeDisabled = ref(false);

const ACCOUNT_TYPES = [
	"Accumulated Depreciation",
	"Asset Received But Not Billed",
	"Bank",
	"Cash",
	"Chargeable",
	"Capital Work in Progress",
	"Cost of Goods Sold",
	"Current Asset",
	"Current Liability",
	"Depreciation",
	"Direct Expense",
	"Direct Income",
	"Equity",
	"Expense Account",
	"Expenses Included In Asset Valuation",
	"Expenses Included In Valuation",
	"Fixed Asset",
	"Income Account",
	"Indirect Expense",
	"Indirect Income",
	"Liability",
	"Payable",
	"Receivable",
	"Round Off",
	"Round Off for Opening",
	"Stock",
	"Stock Adjustment",
	"Stock Received But Not Billed",
	"Service Received But Not Billed",
	"Tax",
	"Temporary",
];

// Fixed English enum from ERPNext, so it belongs in the catalogues like any
// other label. Select accepts {value,label} as readily as a bare string.
const ACCOUNT_TYPE_OPTIONS = computed(() => ACCOUNT_TYPES.map((value) => ({ value, label: accountTypeLabel(value) })));

const createOpen = ref(false);
const editMode = ref(false);
const editingName = ref("");
const submitting = ref(false);
const submitError = ref("");
const currencyOptions = ref([]);
const optionsLoaded = ref(false);

function blankAccount() {
	return {
		account_name: "",
		account_number: "",
		parent_account: "",
		is_group: 0,
		account_type: "",
		account_currency: "",
		opening_balance: null,
		opening_date: "",
	};
}
const form = ref(blankAccount());

const ROOT_ICONS = {
	Asset: "ti-building-bank",
	Liability: "ti-receipt",
	Equity: "ti-shield-check",
	Income: "ti-trending-up",
	Expense: "ti-trending-down",
};

const ROOT_COLORS = {
	Asset: "text-green",
	Liability: "text-red",
	Equity: "text-purple",
	Income: "text-teal",
	Expense: "text-orange",
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

// Flat account list keyed by name, for accountAncestorPath's parent-chain
// walk — the tree computed above already threw the parent chain away.
const accountsByName = computed(() => Object.fromEntries(flat.value.map((a) => [a.name, a])));

const searchActive = computed(() => search.value.trim().length > 0);

const flattened = computed(() => {
	const out = [];
	const term = search.value.trim().toLowerCase();
	const matchesTerm = (n) => matchesAccountSearch(n, term);
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

const parentAccountOptions = computed(() =>
	flat.value
		.filter((r) => r.is_group && r.name !== editingName.value)
		.map((r) => ({ value: r.name, label: accountOptionPath(r, accountsByName.value) }))
);

// Contextualizes the modal — "New account in Assets › Bank Accounts" — rather
// than a generic title that never says which group a click on the tree's "+"
// (or a parent picked inside the modal) is about to add into.
const createModalTitle = computed(() => {
	if (editMode.value) return t("Edit account");
	const parent = form.value.parent_account
		? flat.value.find((r) => r.name === form.value.parent_account)
		: null;
	if (parent) return t("New account in {parent}", { parent: accountLabel(parent) });
	return t("New account");
});

// Session-scoped, per-company: the user's expand/collapse choices survive a
// reload within the same tab session without leaking between companies or
// outliving the browser session (unlike localStorage).
function expandedStorageKey(company) {
	return `stabler:coa:expanded:${company}`;
}

function restoreExpanded(company) {
	try {
		const raw = sessionStorage.getItem(expandedStorageKey(company));
		return raw ? new Set(JSON.parse(raw)) : null;
	} catch {
		return null;
	}
}

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const rows = await call("stabler.api.money.chart_of_accounts", {
			company: activeCompany.value,
			include_disabled: includeDisabled.value ? 1 : 0,
		});
		flat.value = rows || [];
		// First load: roots only, so the tree opens navigable instead of as a
		// wall of every account at once. A returning user's own expand/collapse
		// choices for this company (if any were saved) win over that default.
		expanded.value = restoreExpanded(activeCompany.value) || defaultExpandedGroups(rows || []);
		balances.value = new Map();
	} catch (err) {
		error.value = err?.message || t("Failed to load chart of accounts.");
	} finally {
		loading.value = false;
	}
}

async function loadBalances() {
	if (!activeCompany.value) return;
	balancesLoading.value = true;
	try {
		const res = await call("stabler.api.money.chart_balances", {
			company: activeCompany.value,
		});
		const cc = res.company_currency || currency.value;
		const next = new Map();
		for (const [name, b] of Object.entries(res.balances || {})) {
			next.set(name, { base: b.base, acc: b.acc, account_currency: b.account_currency, company_currency: cc });
		}
		balances.value = next;
		asOfDate.value = res.as_of || "";
	} catch {
		balances.value = new Map();
	} finally {
		balancesLoading.value = false;
	}
}

async function refreshAllBalances() {
	await loadBalances();
}

// --- balance presentation -------------------------------------------------
// House rule: show the amount in the account's own currency. The base-currency
// figure is only a hint, and only when the two actually differ — otherwise it
// is the same number printed twice.

function accCurrencyOf(n) {
	const b = balances.value.get(n.name);
	return (b && b.account_currency) || n.account_currency || currency.value;
}

function baseCurrencyOf(n) {
	const b = balances.value.get(n.name);
	return (b && b.company_currency) || currency.value;
}

/** Numeric value shown on the main line. Groups roll up in base currency. */
function primaryValue(n) {
	const b = balances.value.get(n.name);
	if (!b) return null;
	if (!n.is_group && b.acc !== null && b.acc !== undefined) return b.acc;
	return b.base;
}

/**
 * account_summary/chart_balances return raw SUM(debit - credit), which reads
 * negative for a perfectly normal Liability/Equity/Income balance. Sign is
 * interpreted here, at the point of display — never in the raw value the rest
 * of this file computes with (isNegative/abnormal checks below un-flip it).
 */
function displayValue(n) {
	return applyRootTypeSign(primaryValue(n), n.root_type);
}

function primaryBalance(n) {
	const v = displayValue(n);
	if (v === null || v === undefined) return "—";
	const ccy = !n.is_group && balances.value.get(n.name).acc !== null ? accCurrencyOf(n) : baseCurrencyOf(n);
	return formatMoney(v, ccy, user.value.language);
}

/** Only worth printing when the account is genuinely in a foreign currency. */
function showBaseHint(n) {
	const b = balances.value.get(n.name);
	if (!b || n.is_group || b.acc === null || b.acc === undefined) return false;
	return accCurrencyOf(n) !== baseCurrencyOf(n);
}

/** The base-currency hint line, same root-type sign flip as the main line. */
function baseHintValue(n) {
	const b = balances.value.get(n.name);
	return b ? applyRootTypeSign(b.base, n.root_type) : null;
}

/**
 * Red is reserved for a balance that is still negative AFTER the root-type
 * sign flip — genuinely abnormal for its own root type (an overdrawn asset, a
 * debit-balance payable, a loss-making income account). Group rows are never
 * colored: a roll-up mixing normal and abnormal children isn't itself
 * abnormal, and painting every Liability/Equity/Income branch red regardless
 * of root type was the whole complaint this replaces.
 */
function isNegative(n) {
	if (n.is_group) return false;
	return isAbnormalBalance(primaryValue(n), n.root_type);
}

function toggle(name) {
	const next = new Set(expanded.value);
	if (next.has(name)) next.delete(name);
	else next.add(name);
	expanded.value = next;
}

function openLedger(node) {
	if (!node || node.is_group) return;
	router.push({ name: "money-account-ledger", params: { account: node.name } });
}

function rootIcon(t) {
	return ROOT_ICONS[t] || "ti-circle";
}

function rootColor(t) {
	return ROOT_COLORS[t] || "text-secondary";
}

function expandAll() {
	expanded.value = new Set(flat.value.filter((r) => r.is_group).map((r) => r.name));
}

function collapseAll() {
	expanded.value = new Set();
}

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const rows = await call("stabler.api.sales.list_currencies");
		currencyOptions.value = (rows || []).map((c) => ({ value: c.name, label: c.name }));
		optionsLoaded.value = true;
	} catch {
		currencyOptions.value = [];
	}
}

function openCreate(parentNode) {
	editMode.value = false;
	editingName.value = "";
	submitError.value = "";
	form.value = blankAccount();
	if (parentNode?.is_group) form.value.parent_account = parentNode.name;
	// Name the currency now rather than letting the amount field substitute one.
	// The select used to read "—" while the field below it behaved as UZS, and a
	// USD amount typed before the currency was picked lost its decimals on blur.
	form.value.account_currency = newAccountCurrency(parentNode, currency.value);
	loadCreateOptions();
	createOpen.value = true;
}

function closeCreate() {
	createOpen.value = false;
	submitError.value = "";
	form.value = blankAccount();
	editMode.value = false;
	editingName.value = "";
}

async function openEdit(node) {
	if (!node || node.is_group === undefined) return;
	editMode.value = true;
	editingName.value = node.name;
	submitError.value = "";
	loadCreateOptions();
	createOpen.value = true;
	try {
		const doc = await call("stabler.api.money.get_account", { name: node.name });
		form.value = {
			account_name: doc.account_name || "",
			account_number: doc.account_number || "",
			parent_account: doc.parent_account || "",
			is_group: doc.is_group ? 1 : 0,
			account_type: doc.account_type || "",
			account_currency: doc.account_currency || "",
			opening_balance: null,
			opening_date: "",
		};
	} catch (err) {
		submitError.value = err?.message || t("Failed to load account.");
	}
}

async function submitForm() {
	submitting.value = true;
	submitError.value = "";
	try {
		if (editMode.value) {
			await call("stabler.api.money.update_account", {
				name: editingName.value,
				account_name: form.value.account_name,
				account_number: form.value.account_number || null,
				account_type: form.value.account_type || null,
				account_currency: form.value.account_currency || null,
				parent_account: form.value.parent_account || null,
			});
			toast.success(t("Account updated."));
		} else {
			await call("stabler.api.money.create_account", {
				company: activeCompany.value,
				account_name: form.value.account_name,
				parent_account: form.value.parent_account,
				account_number: form.value.account_number || null,
				is_group: form.value.is_group ? 1 : 0,
				account_type: form.value.account_type || null,
				account_currency: form.value.account_currency || null,
				opening_balance: form.value.opening_balance || 0,
				opening_date: form.value.opening_date || null,
			});
			toast.success(t("Account created."));
		}
		closeCreate();
		await load();
		await loadBalances();
	} catch (err) {
		submitError.value = err?.message || t("Failed to save account.");
	} finally {
		submitting.value = false;
	}
}

async function toggleDisabled(node) {
	const willDisable = !node.disabled;
	const ok = await confirm({
		title: willDisable ? t("Disable account?") : t("Enable account?"),
		message: willDisable
			? t("This account will be hidden from the active chart of accounts.")
			: t("This account will be shown in the active chart of accounts again."),
		confirmLabel: willDisable ? t("Disable") : t("Enable"),
	});
	if (!ok) return;
	try {
		await call("stabler.api.money.set_account_disabled", {
			name: node.name,
			disabled: willDisable ? 1 : 0,
		});
		toast.success(willDisable ? t("Account disabled.") : t("Account enabled."));
		await load();
		await loadBalances();
	} catch (err) {
		toast.error(err?.message || t("Failed to update account."));
	}
}

onMounted(async () => {
	await load();
	await loadBalances();
});
watch(activeCompany, async () => {
	await load();
	await loadBalances();
});
watch(includeDisabled, async () => {
	await load();
});
watch(expanded, (next) => {
	if (!activeCompany.value) return;
	try {
		sessionStorage.setItem(expandedStorageKey(activeCompany.value), JSON.stringify([...next]));
	} catch {
		// sessionStorage can throw (private browsing, quota) — expansion just
		// won't be remembered next reload, which is the pre-existing behavior.
	}
});
</script>
<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2 flex-wrap">
			<div class="card-title m-0">{{ t("Chart of Accounts") }}</div>
			<button
				type="button"
				class="btn btn-sm btn-outline-secondary ms-2"
				:disabled="balancesLoading"
				@click="refreshAllBalances"
				:title="t('Re-fetch balances for all accounts')"
			>
				<span v-if="balancesLoading" class="spinner-border spinner-border-sm me-1"></span>
				<i v-else class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
			</button>
			<button
				type="button"
				class="btn btn-sm btn-ghost-secondary"
				@click="expandAll"
				:title="t('Expand all groups')"
			>
				<i class="ti ti-fold-down me-1"></i>{{ t("Expand all") }}
			</button>
			<button
				type="button"
				class="btn btn-sm btn-ghost-secondary"
				@click="collapseAll"
				:title="t('Collapse all groups')"
			>
				<i class="ti ti-fold me-1"></i>{{ t("Collapse all") }}
			</button>
			<div class="form-check m-0 ms-2">
				<input
					v-model="includeDisabled"
					type="checkbox"
					class="form-check-input"
					id="include_disabled"
				/>
				<label class="form-check-label text-nowrap" for="include_disabled">
					{{ t("Include disabled") }}
				</label>
			</div>
			<div class="ms-auto d-flex align-items-center gap-2" style="max-width: 420px; width: 100%">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					:placeholder="t('Search account…')"
				/>
				<button type="button" class="btn btn-primary btn-sm flex-shrink-0" @click="openCreate()">
					<i class="ti ti-plus me-1"></i>{{ t("New account") }}
				</button>
			</div>
		</div>
		<div v-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!loading && !flat.length"
			icon="ti-list-tree"
			accentIcon="ti-coin"
			tone="primary"
			:title="t('No accounts yet')"
			:subtitle="t('Set up the chart of accounts for {company} to see it here.', { company: activeCompany })"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th class="w-1 text-nowrap">{{ t("Code") }}</th>
						<th>{{ t("Account") }}</th>
						<th class="w-1 text-end text-nowrap">
							<div>{{ t("Balance") }}</div>
							<div v-if="asOfDate" class="small text-secondary fw-normal">
								{{ t("as of {date}", { date: formatDate(asOfDate) }) }}
							</div>
						</th>
						<th class="w-1 text-end">{{ t("Actions") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="10" :cols="4" />
				<tbody v-else>
					<tr
						v-for="n in flattened"
						:key="n.name"
						:class="{ 'cursor-pointer': !n.is_group }"
						:style="!n.is_group ? 'cursor: pointer;' : null"
						@click="!n.is_group && openLedger(n)"
					>
						<td class="font-monospace text-secondary text-nowrap coa-code">
							{{ n.account_number || "" }}
						</td>
						<td>
							<div
								class="d-flex align-items-center gap-1"
								:style="{ paddingLeft: searchActive ? '0' : `${n.depth * 1.25}rem` }"
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
								<i class="ti me-1" :class="[rootIcon(n.root_type), rootColor(n.root_type)]"></i>
								<span v-if="n.is_group" class="fw-semibold" :class="{ 'text-muted': n.disabled }">
									{{ accountLabel(n) }}
								</span>
								<a
									v-else
									href="#"
									class="link-body-emphasis text-decoration-none"
									:class="{ 'text-muted': n.disabled }"
									:title="t('View ledger')"
									@click.stop.prevent="openLedger(n)"
								>
									{{ accountLabel(n) }}
								</a>
								<span v-if="n.disabled" class="badge bg-secondary-lt ms-2">{{ t("Disabled") }}</span>
							</div>
							<!-- Search flattens the tree and drops non-matching ancestors, so the
							     row's indentation stops meaning anything (zeroed above). This is
							     what tells three same-named "Kassa" results apart. -->
							<div
								v-if="searchActive && accountAncestorPath(n, accountsByName)"
								class="small text-secondary"
							>
								{{ accountAncestorPath(n, accountsByName) }}
							</div>
							<!-- account_type used to be its own column, but a long translated
							     type (e.g. "Stock Received But Not Billed" in Russian) squeezed
							     the tree instead of the columns with room to spare. -->
							<div
								v-if="n.account_type"
								class="small text-secondary"
								:style="{ paddingLeft: searchActive ? '0' : `${n.depth * 1.25}rem` }"
							>
								{{ accountTypeLabel(n.account_type) }}
							</div>
						</td>
						<td
							class="text-end font-monospace text-nowrap coa-amount"
							:class="{ 'fw-bold': n.is_group, 'text-danger': isNegative(n) }"
						>
							<template v-if="balances.has(n.name)">
								<div class="d-flex align-items-center justify-content-end gap-1">
									<span>{{ primaryBalance(n) }}</span>
									<span
										v-if="n.is_group"
										class="badge bg-secondary-lt fw-normal"
										:title="t('Roll-up of sub-accounts, converted to the company currency.')"
									>
										{{ baseCurrencyOf(n) }}
									</span>
								</div>
								<div v-if="showBaseHint(n)" class="small text-secondary fw-normal">
									≈ {{ formatMoney(baseHintValue(n), balances.get(n.name).company_currency || currency, user.language) }}
								</div>
							</template>
							<span v-else-if="n.is_group" class="text-secondary">—</span>
							<span v-else class="text-secondary placeholder-glow">
								<span class="placeholder col-6"></span>
							</span>
						</td>
						<td class="text-end text-nowrap">
							<button
								v-if="n.is_group"
								type="button"
								class="btn btn-icon btn-sm btn-ghost-primary"
								:title="t('Add child account')"
								@click.stop="openCreate(n)"
							>
								<i class="ti ti-plus"></i>
							</button>
							<button
								type="button"
								class="btn btn-icon btn-sm btn-ghost-secondary ms-1"
								:title="t('Edit')"
								@click.stop="openEdit(n)"
							>
								<i class="ti ti-edit"></i>
							</button>
							<button
								type="button"
								class="btn btn-icon btn-sm ms-1"
								:class="n.disabled ? 'btn-ghost-success' : 'btn-ghost-warning'"
								:title="n.disabled ? t('Enable') : t('Disable')"
								@click.stop="toggleDisabled(n)"
							>
								<i class="ti" :class="n.disabled ? 'ti-toggle-left' : 'ti-toggle-right'"></i>
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						{{ createModalTitle }}
					</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-3">
						<div class="col-md-8">
							<label class="form-label required">{{ t("Account name") }}</label>
							<input v-model="form.account_name" type="text" class="form-control" autofocus required />
						</div>
						<div class="col-md-4">
							<label class="form-label">{{ t("Account number") }}</label>
							<input v-model="form.account_number" type="text" class="form-control" />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Parent account") }}</label>
							<Select
								v-model="form.parent_account"
								:options="parentAccountOptions"
								placeholder="—"
								:clearable="true"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Account type") }}</label>
							<Select
								v-model="form.account_type"
								:options="ACCOUNT_TYPE_OPTIONS"
								placeholder="—"
								:clearable="true"
							/>
						</div>
						<div class="col-md-6">
							<label class="form-label">{{ t("Account currency") }}</label>
							<Select
								v-model="form.account_currency"
								:options="currencyOptions"
								placeholder="—"
								:clearable="true"
							/>
						</div>
						<div class="col-12" v-if="!editMode">
							<div class="form-check">
								<input v-model="form.is_group" :true-value="1" :false-value="0" class="form-check-input" type="checkbox" id="acc_is_group" />
								<label class="form-check-label" for="acc_is_group">
									{{ t("Group account (can contain children, holds no transactions itself)") }}
								</label>
							</div>
						</div>
						<!-- Opening balance fields: only visible when creating a leaf account -->
						<template v-if="!editMode && !form.is_group">
							<div class="col-md-6">
								<label class="form-label">{{ t("Opening balance") }}</label>
								<MoneyInput
									v-model="form.opening_balance"
									:currency="form.account_currency"
									:language="user.language"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Opening date") }}</label>
								<DateInput v-model="form.opening_date" />
							</div>
						</template>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitForm">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
/* Account codes and amounts are identifiers, not prose: fix the digit width so
   1000 / 1100 / 1210 line up into a scannable column. */
.coa-code,
.coa-amount {
	font-variant-numeric: tabular-nums;
}
.coa-code {
	font-size: 0.8125rem;
	padding-right: 0.75rem;
}
</style>
