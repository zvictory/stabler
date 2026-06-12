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
import Typeahead from "../../components/Typeahead.vue";

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

// --- View drawer -----------------------------------------------------------
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

// --- Create modal ----------------------------------------------------------
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const editingName = ref("");

const payAccounts = ref([]); // bank/cash leaf accounts
const expAccounts = ref([]); // expense leaf accounts
const assetAccounts = ref([]); // fixed asset leaves for asset purchases
const optionsLoading = ref(false);

const baseCurrency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD",
);

let lineSeq = 0;
const newLine = () => ({ id: ++lineSeq, account: "", amount: null, memo: "" });

const form = ref(blankForm());

function blankForm() {
	lineSeq = 0;
	return {
		posting_date: today,
		entry_kind: "Expense",
		payee: "",
		payment_from: "",
		exchange_rate: null,
		lines: [newLine()],
	};
}

const entryKindOptions = [
	{ value: "Expense", label: t("Expense") },
	{ value: "Asset Purchase", label: t("Asset purchase") },
];

const paymentFromAccount = computed(() =>
	payAccounts.value.find((a) => a.name === form.value.payment_from) || null,
);

const payCurrency = computed(
	() => paymentFromAccount.value?.account_currency || baseCurrency.value,
);

const isCrossCurrency = computed(
	() => payCurrency.value && payCurrency.value !== baseCurrency.value,
);

const totalAmount = computed(() =>
	form.value.lines.reduce((sum, l) => sum + (Number(l.amount) || 0), 0),
);

const lineAccounts = computed(() =>
	form.value.entry_kind === "Asset Purchase" ? assetAccounts.value : expAccounts.value,
);

const formTitle = computed(() =>
	editingName.value
		? t("Amend expense")
		: form.value.entry_kind === "Asset Purchase"
			? t("New asset purchase")
			: t("New expense"),
);

const baseEquivalent = computed(() => {
	if (!isCrossCurrency.value) return totalAmount.value;
	const rate = Number(form.value.exchange_rate) || 0;
	if (rate === 0) return 0;
	return totalAmount.value / rate;
});

const canSubmit = computed(() => {
	if (!form.value.payment_from) return false;
	if (!form.value.posting_date) return false;
	if (isCrossCurrency.value && !(Number(form.value.exchange_rate) > 0)) return false;
	const validLines = form.value.lines.filter(
		(l) => l.account && Number(l.amount) > 0,
	);
	if (!validLines.length) return false;
	return true;
});

