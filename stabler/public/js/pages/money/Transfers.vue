<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const today = new Date().toISOString().slice(0, 10);
const monthAgo = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);

const fromDate = ref(monthAgo);
const toDate = ref(today);
const limit = ref(50);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

const baseCurrency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD",
);

// --- Create modal ----------------------------------------------------------
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

const accounts = ref([]); // Bank + Cash leaves
const optionsLoading = ref(false);

const form = ref(blankForm());

function blankForm() {
	return {
		posting_date: today,
		from_account: "",
		to_account: "",
		from_amount: null,
		to_amount: null,
		exchange_rate: null,
		memo: "",
	};
}

const fromAcc = computed(() => accounts.value.find((a) => a.name === form.value.from_account) || null);
const toAcc = computed(() => accounts.value.find((a) => a.name === form.value.to_account) || null);

// Disable the account already chosen on the opposite leg (same rule the native
// per-<option> :disabled enforced) — Select reads `disabled` off each option.
const fromAccountOptions = computed(() =>
	accounts.value.map((a) => ({ ...a, disabled: a.name === form.value.to_account })),
);
const toAccountOptions = computed(() =>
	accounts.value.map((a) => ({ ...a, disabled: a.name === form.value.from_account })),
);

const fromCurrency = computed(() => fromAcc.value?.account_currency || baseCurrency.value);
const toCurrency = computed(() => toAcc.value?.account_currency || baseCurrency.value);

const isCrossCurrency = computed(
	() => fromAcc.value && toAcc.value && fromCurrency.value !== toCurrency.value,
);

const rateFromCurrency = computed(() => {
	if (fromCurrency.value === "UZS" && toCurrency.value === "USD") return "USD";
	return fromCurrency.value;
});
const rateToCurrency = computed(() => {
	if (fromCurrency.value === "UZS" && toCurrency.value === "USD") return "UZS";
	return toCurrency.value;
});

// Auto-derive to_amount when cross-currency and the user has typed a rate.
watch(
	() => [form.value.from_amount, form.value.exchange_rate, isCrossCurrency.value, fromCurrency.value, toCurrency.value],
	() => {
		if (!isCrossCurrency.value) {
			form.value.to_amount = form.value.from_amount;
			return;
		}
		const amt = Number(form.value.from_amount) || 0;
		const rate = Number(form.value.exchange_rate) || 0;
		if (amt > 0 && rate > 0) {
			if (fromCurrency.value === "UZS" && toCurrency.value === "USD") {
				form.value.to_amount = Number((amt / rate).toFixed(2));
			} else {
				form.value.to_amount = Number((amt * rate).toFixed(2));
			}
		}
	},
);

const canSubmit = computed(() => {
	if (!form.value.posting_date) return false;
	if (!form.value.from_account || !form.value.to_account) return false;
	if (form.value.from_account === form.value.to_account) return false;
	if (!(Number(form.value.from_amount) > 0)) return false;
	if (isCrossCurrency.value) {
		if (!(Number(form.value.exchange_rate) > 0) && !(Number(form.value.to_amount) > 0)) return false;
	}
	return true;
});

async function fetchExchangeRate() {
	if (!isCrossCurrency.value) {
		form.value.exchange_rate = null;
		return;
	}
	try {
		let fromCur = fromCurrency.value;
		let toCur = toCurrency.value;
		let fromApi = "USD";
		let toApi = "UZS";
		if (fromCur === "USD" && toCur === "UZS") {
			fromApi = "USD";
			toApi = "UZS";
		} else if (fromCur === "UZS" && toCur === "USD") {
			fromApi = "USD";
			toApi = "UZS";
		} else {
			fromApi = fromCur;
			toApi = toCur;
		}
		const rate = await call("stabler.api.money.get_exchange_rate_for_currencies", {
			from_currency: fromApi,
			to_currency: toApi,
			posting_date: form.value.posting_date,
		});
		if (rate > 0) {
			form.value.exchange_rate = rate;
		} else {
			form.value.exchange_rate = null;
		}
	} catch (err) {
		console.error("Failed to load exchange rate", err);
	}
}

watch(
	() => [form.value.from_account, form.value.to_account, form.value.posting_date],
	async () => {
		await fetchExchangeRate();
	}
);

async function loadOptions() {
	if (!activeCompany.value) return;
	optionsLoading.value = true;
	try {
		accounts.value =
			(await call("stabler.api.money.bank_cash_accounts", {
				company: activeCompany.value,
			})) || [];
	} catch (err) {
		submitError.value = err?.message || "Failed to load accounts.";
	} finally {
		optionsLoading.value = false;
	}
}

