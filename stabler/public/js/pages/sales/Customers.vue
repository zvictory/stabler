<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import PartyPaymentModal from "../../components/PartyPaymentModal.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const customers = ref([]);
const companyCurrency = ref("");
const search = ref("");
const onlyWithBalance = ref(false);
const balancesRefreshing = ref(false);

const selected = ref(null);
const ledger = ref(null);
const ledgerLoading = ref(false);
const ledgerError = ref("");
const ledgerFromDate = ref("");
const ledgerToDate = ref("");

const partyPayOpen = ref(false);

const CUSTOMER_TYPES = ["Company", "Individual", "Partnership"];
const createOpen = ref(false);
const editMode = ref(false);
const editingName = ref("");
const submitting = ref(false);
const submitError = ref("");
const groupOptions = ref([]);
const territoryOptions = ref([]);
const priceListOptions = ref([]);
const currencyOptions = ref([]);
const optionsLoaded = ref(false);
const deleting = ref(false);

function blankCustomer() {
	return {
		customer_name: "",
		customer_type: "Company",
		customer_group: "",
		territory: "",
		email_id: "",
		mobile_no: "",
		tax_id: "",
		default_price_list: "",
		default_currency: "",
	};
}
const form = ref(blankCustomer());

const currency = computed(
	() =>
		companyCurrency.value ||
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

// ── P2.1: client-side sort & filter ──────────────────────────────────────────
const sortField = ref("");
const sortAsc = ref(true);
const filterGroup = ref("");
const filterTerritory = ref("");

const availableGroups = computed(() =>
	[...new Set(customers.value.map((c) => c.customer_group).filter(Boolean))].sort()
);
const availableTerritories = computed(() =>
	[...new Set(customers.value.map((c) => c.territory).filter(Boolean))].sort()
);

const groupFilterOptions = computed(() => [
	{ value: "", label: t("All groups") },
	...availableGroups.value.map((g) => ({ value: g, label: g })),
]);
const territoryFilterOptions = computed(() => [
	{ value: "", label: t("All territories") },
	...availableTerritories.value.map((tr) => ({ value: tr, label: tr })),
]);

const customerTypeOptions = computed(() =>
	CUSTOMER_TYPES.map((ct) => ({ value: ct, label: t(ct) }))
);

const filteredCustomers = computed(() => {
	let list = customers.value;
	if (filterGroup.value) list = list.filter((c) => c.customer_group === filterGroup.value);
	if (filterTerritory.value) list = list.filter((c) => c.territory === filterTerritory.value);
	if (sortField.value === "name") {
		list = [...list].sort((a, b) => {
			const cmp = (a.customer_name || "").localeCompare(b.customer_name || "");
			return sortAsc.value ? cmp : -cmp;
		});
	} else if (sortField.value === "balance") {
		list = [...list].sort((a, b) => {
			const av = Number(a.balance_acc ?? a.balance_base ?? 0);
			const bv = Number(b.balance_acc ?? b.balance_base ?? 0);
			return sortAsc.value ? av - bv : bv - av;
		});
	}
	return list;
});

function toggleSort(field) {
	if (sortField.value === field) {
		sortAsc.value = !sortAsc.value;
	} else {
		sortField.value = field;
		sortAsc.value = true;
	}
}

const totalReceivable = computed(() =>
	customers.value.reduce((sum, c) => sum + Number(c.balance_base || 0), 0)
);

const ledgerRows = computed(() => {
	const e = ledger.value?.entries || [];
	let runBase = Number(ledger.value?.opening_base || 0);
	let runAcc = Number(ledger.value?.opening_acc || 0);
	return e.map((row) => {
		runBase += Number(row.debit || 0) - Number(row.credit || 0);
		runAcc +=
			Number(row.debit_in_account_currency || 0) -
			Number(row.credit_in_account_currency || 0);
		return { ...row, running_base: runBase, running_acc: runAcc };
	});
});

// Currency of the customer's ledger (their AR account currency). Falls back to
// the company base when not yet loaded or the ledger entries span multiple
// account currencies (rare — shows base + warning instead).
const ledgerCurrencyMixed = computed(() => {
	const rows = ledger.value?.entries || [];
	if (!rows.length) return false;
	const set = new Set(rows.map((r) => r.account_currency).filter(Boolean));
	return set.size > 1;
});
const ledgerCurrency = computed(() => {
	if (ledgerCurrencyMixed.value) return currency.value;
	return selected.value?.account_currency || currency.value;
});

async function loadCustomers() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.sales.list_customers_with_balances", {
			company: activeCompany.value,
			search: search.value || "",
			only_with_balance: onlyWithBalance.value ? 1 : 0,
			limit: 500,
		});
		customers.value = res.rows || [];
		companyCurrency.value = res.company_currency || "";
		// If a customer was selected and is still present, keep selection.
		if (selected.value && !customers.value.find((c) => c.name === selected.value.name)) {
			selected.value = null;
			ledger.value = null;
		}
	} catch (err) {
		error.value = err?.message || t("Failed to load customers.");
	} finally {
		loading.value = false;
	}
}

async function refreshBalances() {
	balancesRefreshing.value = true;
	try {
		await loadCustomers();
		if (selected.value) await loadLedger(selected.value);
	} finally {
		balancesRefreshing.value = false;
	}
}

function defaultDateRange() {
	const to = new Date();
	const from = new Date();
	from.setDate(from.getDate() - 365);
	const iso = (d) => d.toISOString().slice(0, 10);
	return { from: iso(from), to: iso(to) };
}

