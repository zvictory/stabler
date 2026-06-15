<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, formatDateTime, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { useFocusTrap } from "../../composables/useFocusTrap.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const { confirm } = useConfirm();
const toast = useToast();

const today = todayIso();
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
const modalEl = ref(null);
useFocusTrap(modalEl, createOpen);
const submitting = ref(false);
const submitError = ref("");
const editingName = ref("");

const payAccounts = ref([]);
const expAccounts = ref([]);
const assetAccounts = ref([]);
const equityAccounts = ref([]);
const optionsLoading = ref(false);

// QuickBooks-style save mode — persisted per user
const SAVE_MODE_KEY = "stabler.expenses.saveMode";
const savedMode = ref(localStorage.getItem(SAVE_MODE_KEY) || "close");
const SAVE_LABELS = { close: "Save & close", new: "Save & new", clear: "Save & clear" };
const saveModeLabel = computed(() => t(SAVE_LABELS[savedMode.value] || "Save & close"));

function persistSaveMode(mode) {
	savedMode.value = mode;
	localStorage.setItem(SAVE_MODE_KEY, mode);
}

const baseCurrency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD",
);

// Exchange rate context
const cbuRate = ref(null);
const fxBaseCur = ref("");
const fxCounterCur = ref("");
const rateDate = ref(null);
const rateError = ref("");

function isUZS(cur) {
	return (cur || "").toUpperCase() === "UZS";
}

function fmtAmt(v, cur) {
	const dp = isUZS(cur) ? 0 : 2;
	const s = (Number(v) || 0).toFixed(dp);
	const [i, d] = s.split(".");
	const gi = i.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
	return dp > 0 ? `${gi}.${d}` : gi;
}

function fmtRate(r) {
	const n = Number(r) || 0;
	const dp = n >= 100 ? 2 : 6;
	const s = n.toFixed(dp).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
	const [i, d] = s.split(".");
	return i.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + (d ? `.${d}` : "");
}

function norm(s) {
	return String(s ?? "").toLowerCase().normalize("NFKD").replace(/[\u0300-\u036f]/g, "");
}

let lineSeq = 0;
let ghostSeq = 0;

function newGhost() {
	return { id: `g${++ghostSeq}`, account: "", amount: null, memo: "" };
}

const ghost = ref(newGhost());
const form = ref(blankForm());

function blankForm() {
	lineSeq = 0;
	return {
		posting_date: today,
		entry_kind: "Expense",
		payee: "",
		payment_from: "",
		exchange_rate: null,
		lines: [],
	};
}

function materialGhost(item) {
	form.value.lines.push({
		id: ++lineSeq,
		account: item.name,
		amount: ghost.value.amount,
		memo: ghost.value.memo,
	});
	ghost.value = newGhost();
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

const lineAccounts = computed(() => {
	const base = form.value.entry_kind === "Asset Purchase" ? assetAccounts.value : expAccounts.value;
	return [...base, ...equityAccounts.value];
});

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

function lineBaseAmount(line) {
	if (!isCrossCurrency.value) return null;
	const rate = Number(form.value.exchange_rate) || 0;
	if (rate === 0) return null;
	return (Number(line.amount) || 0) / rate;
}

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
		cbuRate.value = null;
		fxBaseCur.value = "";
		fxCounterCur.value = "";
		rateDate.value = null;
		rateError.value = "";
		return;
	}
	rateError.value = "";
	try {
		const raw = await call("stabler.api.money.get_exchange_rate_for_currencies", {
			from_currency: baseCurrency.value,
			to_currency: payCurrency.value,
			posting_date: form.value.posting_date,
		});
		if (raw > 0) {
			// Canonical quote: always >= 1 so UZS↔USD reads "1 USD = 12 950 UZS"
			let base, counter, R;
			if (raw >= 1) {
				base = baseCurrency.value; counter = payCurrency.value; R = raw;
			} else {
				base = payCurrency.value; counter = baseCurrency.value; R = 1 / raw;
			}
			fxBaseCur.value = base;
			fxCounterCur.value = counter;
			cbuRate.value = R;
			rateDate.value = form.value.posting_date;
			form.value.exchange_rate = raw;
		} else {
			form.value.exchange_rate = null;
			cbuRate.value = null;
			rateDate.value = null;
			rateError.value = t("No exchange rate for this date — enter manually.");
		}
	} catch (err) {
		console.error("Failed to load exchange rate", err);
		rateError.value = t("No exchange rate for this date — enter manually.");
	}
}

