<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const router = useRouter();

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
	} catch {
		balances.value = new Map();
	} finally {
		balancesLoading.value = false;
	}
}

async function refreshAllBalances() {
	await loadBalances();
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

onMounted(async () => {
	await load();
	await loadBalances();
});
watch(activeCompany, async () => {
	await load();
	await loadBalances();
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
								<i class="ti me-1" :class="[rootIcon(n.root_type), rootColor(n.root_type)]"></i>
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
						<td class="text-end font-monospace" :class="{ 'fw-bold': n.is_group }">
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

</template>