async function loadLedger(customer) {
	if (!customer) return;
	ledgerLoading.value = true;
	ledgerError.value = "";
	try {
		const params = {
			company: activeCompany.value,
			customer: customer.name,
			limit: 1000,
		};
		if (ledgerFromDate.value) params.from_date = ledgerFromDate.value;
		if (ledgerToDate.value) params.to_date = ledgerToDate.value;
		ledger.value = await call("stabler.api.sales.customer_ledger", params);
	} catch (err) {
		ledger.value = null;
		ledgerError.value = err?.message || t("Failed to load ledger.");
	} finally {
		ledgerLoading.value = false;
	}
}

function selectCustomer(c) {
	selected.value = c;
	custOrders.value = [];
	if (!ledgerFromDate.value && !ledgerToDate.value) {
		const r = defaultDateRange();
		ledgerFromDate.value = r.from;
		ledgerToDate.value = r.to;
	}
	loadLedger(c);
	loadCustOrders(c);
}

// ── P1.3: Customer orders ────────────────────────────────────────────────────
const custOrders = ref([]);
const custOrdersLoading = ref(false);
const custOrdersFromDate = ref("");
const custOrdersToDate = ref("");
const custOrdersStatus = ref("");

const ORDER_STATUSES = ["", "Draft", "To Deliver and Bill", "To Bill", "To Deliver", "Completed", "Cancelled", "Closed"];
const orderStatusOptions = computed(() =>
	ORDER_STATUSES.map((s) => ({ value: s, label: s ? t(s) : t("All") }))
);

async function loadCustOrders(customer) {
	if (!customer || !activeCompany.value) return;
	custOrdersLoading.value = true;
	try {
		custOrders.value = await call("stabler.api.sales.list_sales_orders", {
			company: activeCompany.value,
			customer: customer.name,
			from_date: custOrdersFromDate.value || undefined,
			to_date: custOrdersToDate.value || undefined,
			status: custOrdersStatus.value || undefined,
			limit: 50,
		});
	} catch {
		custOrders.value = [];
	} finally {
		custOrdersLoading.value = false;
	}
}

function orderStatusBadge(s) {
	const m = {
		Draft: "bg-secondary-lt",
		"To Deliver and Bill": "bg-yellow-lt",
		"To Bill": "bg-orange-lt",
		"To Deliver": "bg-blue-lt",
		Completed: "bg-green-lt",
		Cancelled: "bg-red-lt",
	};
	return m[s] || "bg-secondary-lt";
}

// ── P1.4: In-context voucher drawer ─────────────────────────────────────────
const voucherOpen = ref(false);
const voucherLoading = ref(false);
const voucherDetail = ref(null);
const voucherError = ref("");

async function openVoucher(entry) {
	if (!entry?.voucher_no) return;
	voucherOpen.value = true;
	voucherLoading.value = true;
	voucherDetail.value = null;
	voucherError.value = "";
	const type = entry.voucher_type;
	const name = entry.voucher_no;
	try {
		let data;
		if (type === "Sales Invoice") {
			data = await call("stabler.api.sales.sales_invoice_detail", { name });
		} else if (type === "Payment Entry") {
			data = await call("stabler.api.money.payment_entry_detail", { name });
		} else if (type === "Journal Entry") {
			data = await call("stabler.api.money.journal_entry_detail", { name });
		} else if (type === "Sales Order") {
			data = await call("stabler.api.sales.sales_order_detail", { name });
		} else {
			data = { name };
		}
		voucherDetail.value = { _type: type, ...data };
	} catch (err) {
		voucherError.value = err?.message || t("Failed to load.");
	} finally {
		voucherLoading.value = false;
	}
}

