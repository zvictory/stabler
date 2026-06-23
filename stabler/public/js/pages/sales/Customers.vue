<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney, balanceState } from "../../composables/money.js";
import { formatDate, formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import PartyPaymentModal from "../../components/PartyPaymentModal.vue";
import BalanceChip from "../../components/BalanceChip.vue";
import PartyAvatar from "../../components/PartyAvatar.vue";
import ApexChart from "../../components/ApexChart.vue";
import { getStatusBadgeClass } from "../../composables/status.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const { confirm } = useConfirm();
const toast = useToast();

const loading = ref(false);
const error = ref("");
const customers = ref([]);
const companyCurrency = ref("");
const search = ref("");
const onlyWithBalance = ref(false);

const selected = ref(null);
const selectedDetail = ref(null);
const recentInvoices = ref([]);
const ledger = ref(null);
const ledgerLoading = ref(false);
const ledgerError = ref("");
const ledgerFromDate = ref("");
const ledgerToDate = ref("");
const ledgerTypeFilter = ref("");
const ledgerSearch = ref("");
const ledgerSortAsc = ref(true);

// Professional .xlsx of the open customer's ledger (opening / movements / running
// balance / closing) — re-runs server-side for the current customer + date range.
function exportLedgerXlsx() {
	if (!selected.value?.name) return;
	const qs = new URLSearchParams({
		report_key: "customer_ledger",
		filters: JSON.stringify({
			company: activeCompany.value,
			customer: selected.value.name,
			from_date: ledgerFromDate.value || undefined,
			to_date: ledgerToDate.value || undefined,
		}),
	});
	window.open(`/api/method/stabler.api.export.export_report_xlsx?${qs.toString()}`, "_blank");
}

const partyPayOpen = ref(false);
const currentTab = ref("ledger");

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

const cockpitData = ref(null);
const cockpitLoading = ref(false);

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

const currency = computed(() => companyCurrency.value || session.currency);

// Sorting & Filtering for Master List
const sortField = ref("name");
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

const voucherTypes = computed(() => [
	{ value: "", label: t("All vouchers") },
	{ value: "Payment Entry", label: t("Payment") },
	{ value: "Sales Invoice", label: t("Invoice") },
	{ value: "Journal Entry", label: t("Journal") },
	{ value: "Return", label: t("Return") },
]);

const filteredLedgerRows = computed(() => {
	let list = ledgerRows.value || [];
	
	if (ledgerTypeFilter.value) {
		if (ledgerTypeFilter.value === "Invoice") {
			list = list.filter(r => r.voucher_type === "Sales Invoice");
		} else if (ledgerTypeFilter.value === "Return") {
			list = list.filter(r => 
				r.voucher_type === "Sales Invoice" && 
				(Number(r.debit || 0) < 0 || Number(r.credit || 0) < 0 || String(r.remarks || "").toLowerCase().includes("return"))
			);
		} else {
			list = list.filter(r => r.voucher_type === ledgerTypeFilter.value);
		}
	}
	
	if (ledgerSearch.value.trim()) {
		const q = ledgerSearch.value.trim().toLowerCase();
		list = list.filter(r => 
			String(r.voucher_no || "").toLowerCase().includes(q) || 
			String(r.remarks || "").toLowerCase().includes(q)
		);
	}
	
	list = [...list].sort((a, b) => {
		const cmp = String(a.posting_date || "").localeCompare(String(b.posting_date || ""));
		return ledgerSortAsc.value ? cmp : -cmp;
	});
	
	return list;
});

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
		if (selected.value) {
			const fresh = customers.value.find((c) => c.name === selected.value.name);
			if (fresh) {
				selected.value = fresh;
			} else {
				selected.value = null;
				ledger.value = null;
			}
		}
	} catch (err) {
		error.value = err?.message || t("Failed to load customers.");
	} finally {
		loading.value = false;
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

async function selectCustomer(c) {
	selected.value = c;
	custOrders.value = [];
	recentInvoices.value = [];
	ledgerTypeFilter.value = "";
	ledgerSearch.value = "";
	ledgerSortAsc.value = true;

	if (!ledgerFromDate.value && !ledgerToDate.value) {
		const r = defaultDateRange();
		ledgerFromDate.value = r.from;
		ledgerToDate.value = r.to;
	}
	loadLedger(c);
	loadCustOrders(c);

	try {
		const detail = await call("stabler.api.sales.customer_detail", {
			name: c.name,
			company: activeCompany.value,
		});
		recentInvoices.value = detail.recent_invoices || [];
		selectedDetail.value = detail;
	} catch (err) {
		console.error(err);
	}
}

const custOrders = ref([]);
const custOrdersLoading = ref(false);

async function loadCustOrders(customer) {
	if (!customer || !activeCompany.value) return;
	custOrdersLoading.value = true;
	try {
		custOrders.value = await call("stabler.api.sales.list_sales_orders", {
			company: activeCompany.value,
			customer: customer.name,
			limit: 50,
		});
	} catch {
		custOrders.value = [];
	} finally {
		custOrdersLoading.value = false;
	}
}

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
	searchTimer = setTimeout(loadCustomers, 300);
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
	const ok = await confirm({
		title: t("Delete Customer"),
		body: t("Delete customer") + " " + editingName.value + "? " + t("This cannot be undone."),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	deleting.value = true;
	submitError.value = "";
	try {
		await call("stabler.api.sales.delete_customer", { name: editingName.value });
		toast.success(t("Customer deleted."));
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

async function loadCockpit() {
	if (!activeCompany.value) return;
	cockpitLoading.value = true;
	try {
		cockpitData.value = await call("stabler.api.sales.receivables_cockpit", {
			company: activeCompany.value,
		});
	} catch (err) {
		console.error(err);
	} finally {
		cockpitLoading.value = false;
	}
}

// Receivables Trend Sparkline configuration
const trendSeries = computed(() => [{
	name: t("Receivables"),
	data: cockpitData.value?.trend_8_weeks || [],
}]);

const trendOptions = computed(() => ({
	chart: {
		sparkline: { enabled: true },
	},
	stroke: { curve: "smooth", width: 2 },
	colors: ["#206bc4"],
	tooltip: {
		fixed: { enabled: false },
		x: { show: false },
		y: {
			title: { formatter: () => t("Receivables") + ": " }
		},
		marker: { show: false }
	}
}));

function getRowRemark(e) {
	if (e.remarks && e.remarks.trim()) {
		return e.remarks;
	}
	if (e.against_voucher) {
		return `${t("against")} ${e.against_voucher}`;
	}
	if (e.against && !e.against.includes(e.party || "")) {
		return e.against;
	}
	return "—";
}

watch(selected, (newVal) => {
	if (!newVal) {
		loadCockpit();
	}
});

watch([ledgerFromDate, ledgerToDate], () => {
	if (selected.value) {
		loadLedger(selected.value);
	}
});

onMounted(() => {
	loadCustomers();
	loadCockpit();
});

watch(activeCompany, () => {
	selected.value = null;
	ledger.value = null;
	loadCustomers();
	loadCockpit();
});
</script>

<template>
	<div class="page-body customers-redesign p-0">
		<div class="container-fluid p-0">
			<div class="card cust-card cust-merged m-0 border-0 rounded-0 bg-transparent shadow-none">
				<div class="row g-0 cust-merged-row">
					<!-- Left side: customer list -->
					<div class="col-12 col-md-5 col-lg-4 cust-merged-list border-end bg-white">
						<div class="cust-list-header d-flex flex-wrap align-items-center gap-2 px-3 py-2 border-bottom bg-light">
							<div class="position-relative flex-fill">
								<i class="ti ti-search position-absolute top-50 translate-middle-y text-secondary" style="left: 0.65rem"></i>
								<input
									v-model="search"
									type="search"
									class="form-control form-control-sm ps-5 pe-5"
									:placeholder="t('Search customer…')"
									@input="onSearchInput"
								/>
								<kbd class="position-absolute top-50 translate-middle-y text-secondary font-monospace" style="right: 0.5rem; font-size: 0.68rem">⌘K</kbd>
							</div>
							<button type="button" class="btn btn-sm btn-primary" @click="openCreate">
								<i class="ti ti-plus me-1"></i>{{ t("New") }}
							</button>
						</div>
						<div class="p-2 border-bottom bg-light d-flex gap-2 flex-wrap align-items-center">
							<Select v-if="availableGroups.length" v-model="filterGroup" size="sm" :options="groupFilterOptions" style="max-width: 140px" />
							<Select v-if="availableTerritories.length" v-model="filterTerritory" size="sm" :options="territoryFilterOptions" style="max-width: 140px" />
							<label class="form-check form-check-inline mb-0">
								<input
									v-model="onlyWithBalance"
									type="checkbox"
									class="form-check-input"
									@change="loadCustomers"
								/>
								<span class="form-check-label small">{{ t("Only with balance") }}</span>
							</label>
						</div>
						
						<div class="cust-list-scroll" style="overflow-y: auto; height: calc(100vh - 12rem);">
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
									<button type="button" class="btn btn-primary btn-sm" @click="openCreate">
										<i class="ti ti-user-plus me-1"></i>{{ t("Add customer") }}
									</button>
								</template>
							</EmptyState>
							<div v-else class="table-responsive m-0">
								<table class="table table-vcenter card-table table-hover table-no-stripe m-0">
									<thead>
										<tr>
											<th class="cursor-pointer select-none py-2" @click="toggleSort('name')">
												{{ t("Name") }}
												<i v-if="sortField === 'name'" :class="sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
											</th>
											<th class="text-end cursor-pointer select-none py-2" @click="toggleSort('balance')">
												{{ t("Balance") }}
												<i v-if="sortField === 'balance'" :class="sortAsc ? 'ti ti-arrow-up' : 'ti ti-arrow-down'"></i>
											</th>
										</tr>
									</thead>
									<tbody>
										<tr
											v-for="c in filteredCustomers"
											:key="c.name"
											:class="{ 'table-active': selected?.name === c.name }"
											class="cursor-pointer"
											@click="selectCustomer(c)"
										>
											<td>
												<div class="d-flex align-items-center gap-2">
													<PartyAvatar :name="c.customer_name || c.name" size="sm" class="flex-shrink-0" />
													<div class="text-truncate min-w-0" style="max-width: 170px;">
														<div class="fw-semibold text-truncate text-body">{{ c.customer_name }}</div>
														<div class="small stbl-subtext font-monospace text-truncate">{{ c.name }}</div>
													</div>
												</div>
											</td>
											<td class="text-end font-monospace stbl-amount align-middle">
												<div
													:class="{
														'text-red': Number(c.balance_acc ?? c.balance_base) > 0,
														'text-green': Number(c.balance_acc ?? c.balance_base) < 0,
														'text-secondary': !Number(c.balance_acc ?? c.balance_base),
													}"
												>
													{{ formatMoney(
														c.balance_acc ?? c.balance_base,
														c.account_currency || currency,
														user.language,
													) }}
												</div>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
						<div v-if="filteredCustomers.length" class="cust-list-footer p-3 border-top bg-light d-flex align-items-center justify-content-between">
							<span class="text-secondary small fw-semibold">{{ t("Total receivable") }}</span>
							<span class="font-monospace fw-bold text-body">
								{{ formatMoney(totalReceivable, currency, user.language) }}
							</span>
						</div>
					</div>

					<!-- Right side: details / cockpit -->
					<div class="col-12 col-md-7 col-lg-8 cust-merged-pane bg-light" style="min-height: calc(100vh - 6rem);">
						<!-- Cockpit View -->
						<div v-if="!selected" class="p-4 d-flex flex-column gap-4">
							<div class="row g-3">
								<div class="col-md-6">
									<div class="card bg-white shadow-sm border-0">
										<div class="card-body d-flex align-items-center gap-3">
											<span class="bg-primary-lt text-primary avatar avatar-md rounded-2">
												<i class="ti ti-currency-dollar fs-2"></i>
											</span>
											<div>
												<div class="text-secondary small fw-semibold text-uppercase">{{ t("Total receivable") }}</div>
												<div class="h2 mb-0 font-monospace stbl-amount text-body fw-bold">
													{{ formatMoney(cockpitData?.total_receivable || 0, currency, user.language) }}
												</div>
											</div>
										</div>
									</div>
								</div>
								<div class="col-md-6">
									<div class="card bg-white shadow-sm border-0">
										<div class="card-body d-flex align-items-center gap-3">
											<span class="bg-green-lt text-green avatar avatar-md rounded-2">
												<i class="ti ti-cash-banknote fs-2"></i>
											</span>
											<div>
												<div class="text-secondary small fw-semibold text-uppercase">{{ t("Payments received today") }}</div>
												<div class="h2 mb-0 font-monospace stbl-amount text-body fw-bold">
													{{ formatMoney(cockpitData?.payments_received_today || 0, currency, user.language) }}
												</div>
											</div>
										</div>
									</div>
								</div>
							</div>

							<!-- Sparkline Trend -->
							<div class="card bg-white shadow-sm border-0">
								<div class="card-body">
									<h4 class="card-title text-secondary mb-3">{{ t("Receivable Trend (Last 8 Weeks)") }}</h4>
									<div v-if="cockpitLoading" class="text-center py-4">
										<div class="spinner-border text-primary spinner-border-sm"></div>
									</div>
									<div v-else-if="cockpitData?.trend_8_weeks?.length">
										<ApexChart
											type="line"
											height="120"
											:series="trendSeries"
											:options="trendOptions"
										/>
									</div>
								</div>
							</div>

							<!-- Top 10 Debtors -->
							<div class="card bg-white shadow-sm border-0">
								<div class="card-header py-2 border-bottom">
									<h4 class="card-title text-secondary">{{ t("Top 10 Debtors") }}</h4>
								</div>
								<div class="list-group list-group-flush list-group-hoverable">
									<div
										v-for="d in cockpitData?.top_debtors"
										:key="d.name"
										class="list-group-item cursor-pointer py-2 px-3 border-bottom bg-transparent"
										@click="selectCustomer(d)"
									>
										<div class="row align-items-center g-2">
											<div class="col-auto">
												<PartyAvatar :name="d.customer_name || d.name" size="sm" />
											</div>
											<div class="col text-truncate">
												<div class="text-body fw-semibold text-truncate">{{ d.customer_name }}</div>
												<div class="stbl-subtext small font-monospace text-truncate">{{ d.name }}</div>
											</div>
											<div class="col-auto font-monospace stbl-amount text-red fw-bold">
												{{ formatMoney(d.balance_acc ?? d.balance, d.account_currency || currency, user.language) }}
											</div>
										</div>
									</div>
									<div v-if="!cockpitData?.top_debtors?.length" class="text-center py-4 text-secondary">
										{{ t("No debtors found.") }}
									</div>
								</div>
							</div>
						</div>

						<!-- Selected Customer View -->
						<template v-else>
							<!-- Detail Header -->
							<div class="p-3 bg-white border-bottom shadow-sm d-flex align-items-center gap-3 flex-wrap">
								<PartyAvatar :name="selected.customer_name || selected.name" size="lg" class="rounded-3" />
								<div class="min-w-0 flex-fill">
									<h2 class="m-0 text-truncate text-body fw-bold">{{ selected.customer_name }}</h2>
									<div class="small stbl-subtext font-monospace">{{ selected.name }}</div>
								</div>
								<div class="d-flex gap-2">
									<button type="button" class="btn btn-sm btn-outline-secondary" @click="openEdit(selected)">
										<i class="ti ti-pencil me-1"></i>{{ t("Edit") }}
									</button>
									<button type="button" class="btn btn-sm btn-outline-secondary" @click="partyPayOpen = true">
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

							<!-- KPI Strip -->
							<div class="px-3 py-2 bg-light border-bottom">
								<div class="row g-2">
									<div class="col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Balance") }}</div>
											<BalanceChip
												:value="selected.balance_acc ?? selected.balance_base"
												:currency="selected.account_currency || currency"
												:language="user.language"
												party-type="Customer"
												size="md"
												class="w-100 justify-content-center"
											/>
										</div>
									</div>
									<div class="col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Overdue") }}</div>
											<div class="h3 mb-0 font-monospace stbl-amount" :class="Number(selectedDetail?.overdue_amount || 0) > 0 ? 'text-red fw-bold' : 'text-body'">
												{{ formatMoney(selectedDetail?.overdue_amount || 0, selectedDetail?.overdue_currency || selected.account_currency || currency, user.language) }}
											</div>
										</div>
									</div>
									<div class="col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Lifetime Sales") }}</div>
											<div class="h3 mb-0 font-monospace stbl-amount text-body">
												{{ formatMoney(selectedDetail?.lifetime_amount ?? selectedDetail?.lifetime_base ?? 0, selectedDetail?.lifetime_currency || currency, user.language) }}
											</div>
										</div>
									</div>
									<div class="col-md-3">
										<div class="card border bg-white py-2 px-3 text-center shadow-none rounded-2">
											<div class="text-secondary small text-uppercase fw-semibold mb-1">{{ t("Last Payment") }}</div>
											<div class="h3 mb-0 text-body">
												{{ selectedDetail?.last_payment_date ? formatDate(selectedDetail.last_payment_date) : "—" }}
											</div>
										</div>
									</div>
								</div>
							</div>

							<!-- Tabs Header -->
							<div class="bg-white border-bottom">
								<ul class="nav nav-tabs border-0 px-3">
									<li class="nav-item">
										<a
											href="#"
											class="nav-link border-0 border-bottom-2 py-3"
											:class="{ active: currentTab === 'ledger', 'border-primary': currentTab === 'ledger' }"
											@click.prevent="currentTab = 'ledger'"
										>
											{{ t("Ledger") }}
										</a>
									</li>
									<li class="nav-item">
										<a
											href="#"
											class="nav-link border-0 border-bottom-2 py-3"
											:class="{ active: currentTab === 'orders', 'border-primary': currentTab === 'orders' }"
											@click.prevent="currentTab = 'orders'"
										>
											{{ t("Orders") }}
											<span class="badge bg-secondary-subtle text-secondary ms-1">{{ custOrders.length }}</span>
										</a>
									</li>
									<li class="nav-item">
										<a
											href="#"
											class="nav-link border-0 border-bottom-2 py-3"
											:class="{ active: currentTab === 'invoices', 'border-primary': currentTab === 'invoices' }"
											@click.prevent="currentTab = 'invoices'"
										>
											{{ t("Invoices") }}
											<span class="badge bg-secondary-subtle text-secondary ms-1">{{ recentInvoices.length }}</span>
										</a>
									</li>
								</ul>
							</div>

							<!-- Tab Panes -->
							<div class="cust-tab-content bg-white" style="overflow-y: auto; height: calc(100vh - 20rem);">
								<!-- LEDGER TAB -->
								<div v-if="currentTab === 'ledger'" class="d-flex flex-column h-100">
									<!-- Ledger controls -->
									<div class="p-3 border-bottom bg-light">
										<div class="row g-2 align-items-center">
											<div class="col-auto">
												<Select v-model="ledgerTypeFilter" size="sm" :options="voucherTypes" style="width: 140px" />
											</div>
											<div class="col-auto">
												<DateInput v-model="ledgerFromDate" size="sm" style="width: 110px" />
											</div>
											<div class="col-auto">
												<DateInput v-model="ledgerToDate" size="sm" style="width: 110px" />
											</div>
											<div class="col">
												<input v-model="ledgerSearch" type="search" class="form-control form-control-sm" :placeholder="t('Search voucher…')" />
											</div>
											<div class="col-auto">
												<button
													type="button"
													class="btn btn-sm btn-ghost-secondary px-2"
													@click="ledgerSortAsc = !ledgerSortAsc"
													:title="t('Toggle date sort')"
												>
													<i class="ti fs-3" :class="ledgerSortAsc ? 'ti-arrow-narrow-up' : 'ti-arrow-narrow-down'"></i>
												</button>
											</div>
											<div class="col-auto">
												<button
													type="button"
													class="btn btn-sm btn-outline-secondary"
													:disabled="!ledger?.entries?.length"
													:title="t('Professional Excel export of this ledger')"
													@click="exportLedgerXlsx"
												>
													<i class="ti ti-file-spreadsheet me-1"></i>{{ t("Excel") }}
												</button>
											</div>
										</div>
									</div>

									<div class="flex-fill position-relative">
										<div v-if="ledgerLoading" class="text-center py-5">
											<div class="spinner-border text-primary"></div>
										</div>
										<div v-else-if="ledgerError" class="alert alert-danger m-3">{{ ledgerError }}</div>
										<div v-else-if="!filteredLedgerRows.length" class="text-secondary text-center py-5">
											{{ t("No transactions in this period.") }}
										</div>
										<template v-else>
											<div v-if="ledgerCurrencyMixed" class="alert alert-warning m-3 small mb-2" role="alert">
												<i class="ti ti-alert-triangle me-1"></i>
												{{ t("Ledger spans multiple account currencies; amounts shown in base currency.") }}
											</div>
											<table class="table table-vcenter table-sm card-table m-0">
												<thead class="sticky-top bg-white border-bottom">
													<tr>
														<th class="py-2">{{ t("Date") }}</th>
														<th class="py-2">{{ t("Voucher") }}</th>
														<th class="text-end py-2">{{ t("Debit") }}</th>
														<th class="text-end py-2">{{ t("Credit") }}</th>
														<th class="text-end py-2">{{ t("Balance") }} ({{ ledgerCurrency }})</th>
													</tr>
												</thead>
												<tbody>
													<!-- Opening Balance Row -->
													<tr v-if="Number(ledgerCurrencyMixed ? ledger?.opening_base : ledger?.opening_acc) !== 0" class="text-secondary bg-transparent">
														<td colspan="4" class="text-end fst-italic py-2">{{ t("Opening balance") }}</td>
														<td class="text-end font-monospace fst-italic py-2">
															{{ formatMoney(
																ledgerCurrencyMixed ? ledger.opening_base : ledger.opening_acc,
																ledgerCurrency,
																user.language,
															) }}
														</td>
													</tr>
													<tr v-for="e in filteredLedgerRows" :key="e.name">
														<td class="text-nowrap small py-2">{{ formatDateTime(e.posting_date) }}</td>
														<td class="py-2">
															<div class="small text-secondary fw-semibold">{{ e.voucher_type }}</div>
															<button
																v-if="e.voucher_no"
																type="button"
																class="btn btn-link p-0 font-monospace small text-primary fw-semibold"
																@click="openVoucher(e)"
															>
																{{ e.voucher_no }}
															</button>
															<div v-else class="font-monospace small">—</div>
															<div class="small text-muted font-monospace mt-0.5 text-truncate" style="max-width:280px" :title="e.display_remark">{{ e.display_remark || "—" }}</div>
														</td>
														<td class="text-end font-monospace small py-2 align-middle">
															<span v-if="Number(ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency) > 0">
																{{ formatMoney(
																	ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency,
																	ledgerCurrencyMixed ? currency : (e.account_currency || ledgerCurrency),
																	user.language,
																) }}
															</span>
															<span v-else class="text-secondary">—</span>
														</td>
														<td class="text-end font-monospace small py-2 align-middle">
															<span v-if="Number(ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency) > 0">
																{{ formatMoney(
																	ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency,
																	ledgerCurrencyMixed ? currency : (e.account_currency || ledgerCurrency),
																	user.language,
																) }}
															</span>
															<span v-else class="text-secondary">—</span>
														</td>
														<td class="text-end font-monospace fw-semibold small py-2 align-middle">
															{{ formatMoney(
																ledgerCurrencyMixed ? e.running_base : e.running_acc,
																ledgerCurrency,
																user.language,
															) }}
														</td>
													</tr>
												</tbody>
												<tfoot v-if="ledgerRows.length" class="bg-light border-top">
													<tr>
														<th colspan="4" class="text-end py-2 fw-bold">{{ t("Closing balance") }}</th>
														<th class="text-end font-monospace py-2 fw-bold">
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
								</div>

								<!-- ORDERS TAB -->
								<div v-if="currentTab === 'orders'" class="p-3">
									<div v-if="custOrdersLoading" class="text-center py-5">
										<div class="spinner-border text-primary"></div>
									</div>
									<EmptyState
										v-else-if="!custOrders.length"
										icon="ti-clipboard-list"
										tone="primary"
										:title="t('No orders yet')"
										:subtitle="t('Create a new Sales Order for this customer to begin.')"
										class="py-4 bg-transparent border-0"
									>
										<template #actions>
											<router-link
												:to="{ path: '/sales/orders/new', query: { new_for: selected.name } }"
												class="btn btn-sm btn-primary"
											>
												<i class="ti ti-plus me-1"></i>{{ t("Create first order") }}
											</router-link>
										</template>
									</EmptyState>
									<div v-else class="table-responsive">
										<table class="table table-vcenter table-hover card-table">
											<thead>
												<tr>
													<th>{{ t("Order #") }}</th>
													<th>{{ t("Date") }}</th>
													<th class="text-end">{{ t("Total") }}</th>
													<th>{{ t("Status") }}</th>
												</tr>
											</thead>
											<tbody>
												<tr
													v-for="o in custOrders"
													:key="o.name"
													class="cursor-pointer"
													@click="openVoucher({ voucher_type: 'Sales Order', voucher_no: o.name })"
												>
													<td class="font-monospace text-primary fw-semibold">{{ o.name }}</td>
													<td>{{ formatDate(o.transaction_date) }}</td>
													<td class="text-end font-monospace">
														{{ formatMoney(o.grand_total, o.currency || currency, user.language) }}
													</td>
													<td>
														<span class="badge" :class="getStatusBadgeClass('Sales Order', o.status)">
															{{ t(o.status) }}
														</span>
													</td>
												</tr>
											</tbody>
										</table>
									</div>
								</div>

								<!-- INVOICES TAB -->
								<div v-if="currentTab === 'invoices'" class="p-3">
									<div class="table-responsive">
										<table class="table table-vcenter table-hover card-table">
											<thead>
												<tr>
													<th>{{ t("Invoice #") }}</th>
													<th>{{ t("Date") }}</th>
													<th class="text-end">{{ t("Total") }}</th>
													<th class="text-end">{{ t("Outstanding") }}</th>
													<th>{{ t("Status") }}</th>
												</tr>
											</thead>
											<tbody>
												<tr
													v-for="inv in recentInvoices"
													:key="inv.name"
													class="cursor-pointer"
													@click="openVoucher({ voucher_type: 'Sales Invoice', voucher_no: inv.name })"
												>
													<td class="font-monospace text-primary fw-semibold">{{ inv.name }}</td>
													<td>{{ formatDate(inv.posting_date) }}</td>
													<td class="text-end font-monospace stbl-amount">
														{{ formatMoney(inv.grand_total, inv.currency || currency, user.language) }}
													</td>
													<td class="text-end font-monospace stbl-amount">
														{{ formatMoney(inv.outstanding_amount, inv.currency || currency, user.language) }}
													</td>
													<td>
														<span class="badge" :class="getStatusBadgeClass('Sales Invoice', inv.status)">
															{{ t(inv.status) }}
														</span>
													</td>
												</tr>
												<tr v-if="!recentInvoices.length">
													<td colspan="5" class="text-center py-4 text-secondary">
														{{ t("No invoices found.") }}
													</td>
												</tr>
											</tbody>
										</table>
									</div>
								</div>
							</div>
						</template>
					</div>
				</div>
			</div>
		</div>
	</div>

	<!-- Voucher Drawer -->
	<template v-if="voucherOpen">
		<div class="offcanvas-backdrop fade show" @click="closeVoucher"></div>
		<div class="offcanvas offcanvas-end show" tabindex="-1" style="width: min(520px, 100vw)">
			<div class="offcanvas-header border-bottom">
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
									<span class="badge" :class="getStatusBadgeClass('Sales Invoice', voucherDetail.status)">
										{{ t(voucherDetail.status) }}
									</span>
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
									<span class="badge" :class="getStatusBadgeClass('Sales Order', voucherDetail.status)">
										{{ t(voucherDetail.status) }}
									</span>
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
										<td class="small">{{ ac.account_name || ac.account }}</td>
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

	<!-- Create/Edit Modal -->
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

	<!-- Payment Entry Modal -->
	<PartyPaymentModal
		v-if="selected"
		:open="partyPayOpen"
		party-type="Customer"
		:party="selected.name"
		:company="activeCompany"
		@close="partyPayOpen = false"
		@paid="partyPayOpen = false; loadLedger(selected); loadCustOrders(selected); selectCustomer(selected);"
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

.cust-merged-list {
	display: flex;
	flex-direction: column;
}

.cust-merged-pane {
	display: flex;
	flex-direction: column;
}

.cust-list-scroll {
	overflow-y: auto;
}

.cust-list-footer {
	margin-top: auto;
}
</style>