async function fetchExchangeRate() {
	if (!isCrossCurrency.value) {
		form.value.exchange_rate = null;
		return;
	}
	try {
		const rate = await call("stabler.api.money.get_exchange_rate_for_currencies", {
			from_currency: baseCurrency.value,
			to_currency: payCurrency.value,
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
	() => [form.value.payment_from, form.value.posting_date],
	async () => {
		await fetchExchangeRate();
	}
);

async function loadOptions() {
	if (!activeCompany.value) return;
	optionsLoading.value = true;
	try {
		const [pay, exp, fixed] = await Promise.all([
			call("stabler.api.money.bank_cash_accounts", { company: activeCompany.value }),
			call("stabler.api.money.expense_accounts", { company: activeCompany.value }),
			call("stabler.api.money.fixed_asset_accounts", { company: activeCompany.value }),
		]);
		payAccounts.value = pay || [];
		expAccounts.value = exp || [];
		assetAccounts.value = fixed || [];
	} catch (err) {
		submitError.value = err?.message || "Failed to load accounts.";
	} finally {
		optionsLoading.value = false;
	}
}

async function openCreate() {
	form.value = blankForm();
	editingName.value = "";
	submitError.value = "";
	createOpen.value = true;
	if (!payAccounts.value.length || !expAccounts.value.length || !assetAccounts.value.length) await loadOptions();
	await fetchExchangeRate();
}

async function openEditFromDetail() {
	if (!detail.value?.name) return;
	if (!payAccounts.value.length || !expAccounts.value.length || !assetAccounts.value.length) await loadOptions();
	const credit = (detail.value.accounts || []).find((row) => Number(row.credit_in_account_currency) > 0);
	const debits = (detail.value.accounts || []).filter((row) => Number(row.debit_in_account_currency) > 0);
	form.value = {
		posting_date: detail.value.posting_date || today,
		entry_kind: detail.value.entry_kind || "Expense",
		payee: detail.value.pay_to_recd_from || "",
		payment_from: credit?.account || "",
		exchange_rate: null,
		lines: debits.map((row) => ({
			id: ++lineSeq,
			account: row.account,
			amount: Number(row.debit_in_account_currency) || null,
			memo: row.user_remark || "",
		})),
	};
	if (!form.value.lines.length) form.value.lines = [newLine()];
	editingName.value = detail.value.name;
	submitError.value = "";
	createOpen.value = true;
	await fetchExchangeRate();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
	editingName.value = "";
}

function addLine() {
	form.value.lines.push(newLine());
}

function removeLine(idx) {
	if (form.value.lines.length <= 1) return;
	form.value.lines.splice(idx, 1);
}

function searchLineAccount(q) {
	const lower = (q || "").toLowerCase();
	if (!lower) return lineAccounts.value.slice(0, 60);
	return lineAccounts.value.filter(
		(a) =>
			(a.account_name || a.name).toLowerCase().includes(lower) ||
			a.name.toLowerCase().includes(lower),
	);
}

function lineAccountDisplay(name) {
	const a = lineAccounts.value.find((x) => x.name === name);
	return a ? `${a.account_name || a.name} (${a.account_currency})` : name;
}

// Expense lines must share currency with the payment-from leg (backend rule).
// If the user picks an expense account in a different currency, surface a hint.
function lineCurrencyMismatch(line) {
	if (!line.account) return false;
	const picked = lineAccounts.value.find((a) => a.name === line.account);
	if (!picked) return false;
	return picked.account_currency && picked.account_currency !== payCurrency.value;
}

async function submitCreate() {
	submitError.value = "";
	if (!canSubmit.value) {
		submitError.value = t("Fill in the required fields before submitting.");
		return;
	}
	const lines = form.value.lines
		.filter((l) => l.account && Number(l.amount) > 0)
		.map((l) => ({
			account: l.account,
			amount: Number(l.amount),
			memo: l.memo?.trim() || undefined,
		}));
	const payload = {
		company: activeCompany.value,
		posting_date: form.value.posting_date,
		payment_from: form.value.payment_from,
		lines,
		submit: 1,
		entry_kind: form.value.entry_kind,
	};
	if (form.value.payee?.trim()) payload.payee = form.value.payee.trim();
	if (isCrossCurrency.value) {
		const rate = Number(form.value.exchange_rate);
		payload.exchange_rate = rate > 0 ? (1 / rate) : 0;
	}

	submitting.value = true;
	try {
		const method = editingName.value
			? "stabler.api.money.amend_expense_entry"
			: "stabler.api.money.submit_expense_entry";
		const res = await call(method, editingName.value ? { source_name: editingName.value, ...payload } : payload);
		createOpen.value = false;
		editingName.value = "";
		await load();
		if (res?.name) await openDetail(res.name);
	} catch (err) {
		submitError.value = err?.message || "Failed to submit expense.";
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
			entry_type: "Expense",
		});
	} catch (err) {
		error.value = err?.message || "Failed to load expenses.";
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

async function cancelEntry() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Cancel this entry?"))) return;
	submitError.value = "";
	try {
		await call("stabler.api.money.cancel_bank_entry", { name: detail.value.name });
		await openDetail(detail.value.name);
		await load();
	} catch (err) {
		detail.value.error = err?.message || t("Failed to cancel entry.");
	}
}

async function deleteEntry() {
	if (!detail.value?.name) return;
	if (!window.confirm(t("Delete this draft entry?"))) return;
	try {
		await call("stabler.api.money.delete_bank_entry", { name: detail.value.name });
		closeDetail();
		await load();
	} catch (err) {
		detail.value.error = err?.message || t("Failed to delete entry.");
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
	payAccounts.value = [];
	expAccounts.value = [];
	assetAccounts.value = [];
	load();
	loadOptions();
});
</script>

<template>
	<div class="card">
		<div class="card-header">
			<div class="card-title">{{ t("Expenses") }}</div>
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
					<i class="ti ti-receipt-2 me-1"></i>{{ t("New expense") }}
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
			icon="ti-receipt-2"
			accentIcon="ti-plus"
			tone="info"
			title="No expenses in this range"
			subtitle="Record an outgoing payment to start tracking spend."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" :disabled="!activeCompany" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New expense") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>#</th>
						<th>{{ t("Date") }}</th>
						<th>{{ t("Kind") }}</th>
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
						<td>
							<span class="badge bg-blue-lt">{{ r.entry_kind || t("Expense") }}</span>
						</td>
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

	<!-- View drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div
		v-if="detailOpen"
		class="offcanvas offcanvas-end show"
		tabindex="-1"
		style="visibility: visible; width: 620px"
	>
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<i class="ti ti-receipt-2 me-1"></i>{{ t("Expense") }}
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
					<div class="datagrid-item">
						<div class="datagrid-title">{{ t("Kind") }}</div>
						<div class="datagrid-content">{{ detail.entry_kind || t("Expense") }}</div>
					</div>
					<div v-if="detail.pay_to_recd_from" class="datagrid-item">
						<div class="datagrid-title">{{ t("Payee") }}</div>
						<div class="datagrid-content">{{ detail.pay_to_recd_from }}</div>
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
				<div class="d-flex gap-2 justify-content-end mt-3">
					<button v-if="detail.docstatus < 2" type="button" class="btn btn-outline-primary" @click="openEditFromDetail">
						<i class="ti ti-pencil me-1"></i>{{ detail.docstatus === 1 ? t("Amend") : t("Edit draft") }}
					</button>
					<button v-if="detail.docstatus === 0" type="button" class="btn btn-outline-danger" @click="deleteEntry">
						<i class="ti ti-trash me-1"></i>{{ t("Delete draft") }}
					</button>
					<button v-if="detail.docstatus === 1" type="button" class="btn btn-outline-danger" @click="cancelEntry">
						<i class="ti ti-ban me-1"></i>{{ t("Cancel") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" aria-modal="true">
		<div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						<i class="ti ti-receipt-2 me-1"></i>{{ formTitle }}
					</h5>
					<button type="button" class="btn-close" @click="closeCreate" aria-label="Close"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-2 mb-3">
						<div class="col-md-4">
							<label class="form-label small">{{ t("Mode") }}</label>
							<Select
								v-model="form.entry_kind"
								:options="entryKindOptions"
								value-key="value"
								label-key="label"
							/>
						</div>
						<div class="col-md-4">
							<label class="form-label small">{{ t("Posting date") }}</label>
							<DateInput v-model="form.posting_date" required />
						</div>
						<div class="col-md-4">
							<label class="form-label small">{{ t("Pay from") }}</label>
							<Select
								v-model="form.payment_from"
								:disabled="optionsLoading"
								:options="payAccounts"
								value-key="name"
								:placeholder="t('Select an account…')"
							>
								<template #option="{ option }">
									{{ option.account_name || option.name }} ({{ option.account_currency }})
								</template>
								<template #selected="{ option }">
									{{ option.account_name || option.name }} ({{ option.account_currency }})
								</template>
							</Select>
						</div>
						<div class="col-md-12">
							<label class="form-label small">{{ t("Payee") }}</label>
							<input
								v-model="form.payee"
								type="text"
								class="form-control"
								:placeholder="t('Optional')"
							/>
						</div>
					</div>

					<div v-if="isCrossCurrency" class="alert alert-info py-2 px-3 mb-3 small">
						<div class="d-flex align-items-end gap-3 flex-wrap">
							<div>
								<i class="ti ti-info-circle me-1"></i>
								<strong>1 {{ baseCurrency }} =</strong>
							</div>
							<div style="width: 160px">
								<MoneyInput
									v-model="form.exchange_rate"
									:currency="payCurrency"
									:language="user.language"
									size="sm"
									:placeholder="`Rate to ${payCurrency}`"
								/>
							</div>
							<div class="ms-auto text-secondary">
								{{ t("Base equivalent") }}:
								<span class="fw-semibold font-monospace">
									{{ formatMoney(baseEquivalent, baseCurrency, user.language) }}
								</span>
							</div>
						</div>
					</div>

					<div class="d-flex align-items-center mb-2">
						<h6 class="text-uppercase text-secondary small m-0">
							{{ form.entry_kind === "Asset Purchase" ? t("Asset lines") : t("Expense lines") }}
						</h6>
						<button type="button" class="btn btn-sm btn-outline-secondary ms-auto" @click="addLine">
							<i class="ti ti-plus me-1"></i>{{ t("Add line") }}
						</button>
					</div>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter align-middle">
							<thead>
								<tr>
									<th style="min-width: 240px">{{ t("Account") }}</th>
									<th style="min-width: 160px" class="text-end">{{ t("Amount") }}</th>
									<th>{{ t("Memo") }}</th>
									<th class="w-1"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(line, idx) in form.lines" :key="line.id">
									<td>
										<Typeahead
											v-model="line.account"
											:search="searchLineAccount"
											:display="lineAccountDisplay(line.account)"
											:placeholder="t('Search account…')"
											size="sm"
											open-on-focus
											@pick="(item) => (line.account = item.name)"
											@clear="() => (line.account = '')"
										>
											<template #option="{ item }">
												{{ item.account_name || item.name }} ({{ item.account_currency }})
											</template>
										</Typeahead>
										<div v-if="lineCurrencyMismatch(line)" class="text-danger small mt-1">
											<i class="ti ti-alert-triangle me-1"></i>
											{{ t("Account currency must match the payment account.") }}
										</div>
									</td>
									<td>
										<MoneyInput
											v-model="line.amount"
											:currency="payCurrency"
											:language="user.language"
											size="sm"
										/>
									</td>
									<td>
										<input
											v-model="line.memo"
											type="text"
											class="form-control form-control-sm"
											:placeholder="t('Optional')"
										/>
									</td>
									<td>
										<button
											type="button"
											class="btn btn-sm btn-ghost-danger"
											:disabled="form.lines.length <= 1"
											@click="removeLine(idx)"
										>
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
							<tfoot>
								<tr class="fw-bold">
									<td class="text-end">{{ t("Total") }}</td>
									<td class="text-end font-monospace">
										{{ formatMoney(totalAmount, payCurrency, user.language) }}
									</td>
									<td colspan="2"></td>
								</tr>
							</tfoot>
						</table>
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
						{{ t("Submit expense") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