async function openCreate() {
	form.value = blankForm();
	submitError.value = "";
	createOpen.value = true;
	if (!accounts.value.length) await loadOptions();
	await fetchExchangeRate();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

function swap() {
	const a = form.value.from_account;
	const b = form.value.to_account;
	form.value.from_account = b;
	form.value.to_account = a;
	// Reset amounts since currencies/rates flip — safer than trying to invert the rate.
	form.value.from_amount = null;
	form.value.to_amount = null;
	form.value.exchange_rate = null;
}

async function submitCreate() {
	submitError.value = "";
	if (!canSubmit.value) {
		submitError.value = t("Fill in the required fields before submitting.");
		return;
	}
	const payload = {
		company: activeCompany.value,
		posting_date: form.value.posting_date,
		from_account: form.value.from_account,
		to_account: form.value.to_account,
		from_amount: Number(form.value.from_amount),
		submit: 1,
	};
	if (form.value.memo?.trim()) payload.memo = form.value.memo.trim();
	if (isCrossCurrency.value) {
		if (Number(form.value.to_amount) > 0) payload.to_amount = Number(form.value.to_amount);
		
		const rate = Number(form.value.exchange_rate);
		if (rate > 0) {
			if (fromCurrency.value === "UZS" && toCurrency.value === "USD") {
				payload.exchange_rate = 1 / rate;
			} else {
				payload.exchange_rate = rate;
			}
		}
	}

	submitting.value = true;
	try {
		await call("stabler.api.money.submit_transfer_entry", payload);
		createOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || "Failed to submit transfer.";
	} finally {
		submitting.value = false;
	}
}

// --- List + detail ---------------------------------------------------------

const statusBadge = (d) => {
	if (d === 0) return { cls: "bg-yellow-lt", label: "Draft" };
	if (d === 1) return { cls: "bg-green-lt", label: "Submitted" };
	if (d === 2) return { cls: "bg-red-lt", label: "Cancelled" };
	return { cls: "bg-secondary-lt", label: String(d) };
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_bank_entries", {
			company: activeCompany.value,
			from_date: fromDate.value,
			to_date: toDate.value,
			limit: limit.value,
			voucher_type: "Bank Entry",
			entry_type: "Transfer",
		});
	} catch (err) {
		error.value = err?.message || "Failed to load transfers.";
	} finally {
		loading.value = false;
	}
}

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.money.journal_entry_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || "Failed to load." };
	} finally {
		detailLoading.value = false;
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

onMounted(() => {
	load();
	loadOptions();
});
watch(activeCompany, () => {
	accounts.value = [];
	load();
	loadOptions();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Transfers") }}</div>
			<div class="ms-auto d-flex gap-2 align-items-end">
				<div>
					<label class="form-label small mb-1">{{ t("From") }}</label>
					<DateInput v-model="fromDate" size="sm" />
				</div>
				<div>
					<label class="form-label small mb-1">{{ t("To") }}</label>
					<DateInput v-model="toDate" size="sm" />
				</div>
				<button type="button" class="btn btn-sm btn-outline-primary" @click="load">
					<i class="ti ti-refresh me-1"></i>{{ t("Apply") }}
				</button>
				<button
					type="button"
					class="btn btn-sm btn-primary"
					:disabled="!activeCompany"
					@click="openCreate"
				>
					<i class="ti ti-transfer me-1"></i>{{ t("New transfer") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary" role="status"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-transfer"
			accentIcon="ti-plus"
			tone="info"
			title="No transfers in this range"
			subtitle="Move money between your bank or cash accounts."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" :disabled="!activeCompany" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New transfer") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Memo") }}</th>
						<th class="text-end">{{ t("Amount") }}</th>
						<th class="w-1">{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openDetail(r.name)"
					>
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td class="text-truncate" style="max-width: 380px">{{ r.user_remark || "—" }}</td>
						<td class="text-end font-monospace">
							{{ formatMoney(r.total_amount ?? r.total_debit_base, r.currency || r.base_currency || baseCurrency, user.language) }}
						</td>
						<td>
							<span class="badge" :class="statusBadge(r.docstatus).cls">
								{{ statusBadge(r.docstatus).label }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- View drawer (re-uses JE detail) -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 620px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-transfer me-1"></i>{{ t("Transfer") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<div v-else-if="detail">
				<div class="datagrid mb-3">
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Name") }}</div>
						<div class="datagrid-content font-monospace">{{ detail.name }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Posting date") }}</div>
						<div class="datagrid-content">{{ formatDateTime(detail.posting_date) }}</div>
					</div>
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Status") }}</div>
						<div class="datagrid-content">
							<span class="badge" :class="statusBadge(detail.docstatus).cls">
								{{ statusBadge(detail.docstatus).label }}
							</span>
						</div>
					</div>
					<div v-if="detail.user_remark" class="datagrid-item">
						<div class="datagrid-title">{{ t("Memo") }}</div>
						<div class="datagrid-content">{{ detail.user_remark }}</div>
					</div>
				</div>

				<h6 class="text-uppercase text-secondary small mb-2">{{ t("Postings") }}</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Account") }}</th>
								<th class="text-end">{{ t("Debit") }}</th>
								<th class="text-end">{{ t("Credit") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(a, i) in detail.accounts" :key="i">
								<td>{{ a.account }}</td>
								<td class="text-end font-monospace">
									{{ a.debit_in_account_currency ? formatMoney(a.debit_in_account_currency, a.account_currency || baseCurrency, user.language) : "—" }}
								</td>
								<td class="text-end font-monospace">
									{{ a.credit_in_account_currency ? formatMoney(a.credit_in_account_currency, a.account_currency || baseCurrency, user.language) : "—" }}
								</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" aria-modal="true">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						<i class="ti ti-transfer me-1"></i>{{ t("New transfer") }}
					</h5>
					<button type="button" class="btn-close" @click="closeCreate" aria-label="Close"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-2 mb-3">
						<div class="col-md-4">
							<label class="form-label small">{{ t("Posting date") }}</label>
							<DateInput v-model="form.posting_date" required />
						</div>
						<div class="col-md-8">
							<label class="form-label small">{{ t("Memo") }}</label>
							<input
								v-model="form.memo"
								type="text"
								class="form-control"
								:placeholder="t('Optional')"
							/>
						</div>
					</div>

					<div class="row g-2 align-items-end">
						<div class="col-md-5">
							<label class="form-label small">{{ t("From account") }}</label>
							<Select
								v-model="form.from_account"
								:disabled="optionsLoading"
								:options="fromAccountOptions"
								value-key="name"
								:placeholder="t('Select…')"
							>
								<template #option="{ option }">
									{{ option.account_name || option.name }} ({{ option.account_currency }})
								</template>
								<template #selected="{ option }">
									{{ option.account_name || option.name }} ({{ option.account_currency }})
								</template>
							</Select>
						</div>
						<div class="col-md-2 text-center">
							<button
								type="button"
								class="btn btn-outline-secondary"
								:disabled="!form.from_account && !form.to_account"
								@click="swap"
								:aria-label="t('Swap accounts')"
							>
								<i class="ti ti-arrows-exchange"></i>
							</button>
						</div>
						<div class="col-md-5">
							<label class="form-label small">{{ t("To account") }}</label>
							<Select
								v-model="form.to_account"
								:disabled="optionsLoading"
								:options="toAccountOptions"
								value-key="name"
								:placeholder="t('Select…')"
							>
								<template #option="{ option }">
									{{ option.account_name || option.name }} ({{ option.account_currency }})
								</template>
								<template #selected="{ option }">
									{{ option.account_name || option.name }} ({{ option.account_currency }})
								</template>
							</Select>
						</div>
					</div>

					<div class="row g-2 mt-3">
						<div class="col-md-6">
							<label class="form-label small">
								{{ t("Amount sent") }}
								<span v-if="fromAcc" class="text-secondary">({{ fromCurrency }})</span>
							</label>
							<MoneyInput
								v-model="form.from_amount"
								:currency="fromCurrency"
								:language="user.language"
							/>
						</div>
						<div v-if="isCrossCurrency" class="col-md-6">
							<label class="form-label small">
								{{ t("Amount received") }}
								<span class="text-secondary">({{ toCurrency }})</span>
							</label>
							<MoneyInput
								v-model="form.to_amount"
								:currency="toCurrency"
								:language="user.language"
							/>
						</div>
					</div>

					<div v-if="isCrossCurrency" class="row g-2 mt-3">
						<div class="col-md-6">
							<label class="form-label small">
								{{ t("Exchange rate") }} — 1 {{ rateFromCurrency }} = ? {{ rateToCurrency }}
							</label>
							<MoneyInput
								v-model="form.exchange_rate"
								:currency="rateToCurrency"
								:language="user.language"
							/>
							<div class="form-hint small">
								{{ t("Editing the rate updates the received amount.") }}
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeCreate" :disabled="submitting">
						{{ t("Cancel") }}
					</button>
					<button
						type="button"
						class="btn btn-primary"
						:disabled="!canSubmit || submitting"
						@click="submitCreate"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>
						{{ t("Submit transfer") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