function closeVoucher() {
	voucherOpen.value = false;
	voucherDetail.value = null;
	voucherError.value = "";
}

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(loadCustomers, 250);
}

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const [groups, terrs, priceLists, currencies] = await Promise.all([
			call("stabler.api.sales.list_customer_groups", { limit: 200 }),
			call("stabler.api.sales.list_territories", { limit: 200 }),
			call("stabler.api.sales.list_price_lists", { selling_only: 1, limit: 200 }),
			call("stabler.api.sales.list_currencies", {}),
		]);
		groupOptions.value = groups || [];
		territoryOptions.value = terrs || [];
		priceListOptions.value = priceLists || [];
		currencyOptions.value = currencies || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || t("Failed to load options.");
	}
}
function openCreate() {
	form.value = blankCustomer();
	submitError.value = "";
	editMode.value = false;
	editingName.value = "";
	createOpen.value = true;
	loadCreateOptions();
}
async function openEdit(c) {
	submitError.value = "";
	editMode.value = true;
	editingName.value = c.name;
	createOpen.value = true;
	loadCreateOptions();
	try {
		const data = await call("stabler.api.sales.get_customer", { name: c.name });
		form.value = {
			customer_name: data.customer_name || "",
			customer_type: data.customer_type || "Company",
			customer_group: data.customer_group || "",
			territory: data.territory || "",
			email_id: data.email_id || "",
			mobile_no: data.mobile_no || "",
			tax_id: data.tax_id || "",
			default_price_list: data.default_price_list || "",
			default_currency: data.default_currency || "",
		};
	} catch (err) {
		submitError.value = err?.message || t("Failed to load customer.");
	}
}
function closeCreate() {
	if (submitting.value || deleting.value) return;
	createOpen.value = false;
}
async function submitCreate() {
	submitError.value = "";
	const f = form.value;
	if (!f.customer_name.trim()) return (submitError.value = t("Customer name is required."));
	submitting.value = true;
	try {
		if (editMode.value) {
			const updated = await call("stabler.api.sales.update_customer", {
				name: editingName.value,
				customer_name: f.customer_name.trim(),
				customer_type: f.customer_type,
				customer_group: f.customer_group || null,
				territory: f.territory || null,
				email_id: f.email_id || null,
				mobile_no: f.mobile_no || null,
				tax_id: f.tax_id || null,
				default_price_list: f.default_price_list || null,
				default_currency: f.default_currency || null,
			});
			createOpen.value = false;
			await loadCustomers();
			// keep selection on updated customer
			if (selected.value?.name === editingName.value) {
				const fresh = customers.value.find((c) => c.name === updated.name);
				if (fresh) selected.value = fresh;
			}
		} else {
			await call("stabler.api.sales.create_customer", {
				customer_name: f.customer_name.trim(),
				customer_type: f.customer_type,
				customer_group: f.customer_group || null,
				territory: f.territory || null,
				email_id: f.email_id || null,
				mobile_no: f.mobile_no || null,
				tax_id: f.tax_id || null,
				default_price_list: f.default_price_list || null,
				default_currency: f.default_currency || null,
			});
			createOpen.value = false;
			await loadCustomers();
		}
	} catch (err) {
		submitError.value = err?.message || t("Failed to save customer.");
	} finally {
		submitting.value = false;
	}
}
async function deleteCustomer() {
	if (!editMode.value || !editingName.value) return;
	if (!window.confirm(t("Delete customer") + " " + editingName.value + "? " + t("This cannot be undone."))) return;
	deleting.value = true;
	submitError.value = "";
	try {
		await call("stabler.api.sales.delete_customer", { name: editingName.value });
		createOpen.value = false;
		if (selected.value?.name === editingName.value) {
			selected.value = null;
			ledger.value = null;
		}
		await loadCustomers();
	} catch (err) {
		submitError.value = err?.message || t("Failed to delete customer.");
	} finally {
		deleting.value = false;
	}
}

onMounted(loadCustomers);
watch(activeCompany, () => {
	selected.value = null;
	ledger.value = null;
	loadCustomers();
});
</script>