watch(
	() => [form.value.payment_from, form.value.posting_date],
	async () => {
		await fetchExchangeRate();
	},
);

function searchLineAccount(q) {
	const n = norm(q);
	const baseLabel = form.value.entry_kind === "Asset Purchase" ? t("Assets") : t("Expenses");
	const baseList = form.value.entry_kind === "Asset Purchase" ? assetAccounts.value : expAccounts.value;

	function filter(list) {
		if (!n) return list;
		return list.filter(
			(a) =>
				norm(a.account_name || a.name).includes(n) ||
				norm(a.name).includes(n) ||
				(a.account_number && norm(a.account_number).includes(n)),
		);
	}

	const filteredBase = filter(baseList);
	const filteredEquity = filter(equityAccounts.value);
	const result = [];
	if (filteredBase.length) {
		result.push({ __group: baseLabel });
		result.push(...filteredBase);
	}
	if (filteredEquity.length) {
		result.push({ __group: t("Equity") });
		result.push(...filteredEquity);
	}
	return result;
}

function lineAccountDisplay(name) {
	const a = lineAccounts.value.find((x) => x.name === name);
	return a ? `${a.account_name || a.name} (${a.account_currency})` : name;
}

function lineCurrencyMismatch(line) {
	if (!line.account) return false;
	const picked = lineAccounts.value.find((a) => a.name === line.account);
	if (!picked) return false;
	return picked.account_currency && picked.account_currency !== payCurrency.value;
}

async function loadOptions() {
	if (!activeCompany.value) return;
	optionsLoading.value = true;
	try {
		const [pay, exp, fixed, equity] = await Promise.all([
			call("stabler.api.money.bank_cash_accounts", {
				company: activeCompany.value,
				include_equity: 1,
			}),
			call("stabler.api.money.expense_accounts", { company: activeCompany.value }),
			call("stabler.api.money.fixed_asset_accounts", { company: activeCompany.value }),
			call("stabler.api.money.equity_accounts", { company: activeCompany.value }),
		]);
		payAccounts.value = pay || [];
		expAccounts.value = exp || [];
		assetAccounts.value = fixed || [];
		equityAccounts.value = equity || [];
	} catch (err) {
		submitError.value = err?.message || "Failed to load accounts.";
	} finally {
		optionsLoading.value = false;
	}
}

async function openCreate() {
	form.value = blankForm();
	ghost.value = newGhost();
	editingName.value = "";
	submitError.value = "";
	cbuRate.value = null;
	rateError.value = "";
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
	ghost.value = newGhost();
	editingName.value = detail.value.name;
	submitError.value = "";
	cbuRate.value = null;
	rateError.value = "";
	createOpen.value = true;
	await fetchExchangeRate();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
	editingName.value = "";
}

function removeLine(idx) {
	form.value.lines.splice(idx, 1);
}

async function submitCreate(afterAction) {
	submitError.value = "";
	persistSaveMode(afterAction);

	if (afterAction === "clear") {
		const keepDate = form.value.posting_date;
		form.value = blankForm();
		form.value.posting_date = keepDate;
		ghost.value = newGhost();
		await fetchExchangeRate();
		return;
	}

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
		payload.exchange_rate = rate > 0 ? 1 / rate : 0;
	}

	submitting.value = true;
	try {
		const method = editingName.value
			? "stabler.api.money.amend_expense_entry"
			: "stabler.api.money.submit_expense_entry";
		const res = await call(
			method,
			editingName.value ? { source_name: editingName.value, ...payload } : payload,
		);

		load();

		if (editingName.value || afterAction === "close") {
			createOpen.value = false;
			editingName.value = "";
			if (res?.name) await openDetail(res.name);
		} else if (afterAction === "new") {
			const keepDate = form.value.posting_date;
			form.value = blankForm();
			form.value.posting_date = keepDate;
			ghost.value = newGhost();
			toast.success(t("Expense saved · {name}", { name: res?.name || "" }));
			await fetchExchangeRate();
		}
	} catch (err) {
		submitError.value = err?.message || t("Failed to submit expense.");
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
	const ok = await confirm({
		title: t("Cancel Expense Entry"),
		body: t("Cancel this entry?"),
		confirmLabel: t("Cancel Entry"),
		cancelLabel: t("Close"),
		danger: true,
	});
	if (!ok) return;
	submitError.value = "";
	try {
		await call("stabler.api.money.cancel_bank_entry", { name: detail.value.name });
		toast.success(t("Expense entry cancelled."));
		await openDetail(detail.value.name);
		await load();
	} catch (err) {
		detail.value.error = err?.message || t("Failed to cancel entry.");
	}
}

