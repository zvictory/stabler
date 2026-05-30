<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

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

const SUPPLIER_TYPES = ["Company", "Individual", "Partnership"];
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const groupOptions = ref([]);
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
	if (!ledgerFromDate.value && !ledgerToDate.value) {
		const r = defaultDateRange();
		ledgerFromDate.value = r.from;
		ledgerToDate.value = r.to;
	}
	loadLedger(s);
}

const VOUCHER_ROUTES = {
	"Purchase Invoice": "/purchasing/invoices",
	"Payment Entry": "/money/payments",
	"Journal Entry": "/money/journals",
};
function voucherLinkTo(entry) {
	const path = VOUCHER_ROUTES[entry?.voucher_type];
	if (!path || !entry?.voucher_no) return null;
	return { path, query: { open: entry.voucher_no } };
}

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(loadSuppliers, 250);
}

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const groups = await call("stabler.api.purchasing.list_supplier_groups", { limit: 200 });
		groupOptions.value = groups || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || t("Failed to load options.");
	}
}
function openCreate() {
	form.value = blankSupplier();
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}
async function submitCreate() {
	submitError.value = "";
	const f = form.value;
	if (!f.supplier_name.trim()) return (submitError.value = t("Supplier name is required."));
	submitting.value = true;
	try {
		await call("stabler.api.purchasing.create_supplier", {
			supplier_name: f.supplier_name.trim(),
			supplier_type: f.supplier_type,
			supplier_group: f.supplier_group || null,
			country: f.country || null,
			email_id: f.email_id || null,
			mobile_no: f.mobile_no || null,
			tax_id: f.tax_id || null,
		});
		createOpen.value = false;
		await loadSuppliers();
	} catch (err) {
		submitError.value = err?.message || t("Failed to create supplier.");
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
									<div class="fw-semibold text-truncate" style="max-width: 220px">
										{{ s.supplier_name }}
									</div>
									<div class="small text-secondary font-monospace text-truncate">
										{{ s.name }}
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
										<router-link
											v-if="voucherLinkTo(e)"
											:to="voucherLinkTo(e)"
											class="font-monospace small text-decoration-none"
										>
											{{ e.voucher_no }}
										</router-link>
										<div v-else class="font-monospace small">{{ e.voucher_no }}</div>
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

	<template v-if="createOpen">
		<div class="modal-backdrop fade show" @click="closeCreate"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-dialog-centered" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("New supplier") }}</h5>
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
								<select v-model="form.supplier_type" class="form-select">
									<option v-for="st in SUPPLIER_TYPES" :key="st" :value="st">{{ t(st) }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Tax ID") }}</label>
								<input v-model="form.tax_id" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Supplier group") }}</label>
								<select v-model="form.supplier_group" class="form-select">
									<option value="">{{ t("— default —") }}</option>
									<option v-for="g in groupOptions" :key="g.name" :value="g.name">{{ g.name }}</option>
								</select>
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
						</div>
					</div>
					<div class="modal-footer">
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
</template>