<template>
	<div class="page-body customers-redesign">
		<div class="container-fluid">
			<div class="card cust-card cust-merged">
				<div class="row g-0 cust-merged-row">
					<!-- Left side: customer list inside the unified card -->
					<div class="col-12 col-md-5 col-lg-4 cust-merged-list">
						<div class="cust-list-header d-flex flex-wrap align-items-center gap-2 px-3 py-2">
							<div class="card-title m-0">{{ t("Customers") }}</div>
							<span class="badge bg-secondary-lt text-secondary ms-1">{{ filteredCustomers.length }}</span>
							<button
								type="button"
								class="btn btn-sm btn-ghost-secondary ms-auto"
								:disabled="balancesRefreshing"
								@click="refreshBalances"
								:title="t('Refresh balances')"
							>
								<span v-if="balancesRefreshing" class="spinner-border spinner-border-sm"></span>
								<i v-else class="ti ti-refresh"></i>
							</button>
							<button type="button" class="btn btn-sm btn-primary cust-new-btn" @click="openCreate">
								<i class="ti ti-plus me-1"></i>{{ t("New") }}
							</button>
						</div>
						<div class="cust-filter-row px-3 py-2">
							<div class="cust-search-wrap">
								<i class="ti ti-search cust-search-icon"></i>
								<input
									v-model="search"
									type="search"
									class="form-control form-control-sm cust-search-input"
									:placeholder="t('Search customer…')"
									@input="onSearchInput"
								/>
							</div>
							<label class="form-check form-check-inline mt-2 mb-0">
								<input
									v-model="onlyWithBalance"
									type="checkbox"
									class="form-check-input"
									@change="loadCustomers"
								/>
								<span class="form-check-label small">{{ t("Only with balance") }}</span>
							</label>
							<!-- P2.1 sort/filter controls -->
							<div class="d-flex gap-2 flex-wrap mt-2 align-items-center">
								<Select v-if="availableGroups.length" v-model="filterGroup" size="sm" :options="groupFilterOptions" style="max-width: 150px" />
								<Select v-if="availableTerritories.length" v-model="filterTerritory" size="sm" :options="territoryFilterOptions" style="max-width: 150px" />
								<div class="btn-group btn-group-sm ms-auto">
									<button
										type="button"
										class="btn btn-ghost-secondary"
										:class="{ 'text-primary': sortField === 'name' }"
										@click="toggleSort('name')"
									>
										{{ t("Name") }}
										<i v-if="sortField === 'name'" :class="sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
									</button>
									<button
										type="button"
										class="btn btn-ghost-secondary"
										:class="{ 'text-primary': sortField === 'balance' }"
										@click="toggleSort('balance')"
									>
										{{ t("Balance") }}
										<i v-if="sortField === 'balance'" :class="sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
									</button>
								</div>
							</div>
						</div>
						<div class="cust-list-scroll">
							<div v-if="loading" class="text-center py-5">
								<div class="spinner-border text-primary"></div>
							</div>
							<div v-else-if="error" class="alert alert-danger m-2">{{ error }}</div>
							<EmptyState
								v-else-if="!filteredCustomers.length"
								icon="ti-users"
								accentIcon="ti-user-plus"
								tone="purple"
								:title="t('No customers')"
								:subtitle="t('Add your first customer to start sending quotes and invoices.')"
							>
								<template #actions>
									<button type="button" class="btn btn-primary" @click="openCreate">
										<i class="ti ti-user-plus me-1"></i>{{ t("Add customer") }}
									</button>
								</template>
							</EmptyState>
							<ul v-else class="list-unstyled m-0 cust-list">
								<li
									v-for="c in filteredCustomers"
									:key="c.name"
									class="cust-row"
									:class="{ 'cust-row-active': selected?.name === c.name }"
									@click="selectCustomer(c)"
								>
									<div class="cust-row-avatar">
										{{ (c.customer_name || c.name).slice(0, 2).toUpperCase() }}
									</div>
									<div class="cust-row-main">
										<div class="cust-row-name">{{ c.customer_name }}</div>
										<div class="cust-row-id">{{ c.name }}</div>
									</div>
									<div class="cust-row-balance">
										<div
											:class="{
												'text-red': Number(c.balance_acc ?? c.balance_base) > 0,
												'text-secondary': !Number(c.balance_acc ?? c.balance_base),
											}"
										>
											{{ formatMoney(
												c.balance_acc ?? c.balance_base,
												c.account_currency || currency,
												user.language,
											) }}
										</div>
										<div
											v-if="c.account_currency && c.account_currency !== currency"
											class="small text-secondary"
										>
											{{ formatMoney(c.balance_base, currency, user.language) }}
										</div>
									</div>
									<div class="cust-row-actions" @click.stop>
										<router-link
											:to="{ path: '/sales/orders/new', query: { new_for: c.name } }"
											class="btn btn-sm btn-ghost-primary"
											:title="t('New sales order')"
										>
											<i class="ti ti-file-plus"></i>
										</router-link>
										<button
											type="button"
											class="btn btn-sm btn-ghost-secondary"
											:title="t('Edit customer')"
											@click="openEdit(c)"
										>
											<i class="ti ti-pencil"></i>
										</button>
									</div>
								</li>
							</ul>
						</div>
						<div v-if="filteredCustomers.length" class="cust-list-footer">
							<span class="text-secondary small">{{ t("Total receivable") }}</span>
							<span class="font-monospace fw-semibold">
								{{ formatMoney(totalReceivable, currency, user.language) }}
							</span>
						</div>
					</div>

					<!-- Right side: ledger inside the same unified card -->
					<div class="col-12 col-md-7 col-lg-8 cust-merged-pane">
						<div v-if="!selected" class="cust-empty-state d-flex align-items-center justify-content-center text-secondary">
							<div class="text-center">
								<i class="ti ti-user-search" style="font-size: 3rem"></i>
								<div class="mt-2">{{ t("Select a customer to view transactions") }}</div>
							</div>
						</div>
						<template v-else>
							<div class="cust-ledger-header px-3 py-3 d-flex align-items-center gap-3 flex-wrap">
								<span class="avatar avatar-lg bg-blue-lt cust-ledger-avatar">
									{{ (selected.customer_name || selected.name).slice(0, 2).toUpperCase() }}
								</span>
								<div class="min-w-0">
									<h3 class="m-0 text-truncate">{{ selected.customer_name }}</h3>
									<div class="small text-secondary font-monospace">{{ selected.name }}</div>
								</div>
								<div class="ms-auto text-end">
									<div class="small text-secondary text-uppercase cust-balance-label">{{ t("Balance") }}</div>
									<div
										class="m-0 font-monospace cust-balance-amount"
										:class="Number(selected.balance_acc ?? selected.balance_base) > 0 ? 'text-red' : ''"
									>
										{{ formatMoney(
											selected.balance_acc ?? selected.balance_base,
											selected.account_currency || currency,
											user.language,
										) }}
									</div>
									<div
										v-if="selected.account_currency && selected.account_currency !== currency"
										class="small text-secondary font-monospace"
									>
										{{ formatMoney(selected.balance_base, currency, user.language) }}
									</div>
								</div>
							</div>
							<!-- P1.3: Orders section -->
							<div class="cust-orders-section px-3 py-2 border-bottom">
								<div class="d-flex align-items-center gap-2 mb-2">
									<h6 class="text-uppercase text-secondary small mb-0">{{ t("Orders") }}</h6>
									<span v-if="custOrdersLoading" class="spinner-border spinner-border-sm text-secondary"></span>
									<span v-else class="badge bg-secondary-lt text-secondary">{{ custOrders.length }}</span>
								</div>
								<div class="d-flex gap-2 align-items-end flex-wrap mb-2">
									<div>
										<label class="form-label small mb-1">{{ t("From") }}</label>
										<DateInput v-model="custOrdersFromDate" size="sm" @blur="loadCustOrders(selected)" />
									</div>
									<div>
										<label class="form-label small mb-1">{{ t("To") }}</label>
										<DateInput v-model="custOrdersToDate" size="sm" @blur="loadCustOrders(selected)" />
									</div>
									<div style="min-width: 160px">
										<label class="form-label small mb-1">{{ t("Status") }}</label>
										<Select v-model="custOrdersStatus" size="sm" :options="orderStatusOptions" @update:modelValue="loadCustOrders(selected)" />
									</div>
								</div>
								<div v-if="!custOrders.length && !custOrdersLoading" class="text-secondary small">{{ t("No orders.") }}</div>
								<div v-else class="d-flex flex-column gap-1">
									<button
										v-for="o in custOrders"
										:key="o.name"
										type="button"
										class="btn btn-ghost-secondary d-flex align-items-center gap-2 px-1 py-1 text-start"
										@click="openVoucher({ voucher_type: 'Sales Order', voucher_no: o.name })"
									>
										<span class="badge" :class="orderStatusBadge(o.status)">{{ t(o.status) }}</span>
										<span class="font-monospace small text-primary">{{ o.name }}</span>
										<span class="text-secondary small">{{ formatDate(o.transaction_date) }}</span>
										<span class="font-monospace small ms-auto">{{ formatMoney(o.grand_total, o.currency || currency, user.language) }}</span>
									</button>
								</div>
							</div>
							<div class="cust-ledger-filter px-3 py-2">
								<div class="row g-2 align-items-end">
									<div class="col-auto">
										<label class="form-label small mb-1">{{ t("From") }}</label>
										<DateInput
											v-model="ledgerFromDate"
											size="sm"
											@blur="loadLedger(selected)"
										/>
									</div>
									<div class="col-auto">
										<label class="form-label small mb-1">{{ t("To") }}</label>
										<DateInput
											v-model="ledgerToDate"
											size="sm"
											@blur="loadLedger(selected)"
										/>
									</div>
									<div class="col-auto">
										<button
											type="button"
											class="btn btn-sm btn-ghost-secondary"
											:disabled="ledgerLoading"
											@click="loadLedger(selected)"
										>
											<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
										</button>
									</div>
									<div class="col-auto ms-auto d-flex gap-2">
										<button
											type="button"
											class="btn btn-sm btn-outline-secondary"
											@click="openEdit(selected)"
										>
											<i class="ti ti-pencil me-1"></i>{{ t("Edit") }}
										</button>
										<button
											type="button"
											class="btn btn-sm btn-outline-success"
											@click="partyPayOpen = true"
										>
											<i class="ti ti-cash me-1"></i>{{ t("Payment") }}
										</button>
										<router-link
											:to="{ path: '/sales/orders/new', query: { new_for: selected.name } }"
											class="btn btn-sm btn-primary"
										>
											<i class="ti ti-file-plus me-1"></i>{{ t("New SO") }}
										</router-link>
									</div>
								</div>
							</div>
							<div class="cust-ledger-scroll">
								<div v-if="ledgerLoading" class="text-center py-5">
									<div class="spinner-border text-primary"></div>
								</div>
								<div v-else-if="ledgerError" class="alert alert-danger m-2">{{ ledgerError }}</div>
								<div v-else-if="!ledgerRows.length" class="text-secondary text-center py-5">
									{{ t("No transactions in this period.") }}
								</div>
								<template v-else>
									<div
										v-if="ledgerCurrencyMixed"
										class="alert alert-warning m-2 small mb-0"
										role="alert"
									>
										<i class="ti ti-alert-triangle me-1"></i>
										{{ t("Ledger spans multiple account currencies; amounts shown in base currency.") }}
									</div>
									<table class="table table-vcenter table-sm m-0 cust-ledger-table">
										<thead class="cust-ledger-thead">
											<tr>
												<th>{{ t("Date") }}</th>
												<th>{{ t("Voucher") }}</th>
												<th class="text-end">{{ t("Debit") }}</th>
												<th class="text-end">{{ t("Credit") }}</th>
												<th class="text-end">{{ t("Balance") }} ({{ ledgerCurrency }})</th>
											</tr>
										</thead>
										<tbody>
											<tr v-if="Number(ledgerCurrencyMixed ? ledger?.opening_base : ledger?.opening_acc) !== 0" class="text-secondary">
												<td colspan="4" class="text-end fst-italic">{{ t("Opening balance") }}</td>
												<td class="text-end font-monospace fst-italic">
													{{ formatMoney(
														ledgerCurrencyMixed ? ledger.opening_base : ledger.opening_acc,
														ledgerCurrency,
														user.language,
													) }}
												</td>
											</tr>
											<tr v-for="e in ledgerRows" :key="e.name">
												<td class="text-nowrap small">{{ formatDateTime(e.posting_date) }}</td>
												<td>
													<div class="small text-secondary">{{ e.voucher_type }}</div>
													<button
														v-if="e.voucher_no"
														type="button"
														class="btn btn-link p-0 font-monospace small text-primary fw-semibold"
														@click="openVoucher(e)"
													>
														{{ e.voucher_no }}
													</button>
													<div v-else class="font-monospace small">—</div>
												</td>
												<td class="text-end font-monospace small">
													<span v-if="Number(ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency) > 0">
														{{ formatMoney(
															ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency,
															ledgerCurrencyMixed ? currency : (e.account_currency || ledgerCurrency),
															user.language,
														) }}
													</span>
													<span v-else class="text-secondary">—</span>
												</td>
												<td class="text-end font-monospace small">
													<span v-if="Number(ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency) > 0">
														{{ formatMoney(
															ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency,
															ledgerCurrencyMixed ? currency : (e.account_currency || ledgerCurrency),
															user.language,
														) }}
													</span>
													<span v-else class="text-secondary">—</span>
												</td>
												<td class="text-end font-monospace fw-semibold small">
													{{ formatMoney(
														ledgerCurrencyMixed ? e.running_base : e.running_acc,
														ledgerCurrency,
														user.language,
													) }}
												</td>
											</tr>
										</tbody>
										<tfoot v-if="ledgerRows.length" class="cust-ledger-tfoot">
											<tr>
												<th colspan="4" class="text-end">{{ t("Closing balance") }}</th>
												<th class="text-end font-monospace">
													{{ formatMoney(
														ledgerCurrencyMixed ? ledger.closing_base : ledger.closing_acc,
														ledgerCurrency,
														user.language,
													) }}
												</th>
											</tr>
										</tfoot>
									</table>
								</template>
							</div>
						</template>
					</div>
				</div>
			</div>
		</div>
	</div>

	<!-- P1.4: In-context voucher detail drawer -->
	<template v-if="voucherOpen">
		<div class="offcanvas-backdrop fade show" @click="closeVoucher"></div>
		<div class="offcanvas offcanvas-end show" tabindex="-1" style="width: min(520px, 100vw)">
			<div class="offcanvas-header">
				<h5 class="offcanvas-title">
					<span v-if="voucherDetail">{{ t(voucherDetail._type) }}</span>
					<span v-else>…</span>
				</h5>
				<button type="button" class="btn-close" @click="closeVoucher"></button>
			</div>
			<div class="offcanvas-body">
				<div v-if="voucherLoading" class="text-center py-5">
					<div class="spinner-border text-primary"></div>
				</div>
				<div v-else-if="voucherError" class="alert alert-danger">{{ voucherError }}</div>
				<template v-else-if="voucherDetail">
					<!-- Sales Invoice detail -->
					<template v-if="voucherDetail._type === 'Sales Invoice'">
						<div class="datagrid mb-3">
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Invoice") }}</div>
								<div class="datagrid-content font-monospace">{{ voucherDetail.name }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Date") }}</div>
								<div class="datagrid-content">{{ formatDate(voucherDetail.posting_date) }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Status") }}</div>
								<div class="datagrid-content">
									<span class="badge bg-secondary-lt">{{ t(voucherDetail.status) }}</span>
								</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Grand total") }}</div>
								<div class="datagrid-content font-monospace">{{ formatMoney(voucherDetail.grand_total, voucherDetail.currency, user.language) }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Outstanding") }}</div>
								<div class="datagrid-content font-monospace">{{ formatMoney(voucherDetail.outstanding_amount, voucherDetail.currency, user.language) }}</div>
							</div>
						</div>
						<table v-if="voucherDetail.items?.length" class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("Item") }}</th>
									<th class="text-end">{{ t("Qty") }}</th>
									<th class="text-end">{{ t("Amount") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="it in voucherDetail.items" :key="it.item_code">
									<td>{{ it.item_name || it.item_code }}</td>
									<td class="text-end font-monospace">{{ it.qty }}</td>
									<td class="text-end font-monospace">{{ formatMoney(it.amount, voucherDetail.currency, user.language) }}</td>
								</tr>
							</tbody>
						</table>
					</template>

					<!-- Sales Order detail -->
					<template v-else-if="voucherDetail._type === 'Sales Order'">
						<div class="datagrid mb-3">
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Order") }}</div>
								<div class="datagrid-content font-monospace">{{ voucherDetail.name }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Date") }}</div>
								<div class="datagrid-content">{{ formatDate(voucherDetail.transaction_date) }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Status") }}</div>
								<div class="datagrid-content">
									<span class="badge" :class="orderStatusBadge(voucherDetail.status)">{{ t(voucherDetail.status) }}</span>
								</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Grand total") }}</div>
								<div class="datagrid-content font-monospace">{{ formatMoney(voucherDetail.grand_total, voucherDetail.currency, user.language) }}</div>
							</div>
						</div>
						<table v-if="voucherDetail.items?.length" class="table table-sm table-vcenter">
							<thead>
								<tr>
									<th>{{ t("Item") }}</th>
									<th class="text-end">{{ t("Qty") }}</th>
									<th class="text-end">{{ t("Amount") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="it in voucherDetail.items" :key="it.item_code">
									<td>{{ it.item_name || it.item_code }}</td>
									<td class="text-end font-monospace">{{ it.qty }}</td>
									<td class="text-end font-monospace">{{ formatMoney(it.amount, voucherDetail.currency, user.language) }}</td>
								</tr>
							</tbody>
						</table>
					</template>

					<!-- Payment Entry detail -->
					<template v-else-if="voucherDetail._type === 'Payment Entry'">
						<div class="datagrid mb-3">
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Payment") }}</div>
								<div class="datagrid-content font-monospace">{{ voucherDetail.name }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Date") }}</div>
								<div class="datagrid-content">{{ formatDate(voucherDetail.posting_date) }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Type") }}</div>
								<div class="datagrid-content">{{ t(voucherDetail.payment_type) }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Amount paid") }}</div>
								<div class="datagrid-content font-monospace">{{ formatMoney(voucherDetail.paid_amount, voucherDetail.paid_from_account_currency, user.language) }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Mode") }}</div>
								<div class="datagrid-content">{{ voucherDetail.mode_of_payment || "—" }}</div>
							</div>
							<div v-if="voucherDetail.reference_no" class="datagrid-item">
								<div class="datagrid-title">{{ t("Reference") }}</div>
								<div class="datagrid-content font-monospace">{{ voucherDetail.reference_no }}</div>
							</div>
						</div>
						<div v-if="voucherDetail.references?.length">
							<div class="small text-secondary text-uppercase mb-1">{{ t("Applied to") }}</div>
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("Document") }}</th>
										<th class="text-end">{{ t("Allocated") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="ref in voucherDetail.references" :key="ref.reference_name">
										<td class="font-monospace small">{{ ref.reference_name }}</td>
										<td class="text-end font-monospace">{{ formatMoney(ref.allocated_amount, voucherDetail.paid_from_account_currency, user.language) }}</td>
									</tr>
								</tbody>
							</table>
						</div>
					</template>

					<!-- Journal Entry detail -->
					<template v-else-if="voucherDetail._type === 'Journal Entry'">
						<div class="datagrid mb-3">
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Entry") }}</div>
								<div class="datagrid-content font-monospace">{{ voucherDetail.name }}</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Date") }}</div>
								<div class="datagrid-content">{{ formatDate(voucherDetail.posting_date) }}</div>
							</div>
							<div v-if="voucherDetail.user_remark" class="datagrid-item">
								<div class="datagrid-title">{{ t("Remark") }}</div>
								<div class="datagrid-content">{{ voucherDetail.user_remark }}</div>
							</div>
						</div>
						<div v-if="voucherDetail.accounts?.length">
							<div class="small text-secondary text-uppercase mb-1">{{ t("Accounts") }}</div>
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("Account") }}</th>
										<th class="text-end">{{ t("Debit") }}</th>
										<th class="text-end">{{ t("Credit") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(ac, i) in voucherDetail.accounts" :key="i">
										<td class="small">{{ ac.account }}</td>
										<td class="text-end font-monospace small">
											<span v-if="Number(ac.debit) > 0">{{ formatMoney(ac.debit, ac.account_currency, user.language) }}</span>
											<span v-else class="text-secondary">—</span>
										</td>
										<td class="text-end font-monospace small">
											<span v-if="Number(ac.credit) > 0">{{ formatMoney(ac.credit, ac.account_currency, user.language) }}</span>
											<span v-else class="text-secondary">—</span>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
					</template>

					<!-- Fallback -->
					<template v-else>
						<div class="font-monospace small">{{ voucherDetail.name }}</div>
					</template>
				</template>
			</div>
		</div>
	</template>

	<template v-if="createOpen">
		<div class="modal-backdrop fade show" @click="closeCreate"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-dialog-centered" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ editMode ? t("Edit customer") : t("New customer") }}</h5>
						<button type="button" class="btn-close" :aria-label="t('Close')" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
						<div class="row g-3">
							<div class="col-12">
								<label class="form-label">{{ t("Customer name") }} <span class="text-danger">*</span></label>
								<input v-model="form.customer_name" type="text" class="form-control" autofocus />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Type") }}</label>
								<Select v-model="form.customer_type" :options="customerTypeOptions" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Tax ID") }}</label>
								<input v-model="form.tax_id" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Customer group") }}</label>
								<Select v-model="form.customer_group" :options="groupOptions" value-key="name" label-key="name" :placeholder="t('— default —')" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Territory") }}</label>
								<Select v-model="form.territory" :options="territoryOptions" value-key="name" label-key="name" :placeholder="t('— default —')" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Email") }}</label>
								<input v-model="form.email_id" type="email" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Mobile") }}</label>
								<input v-model="form.mobile_no" type="tel" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Default price list") }}</label>
								<Select v-model="form.default_price_list" :options="priceListOptions" value-key="name" :placeholder="t('— global default —')">
									<template #option="{ option: p }">
										{{ p.name }}<span v-if="p.currency"> ({{ p.currency }})</span>
									</template>
									<template #selected="{ option: p }">
										{{ p.name }}<span v-if="p.currency"> ({{ p.currency }})</span>
									</template>
								</Select>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Default currency") }}</label>
								<Select v-model="form.default_currency" class="font-monospace" :options="currencyOptions" value-key="name" :placeholder="t('— company default —')">
									<template #option="{ option: c }">
										{{ c.name }}<template v-if="c.symbol"> ({{ c.symbol }})</template>
									</template>
									<template #selected="{ option: c }">
										{{ c.name }}<template v-if="c.symbol"> ({{ c.symbol }})</template>
									</template>
								</Select>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" @click="closeCreate" :disabled="submitting || deleting">
							{{ t("Cancel") }}
						</button>
						<button
							v-if="editMode"
							type="button"
							class="btn btn-outline-danger me-auto"
							:disabled="submitting || deleting"
							@click="deleteCustomer"
						>
							<span v-if="deleting" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-trash me-1"></i>
							{{ t("Delete") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submitting || deleting || !form.customer_name.trim()"
							@click="submitCreate"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>
							{{ t("Save") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>

	<!-- Party-level payment modal (Customer) -->
	<PartyPaymentModal
		v-if="selected"
		:open="partyPayOpen"
		party-type="Customer"
		:party="selected.name"
		:company="activeCompany"
		@close="partyPayOpen = false"
		@paid="partyPayOpen = false; loadLedger(selected); loadCustOrders(selected)"
	/>
</template>

<style scoped>
.customers-redesign {
	--cust-radius: 1rem;
	--cust-radius-sm: 0.625rem;
	--cust-border: #e6e7eb;
	--cust-row-hover: #f4f6fa;
	--cust-row-active: #eef4ff;
	--cust-pane-bg: #fbfbfc;
}

/* unified single-window card */
.customers-redesign .cust-merged {
	border-radius: var(--cust-radius);
	border: 1px solid var(--cust-border);
	box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04), 0 1px 3px rgba(16, 24, 40, 0.06);
	overflow: hidden;
	background: #ffffff;
}

/* vertical divider between list and ledger */
.cust-merged-list {
	border-right: 1px solid var(--cust-border);
	display: flex;
	flex-direction: column;
}
.cust-merged-pane {
	background: var(--cust-pane-bg);
	display: flex;
	flex-direction: column;
}

@media (max-width: 767.98px) {
	.cust-merged-list {
		border-right: none;
		border-bottom: 1px solid var(--cust-border);
	}
}

/* ---- inputs / buttons ---- */
.customers-redesign :deep(.form-control),
.customers-redesign :deep(.form-select),
.customers-redesign :deep(.btn) {
	border-radius: var(--cust-radius-sm);
}

.customers-redesign :deep(.btn-sm) {
	border-radius: 0.5rem;
}

.customers-redesign :deep(.form-check-input) {
	border-radius: 0.375rem;
}

/* ---- list header ---- */
.cust-list-header {
	border-bottom: 1px solid var(--cust-border);
}

.cust-filter-row {
	border-bottom: 1px solid var(--cust-border);
}

.cust-new-btn {
	border-radius: 999px;
	padding-inline: 0.85rem;
}

/* ---- search w/ icon ---- */
.cust-search-wrap {
	position: relative;
}
.cust-search-icon {
	position: absolute;
	left: 0.65rem;
	top: 50%;
	transform: translateY(-50%);
	color: #9ca3af;
	font-size: 0.95rem;
}
.cust-search-input {
	padding-left: 2rem;
	border-radius: var(--cust-radius-sm);
}

/* ---- list scroll ---- */
.cust-list-scroll {
	overflow-y: auto;
	flex: 1 1 auto;
	min-height: 0;
	max-height: calc(100vh - 18rem);
}

.cust-list {
	padding: 0.25rem;
}

/* ---- list rows ---- */
.cust-row {
	display: flex;
	align-items: center;
	gap: 0.75rem;
	padding: 0.55rem 0.75rem;
	border-radius: 0.75rem;
	cursor: pointer;
	position: relative;
	transition: background 0.12s ease;
}
.cust-row:hover {
	background: var(--cust-row-hover);
}
.cust-row-active {
	background: var(--cust-row-active);
}
.cust-row-active:hover {
	background: var(--cust-row-active);
}

.cust-row-avatar {
	flex: 0 0 auto;
	width: 36px;
	height: 36px;
	border-radius: 12px;
	background: #eef2ff;
	color: #4338ca;
	font-weight: 600;
	font-size: 13px;
	display: flex;
	align-items: center;
	justify-content: center;
}

.cust-row-main {
	flex: 1 1 auto;
	min-width: 0;
}

.cust-row-name {
	font-weight: 600;
	font-size: 0.875rem;
	color: #111827;
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.cust-row-id {
	font-size: 0.72rem;
	color: #9ca3af;
	font-family: var(--tblr-font-monospace, ui-monospace, SFMono-Regular, monospace);
	white-space: nowrap;
	overflow: hidden;
	text-overflow: ellipsis;
}

.cust-row-balance {
	flex: 0 0 auto;
	text-align: right;
	font-family: var(--tblr-font-monospace, ui-monospace, SFMono-Regular, monospace);
	font-size: 0.875rem;
	white-space: nowrap;
	transition: opacity 0.15s ease;
}

/* hover quick-actions */
.cust-row-actions {
	position: absolute;
	right: 0.5rem;
	top: 50%;
	transform: translateY(-50%);
	display: flex;
	gap: 0.25rem;
	opacity: 0;
	pointer-events: none;
	background: linear-gradient(90deg, transparent, var(--cust-row-hover) 30%);
	padding: 0.25rem 0.25rem 0.25rem 1.5rem;
	border-radius: 0.75rem;
	transition: opacity 0.12s ease;
}
.cust-row:hover .cust-row-actions {
	opacity: 1;
	pointer-events: auto;
}
.cust-row-active .cust-row-actions {
	background: linear-gradient(90deg, transparent, var(--cust-row-active) 30%);
}
.cust-row:hover .cust-row-balance {
	opacity: 0.35;
}

.cust-row-actions :deep(.btn) {
	border-radius: 0.5rem;
	padding: 0.25rem 0.4rem;
}

/* ---- list footer ---- */
.cust-list-footer {
	display: flex;
	align-items: center;
	gap: 0.5rem;
	padding: 0.65rem 1rem;
	border-top: 1px solid var(--cust-border);
	background: #fafbfc;
}
.cust-list-footer span:last-child {
	margin-left: auto;
}

/* ---- empty ledger state ---- */
.cust-empty-state {
	min-height: 22rem;
	flex: 1 1 auto;
}

/* ---- ledger header (balance forced right via ms-auto on template) ---- */
.cust-ledger-header {
	background: #ffffff;
	border-bottom: 1px solid var(--cust-border);
}
.cust-ledger-avatar {
	border-radius: 14px;
	font-weight: 600;
}
.cust-balance-label {
	letter-spacing: 0.06em;
	font-size: 0.7rem;
}
.cust-balance-amount {
	font-size: 1.6rem;
	line-height: 1.1;
	font-weight: 600;
	text-align: right;
}

.cust-ledger-filter {
	background: #ffffff;
	border-bottom: 1px solid var(--cust-border);
}

.min-w-0 {
	min-width: 0;
}

/* ---- ledger scroll ---- */
.cust-ledger-scroll {
	overflow-y: auto;
	flex: 1 1 auto;
	min-height: 0;
	max-height: calc(100vh - 22rem);
	position: relative;
	background: #ffffff;
}

.cust-ledger-thead {
	position: sticky;
	top: 0;
	z-index: 5;
	background: #ffffff;
}
.cust-ledger-thead th {
	border-bottom: 1px solid var(--cust-border);
	font-size: 0.72rem;
	text-transform: uppercase;
	letter-spacing: 0.04em;
	color: #6b7280;
	font-weight: 600;
	padding-block: 0.5rem;
}

.cust-ledger-table :deep(td) {
	padding-block: 0.45rem;
}

.cust-ledger-tfoot th {
	background: #fafbfc;
	border-top: 1px solid var(--cust-border);
	padding-block: 0.65rem;
}
</style>
