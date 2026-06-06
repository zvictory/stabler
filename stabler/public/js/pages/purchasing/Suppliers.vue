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
const suppliers = ref([]);
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

const SUPPLIER_TYPES = ["Company", "Individual", "Partnership"];
const supplierTypeOptions = computed(() =>
	SUPPLIER_TYPES.map((st) => ({ value: st, label: t(st) }))
);
const createOpen = ref(false);
const editMode = ref(false);
const editingName = ref("");
const submitting = ref(false);
const submitError = ref("");
const groupOptions = ref([]);
const currencyOptions = ref([]);
const priceListOptions = ref([]);
const optionsLoaded = ref(false);

function blankSupplier() {
	return {
		supplier_name: "",
		supplier_type: "Company",
		supplier_group: "",
		country: "",
		email_id: "",
		mobile_no: "",
		tax_id: "",
		default_currency: "",
		default_price_list: "",
	};
}
const form = ref(blankSupplier());

const currency = computed(
	() =>
		companyCurrency.value ||
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const filteredSuppliers = computed(() => {
	const term = search.value.trim().toLowerCase();
	if (!term) return suppliers.value;
	return suppliers.value.filter(
		(s) =>
			(s.supplier_name || "").toLowerCase().includes(term) ||
			(s.name || "").toLowerCase().includes(term)
	);
});

const totalPayable = computed(() =>
	suppliers.value.reduce((sum, s) => sum + Number(s.balance_base || 0), 0)
);

const ledgerRows = computed(() => {
	const e = ledger.value?.entries || [];
	let runBase = Number(ledger.value?.opening_base || 0);
	let runAcc = Number(ledger.value?.opening_acc || 0);
	return e.map((row) => {
		// Payables sign convention: positive balance = we owe (credit - debit).
		runBase += Number(row.credit || 0) - Number(row.debit || 0);
		runAcc +=
			Number(row.credit_in_account_currency || 0) -
			Number(row.debit_in_account_currency || 0);
		return { ...row, running_base: runBase, running_acc: runAcc };
	});
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

async function loadSuppliers() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const res = await call("stabler.api.purchasing.list_suppliers_with_balances", {
			company: activeCompany.value,
			search: search.value || "",
			only_with_balance: onlyWithBalance.value ? 1 : 0,
			limit: 500,
		});
		suppliers.value = res.rows || [];
		companyCurrency.value = res.company_currency || "";
		if (selected.value && !suppliers.value.find((s) => s.name === selected.value.name)) {
			selected.value = null;
			ledger.value = null;
		}
	} catch (err) {
		error.value = err?.message || t("Failed to load suppliers.");
	} finally {
		loading.value = false;
	}
}

async function refreshBalances() {
	balancesRefreshing.value = true;
	try {
		await loadSuppliers();
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

async function loadLedger(supplier) {
	if (!supplier) return;
	ledgerLoading.value = true;
	ledgerError.value = "";
	try {
		const params = {
			company: activeCompany.value,
			supplier: supplier.name,
			limit: 1000,
		};
		if (ledgerFromDate.value) params.from_date = ledgerFromDate.value;
		if (ledgerToDate.value) params.to_date = ledgerToDate.value;
		ledger.value = await call("stabler.api.purchasing.supplier_ledger", params);
	} catch (err) {
		ledger.value = null;
		ledgerError.value = err?.message || t("Failed to load ledger.");
	} finally {
		ledgerLoading.value = false;
	}
}

function selectSupplier(s) {
	selected.value = s;
	suppOrders.value = [];
	if (!ledgerFromDate.value && !ledgerToDate.value) {
		const r = defaultDateRange();
		ledgerFromDate.value = r.from;
		ledgerToDate.value = r.to;
	}
	loadLedger(s);
	loadSuppOrders(s);
}

// ── P1.3: Purchase orders list ───────────────────────────────────────────────
const suppOrders = ref([]);
const suppOrdersLoading = ref(false);

async function loadSuppOrders(supplier) {
	if (!supplier?.name) return;
	suppOrdersLoading.value = true;
	try {
		suppOrders.value = await call("stabler.api.purchasing.list_purchase_orders", {
			company: activeCompany.value,
			supplier: supplier.name,
			limit: 20,
		});
	} catch {
		suppOrders.value = [];
	} finally {
		suppOrdersLoading.value = false;
	}
}

function orderStatusBadge(status) {
	const map = {
		Draft: "bg-secondary-lt",
		"To Receive and Bill": "bg-yellow-lt",
		"To Bill": "bg-orange-lt",
		"To Receive": "bg-blue-lt",
		Completed: "bg-green-lt",
		Cancelled: "bg-red-lt",
		Closed: "bg-secondary-lt",
		"On Hold": "bg-secondary-lt",
	};
	return map[status] || "bg-secondary-lt";
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
		if (type === "Purchase Invoice") {
			data = await call("stabler.api.purchasing.purchase_invoice_detail", { name });
		} else if (type === "Purchase Order") {
			data = await call("stabler.api.purchasing.purchase_order_detail", { name });
		} else if (type === "Payment Entry") {
			data = await call("stabler.api.money.payment_entry_detail", { name });
		} else if (type === "Journal Entry") {
			data = await call("stabler.api.money.journal_entry_detail", { name });
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
	searchTimer = setTimeout(loadSuppliers, 250);
}

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const [groups, currencies, priceLists] = await Promise.all([
			call("stabler.api.purchasing.list_supplier_groups", { limit: 200 }),
			call("stabler.api.sales.list_currencies"),
			call("stabler.api.sales.list_price_lists", { buying_only: 1, limit: 200 }),
		]);
		groupOptions.value = groups || [];
		currencyOptions.value = currencies || [];
		priceListOptions.value = priceLists || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || t("Failed to load options.");
	}
}
function openCreate() {
	editMode.value = false;
	editingName.value = "";
	form.value = blankSupplier();
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}
async function openEdit(s) {
	editMode.value = true;
	editingName.value = s.name;
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
	try {
		form.value = await call("stabler.api.purchasing.get_supplier", { name: s.name });
	} catch (err) {
		submitError.value = err?.message || t("Failed to load supplier.");
	}
}
async function submitCreate() {
	submitError.value = "";
	const f = form.value;
	if (!f.supplier_name.trim()) return (submitError.value = t("Supplier name is required."));
	submitting.value = true;
	try {
		if (editMode.value) {
			await call("stabler.api.purchasing.update_supplier", {
				name: editingName.value,
				supplier_name: f.supplier_name.trim(),
				supplier_type: f.supplier_type,
				supplier_group: f.supplier_group || null,
				country: f.country || null,
				email_id: f.email_id || null,
				mobile_no: f.mobile_no || null,
				tax_id: f.tax_id || null,
				default_price_list: f.default_price_list || null,
				default_currency: f.default_currency || null,
			});
		} else {
			await call("stabler.api.purchasing.create_supplier", {
				supplier_name: f.supplier_name.trim(),
				supplier_type: f.supplier_type,
				supplier_group: f.supplier_group || null,
				country: f.country || null,
				email_id: f.email_id || null,
				mobile_no: f.mobile_no || null,
				tax_id: f.tax_id || null,
				default_price_list: f.default_price_list || null,
				default_currency: f.default_currency || null,
			});
		}
		createOpen.value = false;
		await loadSuppliers();
		if (editMode.value && selected.value?.name === editingName.value) {
			const updated = suppliers.value.find((s) => s.name === editingName.value);
			if (updated) selected.value = updated;
		}
	} catch (err) {
		submitError.value =
			err?.message || t(editMode.value ? "Failed to update supplier." : "Failed to create supplier.");
	} finally {
		submitting.value = false;
	}
}
async function deleteSupplier() {
	if (
		!window.confirm(
			`${t("Delete supplier")} "${form.value.supplier_name || editingName.value}"?`
		)
	)
		return;
	submitting.value = true;
	try {
		await call("stabler.api.purchasing.delete_supplier", { name: editingName.value });
		createOpen.value = false;
		if (selected.value?.name === editingName.value) {
			selected.value = null;
			ledger.value = null;
		}
		await loadSuppliers();
	} catch (err) {
		submitError.value = err?.message || t("Failed to delete supplier.");
	} finally {
		submitting.value = false;
	}
}

onMounted(loadSuppliers);
watch(activeCompany, () => {
	selected.value = null;
	ledger.value = null;
	loadSuppliers();
});
</script>

<template>
	<div class="page-body">
		<div class="container-fluid">
			<div class="row g-2 align-items-start">
		<!-- Left sidebar: supplier list -->
		<div class="col-12 col-md-5 col-lg-4">
			<div class="card">
				<div class="card-header d-flex flex-wrap align-items-center gap-2">
					<div class="card-title m-0">{{ t("Suppliers") }}</div>
					<button
						type="button"
						class="btn btn-sm btn-outline-secondary"
						:disabled="balancesRefreshing"
						:title="t('Refresh balances')"
						@click="refreshBalances"
					>
						<span v-if="balancesRefreshing" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
					<button type="button" class="btn btn-sm btn-success ms-auto" @click="openCreate">
						<i class="ti ti-plus me-1"></i>{{ t("New") }}
					</button>
				</div>
				<div class="card-body py-2 border-bottom">
					<input
						v-model="search"
						type="search"
						class="form-control form-control-sm"
						:placeholder="t('Search supplier…')"
						@input="onSearchInput"
					/>
					<label class="form-check form-check-inline mt-2 mb-0">
						<input
							v-model="onlyWithBalance"
							type="checkbox"
							class="form-check-input"
							@change="loadSuppliers"
						/>
						<span class="form-check-label small">{{ t("Only with balance") }}</span>
					</label>
				</div>
				<div class="card-body p-0" style="overflow-y: auto; max-height: calc(100vh - 18rem)">
					<div v-if="loading" class="text-center py-5">
						<div class="spinner-border text-primary"></div>
					</div>
					<div v-else-if="error" class="alert alert-danger m-2">{{ error }}</div>
					<EmptyState
						v-else-if="!filteredSuppliers.length"
						icon="ti-truck-delivery"
						accentIcon="ti-plus"
						tone="orange"
						:title="t('No suppliers')"
						:subtitle="t('Add your first supplier to start recording bills and purchases.')"
					>
						<template #actions>
							<button type="button" class="btn btn-primary" @click="openCreate">
								<i class="ti ti-plus me-1"></i>{{ t("Add supplier") }}
							</button>
						</template>
					</EmptyState>
					<table v-else class="table table-vcenter table-hover m-0">
						<tbody>
							<tr
								v-for="s in filteredSuppliers"
								:key="s.name"
								style="cursor: pointer"
								:class="{ 'table-active': selected?.name === s.name }"
								@click="selectSupplier(s)"
							>
								<td>
									<div class="d-flex align-items-start gap-1">
										<div class="flex-grow-1 min-w-0">
											<div class="fw-semibold text-truncate" style="max-width: 200px">
												{{ s.supplier_name }}
											</div>
											<div class="small text-secondary font-monospace text-truncate">
												{{ s.name }}
											</div>
										</div>
										<button
											type="button"
											class="btn btn-sm btn-ghost-secondary flex-shrink-0"
											:title="t('Edit')"
											@click.stop="openEdit(s)"
										>
											<i class="ti ti-pencil"></i>
										</button>
									</div>
								</td>
								<td class="text-end text-nowrap font-monospace">
									<div
										:class="{
											'text-red': Number(s.balance_acc ?? s.balance_base) > 0,
											'text-secondary': !Number(s.balance_acc ?? s.balance_base),
										}"
									>
										{{ formatMoney(
											s.balance_acc ?? s.balance_base,
											s.account_currency || currency,
											user.language,
										) }}
									</div>
									<div
										v-if="s.account_currency && s.account_currency !== currency"
										class="small text-secondary"
									>
										{{ formatMoney(s.balance_base, currency, user.language) }}
									</div>
								</td>
							</tr>
						</tbody>
						<tfoot v-if="filteredSuppliers.length">
							<tr class="bg-light">
								<th>{{ t("Total payable") }}</th>
								<th class="text-end font-monospace">
									{{ formatMoney(totalPayable, currency, user.language) }}
								</th>
							</tr>
						</tfoot>
					</table>
				</div>
			</div>
		</div>

		<!-- Right pane: selected supplier ledger -->
		<div class="col-12 col-md-7 col-lg-8">
			<div v-if="!selected" class="card">
				<div class="card-body d-flex align-items-center justify-content-center text-secondary">
					<div class="text-center">
						<i class="ti ti-truck" style="font-size: 3rem"></i>
						<div class="mt-2">{{ t("Select a supplier to view transactions") }}</div>
					</div>
				</div>
			</div>
			<div v-else class="card">
				<div class="card-header">
					<div class="d-flex align-items-center gap-3 flex-wrap">
						<span class="avatar avatar-lg bg-orange-lt">
							{{ (selected.supplier_name || selected.name).slice(0, 2).toUpperCase() }}
						</span>
						<div>
							<h3 class="m-0">{{ selected.supplier_name }}</h3>
							<div class="small text-secondary font-monospace">{{ selected.name }}</div>
						</div>
						<button
							type="button"
							class="btn btn-sm btn-outline-secondary"
							:title="t('Edit')"
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
						<div class="ms-auto text-end">
							<div class="small text-secondary">{{ t("Balance") }}</div>
							<div
								class="h2 m-0 font-monospace"
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
				</div>
				<!-- P1.3: Purchase Orders list -->
				<div v-if="suppOrders.length || suppOrdersLoading" class="card-body py-2 border-bottom">
					<div class="small fw-semibold text-secondary mb-2">{{ t("Orders") }}</div>
					<div v-if="suppOrdersLoading" class="text-center py-2">
						<div class="spinner-border spinner-border-sm text-primary"></div>
					</div>
					<div v-else-if="!suppOrders.length" class="text-secondary small">{{ t("No orders.") }}</div>
					<div v-else class="d-flex flex-wrap gap-1">
						<button
							v-for="o in suppOrders"
							:key="o.name"
							type="button"
							class="btn btn-sm btn-ghost-secondary text-start"
							style="min-width: 0"
							@click="openVoucher({ voucher_type: 'Purchase Order', voucher_no: o.name })"
						>
							<span :class="['badge me-1', orderStatusBadge(o.status)]">{{ t(o.status) }}</span>
							<span class="font-monospace small">{{ o.name }}</span>
							<span class="text-secondary small ms-1">{{ formatDate(o.transaction_date) }}</span>
							<span class="font-monospace small ms-1 text-primary">{{ formatMoney(o.grand_total, o.currency, user.language) }}</span>
						</button>
					</div>
				</div>

				<div class="card-body py-2 border-bottom">
					<div class="row g-2 align-items-end">
						<div class="col-auto">
							<label class="form-label small mb-1">{{ t("From") }}</label>
							<DateInput v-model="ledgerFromDate" size="sm" @blur="loadLedger(selected)" />
						</div>
						<div class="col-auto">
							<label class="form-label small mb-1">{{ t("To") }}</label>
							<DateInput v-model="ledgerToDate" size="sm" @blur="loadLedger(selected)" />
						</div>
						<div class="col-auto">
							<button
								type="button"
								class="btn btn-sm btn-outline-secondary"
								:disabled="ledgerLoading"
								@click="loadLedger(selected)"
							>
								<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
							</button>
						</div>
					</div>
				</div>
				<div class="card-body p-0" style="overflow-y: auto; max-height: calc(100vh - 22rem)">
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
						<table class="table table-vcenter table-sm m-0">
							<thead class="sticky-top bg-white">
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
									<td class="text-nowrap">{{ formatDateTime(e.posting_date) }}</td>
									<td>
										<div class="small text-secondary">{{ e.voucher_type }}</div>
										<button
											v-if="e.voucher_no"
											type="button"
											class="btn btn-link p-0 font-monospace small"
											@click="openVoucher(e)"
										>
											{{ e.voucher_no }}
										</button>
										<div v-else class="font-monospace small">—</div>
									</td>
									<td class="text-end font-monospace">
										<span v-if="Number(ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency) > 0">
											{{ formatMoney(
												ledgerCurrencyMixed ? e.debit : e.debit_in_account_currency,
												ledgerCurrencyMixed ? currency : (e.account_currency || ledgerCurrency),
												user.language,
											) }}
										</span>
										<span v-else class="text-secondary">—</span>
									</td>
									<td class="text-end font-monospace">
										<span v-if="Number(ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency) > 0">
											{{ formatMoney(
												ledgerCurrencyMixed ? e.credit : e.credit_in_account_currency,
												ledgerCurrencyMixed ? currency : (e.account_currency || ledgerCurrency),
												user.language,
											) }}
										</span>
										<span v-else class="text-secondary">—</span>
									</td>
									<td class="text-end font-monospace fw-semibold">
										{{ formatMoney(
											ledgerCurrencyMixed ? e.running_base : e.running_acc,
											ledgerCurrency,
											user.language,
										) }}
									</td>
								</tr>
							</tbody>
						<tfoot v-if="ledgerRows.length" class="bg-light">
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
					<!-- Purchase Invoice detail -->
					<template v-if="voucherDetail._type === 'Purchase Invoice'">
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

					<!-- Purchase Order detail -->
					<template v-else-if="voucherDetail._type === 'Purchase Order'">
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
									<span :class="['badge', orderStatusBadge(voucherDetail.status)]">{{ t(voucherDetail.status) }}</span>
								</div>
							</div>
							<div class="datagrid-item">
								<div class="datagrid-title">{{ t("Grand total") }}</div>
								<div class="datagrid-content font-monospace">{{ formatMoney(voucherDetail.grand_total, voucherDetail.currency, user.language) }}</div>
							</div>
							<div v-if="Number(voucherDetail.per_received) > 0" class="datagrid-item">
								<div class="datagrid-title">{{ t("Received") }}</div>
								<div class="datagrid-content">{{ voucherDetail.per_received }}%</div>
							</div>
							<div v-if="Number(voucherDetail.per_billed) > 0" class="datagrid-item">
								<div class="datagrid-title">{{ t("Billed") }}</div>
								<div class="datagrid-content">{{ voucherDetail.per_billed }}%</div>
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
						<h5 class="modal-title">{{ editMode ? t("Edit supplier") : t("New supplier") }}</h5>
						<button type="button" class="btn-close" :aria-label="t('Close')" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
						<div class="row g-3">
							<div class="col-12">
								<label class="form-label">{{ t("Supplier name") }} <span class="text-danger">*</span></label>
								<input v-model="form.supplier_name" type="text" class="form-control" autofocus />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Type") }}</label>
								<Select v-model="form.supplier_type" :options="supplierTypeOptions" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Tax ID") }}</label>
								<input v-model="form.tax_id" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Supplier group") }}</label>
								<Select
									v-model="form.supplier_group"
									:options="groupOptions"
									value-key="name"
									label-key="name"
									:placeholder="t('— default —')"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Country") }}</label>
								<input v-model="form.country" type="text" class="form-control" :placeholder="t('Optional')" />
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
								<label class="form-label">{{ t("Currency") }}</label>
								<Select
									v-model="form.default_currency"
									class="font-monospace"
									:options="currencyOptions"
									value-key="name"
									label-key="name"
									:placeholder="t('— company default —')"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Buying price list") }}</label>
								<Select
									v-model="form.default_price_list"
									:options="priceListOptions"
									value-key="name"
									label-key="name"
									:placeholder="t('— none —')"
								/>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button
							v-if="editMode"
							type="button"
							class="btn btn-danger me-auto"
							:disabled="submitting"
							@click="deleteSupplier"
						>
							<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
						</button>
						<button type="button" class="btn btn-link link-secondary" @click="closeCreate" :disabled="submitting">
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submitting || !form.supplier_name.trim()"
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

	<!-- Party-level payment modal (Supplier) -->
	<PartyPaymentModal
		v-if="selected"
		:open="partyPayOpen"
		party-type="Supplier"
		:party="selected.name"
		:company="activeCompany"
		@close="partyPayOpen = false"
		@paid="partyPayOpen = false; loadLedger(selected)"
	/>
</template>