async function deleteEntry() {
	if (!detail.value?.name) return;
	const ok = await confirm({
		title: t("Delete Draft Entry"),
		body: t("Delete this draft entry?"),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	try {
		await call("stabler.api.money.delete_bank_entry", { name: detail.value.name });
		toast.success(t("Draft entry deleted."));
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
	equityAccounts.value = [];
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
			<div ref="modalEl" class="modal-content">
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
							<label class="form-label small mb-1 d-flex justify-content-between align-items-baseline">
								<span>{{ t("Pay from") }}</span>
								<span
									v-if="paymentFromAccount && paymentFromAccount.account_balance != null"
									class="text-secondary fw-normal font-monospace"
								>
									{{ fmtAmt(paymentFromAccount.account_balance, payCurrency) }} {{ payCurrency }}
								</span>
							</label>
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

					<!-- Exchange rate bar (cross-currency only) -->
					<div v-if="isCrossCurrency" class="mb-3">
						<div class="d-flex align-items-end gap-3 flex-wrap">
							<div style="min-width: 190px">
								<label class="form-label small mb-1">
									1 {{ baseCurrency }} = <span class="text-secondary">?</span> {{ payCurrency }}
								</label>
								<MoneyInput
									v-model="form.exchange_rate"
									:currency="payCurrency"
									:language="user.language"
									size="sm"
									:placeholder="`Rate in ${payCurrency}`"
								/>
								<div v-if="cbuRate" class="text-secondary small mt-1">
									CBU: 1 {{ fxBaseCur || payCurrency }} = {{ fmtRate(cbuRate) }} {{ fxCounterCur || baseCurrency }}<span v-if="rateDate"> · as of {{ formatDate(rateDate) }}</span>
								</div>
								<div v-if="rateError" class="text-danger small mt-1">
									<i class="ti ti-alert-triangle me-1"></i>{{ rateError }}
								</div>
							</div>
							<div class="text-secondary small pb-1 ms-auto">
								{{ t("Base equivalent") }}:
								<span class="fw-semibold font-monospace">
									{{ fmtAmt(baseEquivalent, baseCurrency) }} {{ baseCurrency }}
								</span>
							</div>
						</div>
					</div>

					<h6 class="text-uppercase text-secondary small mb-2">
						{{ form.entry_kind === "Asset Purchase" ? t("Asset lines") : t("Expense lines") }}
					</h6>
					<div class="table-responsive">
						<table class="table table-sm table-vcenter align-middle">
							<thead>
								<tr>
									<th style="min-width: 240px">{{ t("Account") }}</th>
									<th style="min-width: 160px" class="text-end">{{ t("Amount") }}</th>
									<th v-if="isCrossCurrency" class="text-end text-secondary" style="min-width: 120px; font-size: 0.8em">
										{{ baseCurrency }}
									</th>
									<th>{{ t("Memo") }}</th>
									<th class="w-1"></th>
								</tr>
							</thead>
							<SkeletonRows v-if="optionsLoading" :rows="3" :cols="isCrossCurrency ? 5 : 4" />
							<tbody v-else>
								<!-- Real lines -->
								<tr v-for="(line, idx) in form.lines" :key="line.id">
									<td>
										<Typeahead
											v-model="line.account"
											:search="searchLineAccount"
											:display="lineAccountDisplay(line.account)"
											:placeholder="t('Search account…')"
											size="sm"
											open-on-focus
											@pick="(item) => { if (!item.__group) line.account = item.name; }"
											@clear="() => (line.account = '')"
										>
											<template #option="{ item }">
												<template v-if="item.__group">
													<span class="text-uppercase text-secondary fw-semibold" style="font-size: 0.7em; letter-spacing: .04em">{{ item.__group }}</span>
												</template>
												<template v-else>
													<span>{{ item.account_name || item.name }}</span>
													<span v-if="item.account_number" class="text-secondary ms-1 small">{{ item.account_number }}</span>
													<span class="ms-auto text-secondary small font-monospace">{{ item.account_currency }}</span>
												</template>
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
									<td v-if="isCrossCurrency" class="text-end font-monospace text-secondary small">
										<template v-if="lineBaseAmount(line) != null">{{ fmtAmt(lineBaseAmount(line), baseCurrency) }}</template>
										<template v-else>—</template>
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
											tabindex="-1"
											@click="removeLine(idx)"
										>
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
								<!-- Ghost trailing row -->
								<tr :key="ghost.id" class="opacity-50">
									<td>
										<Typeahead
											:model-value="''"
											:search="searchLineAccount"
											:display="''"
											:placeholder="t('Add a line…')"
											size="sm"
											open-on-focus
											@pick="(item) => { if (!item.__group) materialGhost(item); }"
										>
											<template #option="{ item }">
												<template v-if="item.__group">
													<span class="text-uppercase text-secondary fw-semibold" style="font-size: 0.7em; letter-spacing: .04em">{{ item.__group }}</span>
												</template>
												<template v-else>
													<span>{{ item.account_name || item.name }}</span>
													<span v-if="item.account_number" class="text-secondary ms-1 small">{{ item.account_number }}</span>
													<span class="ms-auto text-secondary small font-monospace">{{ item.account_currency }}</span>
												</template>
											</template>
										</Typeahead>
									</td>
									<td>
										<MoneyInput
											v-model="ghost.amount"
											:currency="payCurrency"
											:language="user.language"
											size="sm"
										/>
									</td>
									<td v-if="isCrossCurrency"></td>
									<td>
										<input
											v-model="ghost.memo"
											type="text"
											class="form-control form-control-sm"
											:placeholder="t('Optional')"
										/>
									</td>
									<td></td>
								</tr>
							</tbody>
							<tfoot>
								<tr class="fw-bold">
									<td class="text-end">{{ t("Total") }}</td>
									<td class="text-end font-monospace">
										{{ formatMoney(totalAmount, payCurrency, user.language) }}
									</td>
									<td v-if="isCrossCurrency" class="text-end font-monospace text-secondary">
										{{ fmtAmt(baseEquivalent, baseCurrency) }} {{ baseCurrency }}
									</td>
									<td colspan="2"></td>
								</tr>
							</tfoot>
						</table>
					</div>
				</div>
				<div class="modal-footer">
					<button
						type="button"
						class="btn btn-outline-secondary"
						:disabled="submitting"
						@click="closeCreate"
					>
						{{ t("Cancel") }}
					</button>

					<!-- Amend mode: single Save & close button -->
					<button
						v-if="editingName"
						type="button"
						class="btn btn-primary ms-auto"
						:disabled="!canSubmit || submitting"
						@click="submitCreate('close')"
					>
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-check me-1"></i>
						{{ t("Save & close") }}
					</button>

					<!-- Create mode: QuickBooks-style split save group -->
					<div v-else class="btn-group ms-auto">
						<button
							type="button"
							class="btn btn-primary"
							:disabled="!canSubmit || submitting"
							@click="submitCreate(savedMode)"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-check me-1"></i>
							{{ saveModeLabel }}
						</button>
						<button
							type="button"
							class="btn btn-primary dropdown-toggle dropdown-toggle-split"
							data-bs-toggle="dropdown"
							:disabled="!canSubmit || submitting"
							aria-expanded="false"
						></button>
						<div class="dropdown-menu dropdown-menu-end stbl-menu stbl-menu--nocheck">
							<a href="#" class="dropdown-item stbl-menu-item" @click.prevent="submitCreate('close')">
								<i class="ti ti-x me-2"></i>{{ t("Save & close") }}
							</a>
							<a href="#" class="dropdown-item stbl-menu-item" @click.prevent="submitCreate('new')">
								<i class="ti ti-plus me-2"></i>{{ t("Save & new") }}
							</a>
							<a href="#" class="dropdown-item stbl-menu-item" @click.prevent="submitCreate('clear')">
								<i class="ti ti-eraser me-2"></i>{{ t("Save & clear") }}
							</a>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
