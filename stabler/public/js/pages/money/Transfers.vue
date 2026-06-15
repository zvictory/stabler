<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDateTime, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
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
const modalEl = ref(null);
useFocusTrap(modalEl, createOpen);
const submitting = ref(false);
const submitError = ref("");
const editingName = ref("");

const accounts = ref([]);
const optionsLoading = ref(false);

const form = ref(blankForm());

// QuickBooks-style save mode — persisted per user
const SAVE_MODE_KEY = "stabler.transfers.saveMode";
const savedMode = ref(localStorage.getItem(SAVE_MODE_KEY) || "close");
const SAVE_LABELS = { close: "Record & close", new: "Record & new", clear: "Record & clear" };
const saveModeLabel = computed(() => t(SAVE_LABELS[savedMode.value] || "Record & close"));

function persistSaveMode(mode) {
	savedMode.value = mode;
	localStorage.setItem(SAVE_MODE_KEY, mode);
}

const formTitle = computed(() => (editingName.value ? t("Amend transfer") : t("New transfer")));

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

// label field required by Select's keyboard type-ahead (optionLabel reads o["label"])
const fromAccountOptions = computed(() =>
	accounts.value.map((a) => ({
		...a,
		label: `${a.account_name || a.name} (${a.account_currency})`,
		disabled: a.name === form.value.to_account,
	})),
);
const toAccountOptions = computed(() =>
	accounts.value.map((a) => ({
		...a,
		label: `${a.account_name || a.name} (${a.account_currency})`,
		disabled: a.name === form.value.from_account,
	})),
);

const fromCurrency = computed(() => fromAcc.value?.account_currency || baseCurrency.value);
const toCurrency = computed(() => toAcc.value?.account_currency || baseCurrency.value);

const isCrossCurrency = computed(
	() => fromAcc.value && toAcc.value && fromCurrency.value !== toCurrency.value,
);

// CBU rate for display hint (canonical: 1 fxBaseCur = cbuRate fxCounterCur, >= 1)
const cbuRate = ref(null);
// Canonical quote direction. We ALWAYS quote the rate as "1 strong = N weak"
// (rate >= 1) so UZS↔USD always reads "1 USD = 12 950 UZS", never "0.000077".
const fxBaseCur = ref("");
const fxCounterCur = ref("");
const fromIsBase = computed(() => fromCurrency.value === fxBaseCur.value);

// --- Three-way reciprocal binding -----------------------------------------
// Relationship: from_amount × exchange_rate = to_amount
// "Last two wins" — the field not in the top-2 recently-touched is derived.
let recent = ["rate", "amt"]; // seed: derived = recv

function computedField() {
	const top = recent.slice(0, 2);
	return ["amt", "rate", "recv"].find((f) => !top.includes(f));
}

function touch(id) {
	recent = [id, ...recent.filter((x) => x !== id)];
}

function reseed() {
	recent = ["rate", "amt"]; // recv is derived
}

function roundMoney(n, currency) {
	return (currency || "").toUpperCase() === "UZS" ? Math.round(n) : Math.round(n * 100) / 100;
}

function roundRate(rate) {
	// Large rates (e.g. UZS amounts): 2 dp. Small rates (e.g. cross-minor): 6 dp.
	return rate > 100 ? Math.round(rate * 100) / 100 : Math.round(rate * 1000000) / 1000000;
}

function isUZS(cur) {
	return (cur || "").toUpperCase() === "UZS";
}

// Space-grouped amount with dot decimals — "1 200.00", "15 300 000".
function fmtAmt(v, cur) {
	const dp = isUZS(cur) ? 0 : 2;
	const s = (Number(v) || 0).toFixed(dp);
	const [i, d] = s.split(".");
	const gi = i.replace(/\B(?=(\d{3})+(?!\d))/g, " ");
	return dp > 0 ? `${gi}.${d}` : gi;
}

// Space-grouped rate — "12 750" for big quotes, up to 6 dp for sub-1.
function fmtRate(r) {
	const n = Number(r) || 0;
	const dp = n >= 100 ? 2 : 6;
	const s = n.toFixed(dp).replace(/(\.\d*?)0+$/, "$1").replace(/\.$/, "");
	const [i, d] = s.split(".");
	return i.replace(/\B(?=(\d{3})+(?!\d))/g, " ") + (d ? `.${d}` : "");
}

let _deriving = false;

function derive() {
	if (!isCrossCurrency.value) {
		form.value.to_amount = form.value.from_amount;
		return;
	}
	const field = computedField();
	const amt = Number(form.value.from_amount) || 0;
	const R = Number(form.value.exchange_rate) || 0; // canonical: 1 base = R counter
	const recv = Number(form.value.to_amount) || 0;
	const fIsBase = fromIsBase.value; // from-leg is the strong/base currency?

	_deriving = true;
	try {
		if (field === "recv") {
			if (amt > 0 && R > 0)
				form.value.to_amount = roundMoney(fIsBase ? amt * R : amt / R, toCurrency.value);
		} else if (field === "amt") {
			if (recv > 0 && R > 0)
				form.value.from_amount = roundMoney(fIsBase ? recv / R : recv * R, fromCurrency.value);
		} else if (field === "rate") {
			if (amt > 0 && recv > 0)
				form.value.exchange_rate = roundRate(fIsBase ? recv / amt : amt / recv);
		}
	} finally {
		_deriving = false;
	}
}

function onAmtInput(val) {
	if (_deriving) return;
	form.value.from_amount = val;
	touch("amt");
	derive();
}

function onRateInput(val) {
	if (_deriving) return;
	form.value.exchange_rate = val;
	rateManuallyEdited.value = true;
	touch("rate");
	derive();
}

function onRecvInput(val) {
	if (_deriving) return;
	form.value.to_amount = val;
	touch("recv");
	derive();
}

// Track whether the user manually typed a rate (so date changes don't clobber it)
const rateManuallyEdited = ref(false);

async function fetchExchangeRate() {
	if (!isCrossCurrency.value) {
		form.value.exchange_rate = null;
		cbuRate.value = null;
		fxBaseCur.value = "";
		fxCounterCur.value = "";
		return;
	}
	try {
		const raw = await call("stabler.api.money.get_exchange_rate_for_currencies", {
			from_currency: fromCurrency.value,
			to_currency: toCurrency.value,
			posting_date: form.value.posting_date,
		});
		// raw = "to per from". Flip to the canonical >= 1 quote so we never show
		// a sub-1 rate like 1 UZS = 0.000077 USD — always 1 USD = 12 950 UZS.
		let base, counter, R;
		if (raw >= 1) {
			base = fromCurrency.value; counter = toCurrency.value; R = raw;
		} else if (raw > 0) {
			base = toCurrency.value; counter = fromCurrency.value; R = 1 / raw;
		} else {
			return;
		}
		fxBaseCur.value = base;
		fxCounterCur.value = counter;
		cbuRate.value = roundRate(R);
		if (!rateManuallyEdited.value) {
			_deriving = true;
			form.value.exchange_rate = roundRate(R);
			_deriving = false;
		}
	} catch (err) {
		console.error("Failed to load exchange rate", err);
	}
}

// Account changes: reseed + re-fetch CBU (currencies may have changed)
watch(
	() => [form.value.from_account, form.value.to_account],
	async () => {
		reseed();
		rateManuallyEdited.value = false;
		await fetchExchangeRate();
		derive();
	},
);

// Date changes: always re-fetch and show THAT date's CBU rate (the rate is a
// function of the posting date, so a date change re-anchors it).
watch(
	() => form.value.posting_date,
	async () => {
		rateManuallyEdited.value = false;
		await fetchExchangeRate();
		derive();
	},
);

const canSubmit = computed(() => {
	if (!form.value.posting_date) return false;
	if (!form.value.from_account || !form.value.to_account) return false;
	if (form.value.from_account === form.value.to_account) return false;
	if (!(Number(form.value.from_amount) > 0)) return false;
	if (isCrossCurrency.value) {
		if (!(Number(form.value.to_amount) > 0) && !(Number(form.value.exchange_rate) > 0)) return false;
	}
	return true;
});

async function loadOptions() {
	if (!activeCompany.value) return;
	optionsLoading.value = true;
	try {
		accounts.value =
			(await call("stabler.api.money.bank_cash_accounts", {
				company: activeCompany.value,
				include_equity: 1,
			})) || [];
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
	rateManuallyEdited.value = false;
	reseed();
	createOpen.value = true;
	if (!accounts.value.length) await loadOptions();
	await fetchExchangeRate();
	derive();
}

async function openEditFromDetail() {
	if (!detail.value?.name) return;
	if (!accounts.value.length) await loadOptions();
	const credit = (detail.value.accounts || []).find((row) => Number(row.credit_in_account_currency) > 0);
	const debit = (detail.value.accounts || []).find((row) => Number(row.debit_in_account_currency) > 0);
	form.value = {
		posting_date: detail.value.posting_date || today,
		from_account: credit?.account || "",
		to_account: debit?.account || "",
		from_amount: Number(credit?.credit_in_account_currency) || null,
		to_amount: Number(debit?.debit_in_account_currency) || null,
		exchange_rate: null,
		memo: detail.value.user_remark || "",
	};
	editingName.value = detail.value.name;
	submitError.value = "";
	rateManuallyEdited.value = false;
	reseed();
	createOpen.value = true;
	await fetchExchangeRate();
	derive();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
	editingName.value = "";
}

function swap() {
	const a = form.value.from_account;
	const b = form.value.to_account;
	form.value.from_account = b;
	form.value.to_account = a;
	form.value.from_amount = null;
	form.value.to_amount = null;
	form.value.exchange_rate = null;
	rateManuallyEdited.value = false;
	reseed();
}

let focusFromAccountFn = null;

async function submitCreate(mode) {
	submitError.value = "";
	persistSaveMode(mode);

	// Record & clear: just reset the form, no network call
	if (mode === "clear") {
		const keepDate = form.value.posting_date;
		form.value = blankForm();
		form.value.posting_date = keepDate;
		rateManuallyEdited.value = false;
		reseed();
		await fetchExchangeRate();
		derive();
		return;
	}

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
		// to_amount is authoritative; send a from→to directional rate (what the
		// backend expects: to_amt = from_amt × exchange_rate) derived from the
		// two amounts, so it never depends on the canonical display direction.
		payload.to_amount = Number(form.value.to_amount);
		const amt = Number(form.value.from_amount) || 0;
		if (amt > 0 && Number(form.value.to_amount) > 0)
			payload.exchange_rate = Number(form.value.to_amount) / amt;
	}

	submitting.value = true;
	try {
		const method = editingName.value
			? "stabler.api.money.amend_transfer_entry"
			: "stabler.api.money.submit_transfer_entry";
		const res = await call(method, editingName.value ? { source_name: editingName.value, ...payload } : payload);

		load(); // refresh list in background

		if (editingName.value || mode === "close") {
			createOpen.value = false;
			editingName.value = "";
			if (res?.name) await openDetail(res.name);
		} else if (mode === "new") {
			const keepDate = form.value.posting_date;
			form.value = blankForm();
			form.value.posting_date = keepDate;
			rateManuallyEdited.value = false;
			reseed();
			toast.success(t("Transfer recorded · {name}", { name: res?.name || "" }));
			await fetchExchangeRate();
			derive();
			focusFromAccountFn?.();
		}
	} catch (err) {
		submitError.value = err?.message || t("Failed to submit transfer.");
	} finally {
		submitting.value = false;
	}
}

// Keyboard shortcut: Ctrl/Cmd+Enter fires the current default action
function onKeydown(e) {
	if (!createOpen.value) return;
	if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
		e.preventDefault();
		if (canSubmit.value && !submitting.value) submitCreate(savedMode.value);
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

async function cancelEntry() {
	if (!detail.value?.name) return;
	const ok = await confirm({
		title: t("Cancel Transfer"),
		body: t("Cancel this transfer?"),
		confirmLabel: t("Cancel Transfer"),
		cancelLabel: t("Close"),
		danger: true,
	});
	if (!ok) return;
	try {
		await call("stabler.api.money.cancel_bank_entry", { name: detail.value.name });
		toast.success(t("Transfer cancelled."));
		await openDetail(detail.value.name);
		await load();
	} catch (err) {
		detail.value.error = err?.message || t("Failed to cancel transfer.");
	}
}

async function deleteEntry() {
	if (!detail.value?.name) return;
	const ok = await confirm({
		title: t("Delete Draft Transfer"),
		body: t("Delete this draft transfer?"),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	try {
		await call("stabler.api.money.delete_bank_entry", { name: detail.value.name });
		toast.success(t("Draft transfer deleted."));
		closeDetail();
		await load();
	} catch (err) {
		detail.value.error = err?.message || t("Failed to delete transfer.");
	}
}

function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

onMounted(() => {
	load();
	loadOptions();
	document.addEventListener("keydown", onKeydown);
});
onUnmounted(() => {
	document.removeEventListener("keydown", onKeydown);
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

	<!-- Create / amend modal -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" aria-modal="true">
		<div class="modal-dialog modal-lg modal-dialog-centered" role="document">
			<div ref="modalEl" class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">
						<i class="ti ti-transfer me-1"></i>{{ formTitle }}
					</h5>
					<button type="button" class="btn-close" @click="closeCreate" aria-label="Close"></button>
				</div>

				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger mb-3">{{ submitError }}</div>

					<!-- Date -->
					<div class="mb-3" style="max-width: 230px">
						<label class="form-label small required">{{ t("Posting date") }}</label>
						<DateInput v-model="form.posting_date" />
					</div>

					<!-- FROM panel -->
					<div class="card card-sm mb-0" style="border: 1.5px solid var(--tblr-blue, #206bc4); border-radius: 6px">
						<div class="card-header py-2 px-3 d-flex align-items-center gap-2"
							style="background: var(--tblr-blue-lt, #e9f0fb); border-bottom: 1px solid var(--tblr-blue-lt, #d0e0f7); border-radius: 5px 5px 0 0">
							<span class="avatar avatar-xs bg-blue text-white rounded-circle" style="width:18px;height:18px;font-size:10px">↑</span>
							<span class="fw-semibold text-blue small">{{ t("From") }}</span>
						</div>
						<div class="card-body p-3">
							<div class="row g-2 align-items-end">
								<div class="col">
									<label class="form-label small mb-1 d-flex justify-content-between align-items-baseline">
										<span>{{ t("Account") }}
											<span v-if="fromAcc" class="text-secondary fw-normal">({{ fromCurrency }})</span>
										</span>
										<span v-if="fromAcc && fromAcc.account_balance != null" class="text-secondary fw-normal font-monospace">
											{{ fmtAmt(fromAcc.account_balance, fromCurrency) }} {{ fromCurrency }}
										</span>
									</label>
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
								<div class="col-5">
									<label class="form-label small mb-1">{{ t("Amount to transfer") }}</label>
									<MoneyInput
										:model-value="form.from_amount"
										:currency="fromCurrency"
										:language="user.language"
										:group-while-typing="true"
										:disabled="submitting"
										@update:model-value="onAmtInput"
									/>
								</div>
							</div>
						</div>
					</div>

					<!-- ROE band -->
					<div class="d-flex align-items-center justify-content-center gap-3 py-3 px-1">
						<div class="text-secondary" style="font-size: 1.2rem">↓</div>

						<div v-if="isCrossCurrency" class="flex-grow-1" style="max-width: 340px">
							<div class="text-center mb-1">
								<span class="text-secondary small text-uppercase fw-semibold" style="letter-spacing:.04em">
									{{ t("Exchange rate") }} · {{ fxBaseCur || fromCurrency }} → {{ fxCounterCur || toCurrency }}
								</span>
								<span v-if="!rateManuallyEdited" class="badge bg-blue-lt text-blue ms-1 small">AUTO</span>
							</div>
							<MoneyInput
								:model-value="form.exchange_rate"
								currency=""
								:language="user.language"
								:group-while-typing="true"
								:disabled="submitting"
								@update:model-value="onRateInput"
							/>
							<div v-if="cbuRate" class="text-center text-secondary small mt-1">
								CBU: 1 {{ fxBaseCur || fromCurrency }} = {{ fmtRate(cbuRate) }} {{ fxCounterCur || toCurrency }}
							</div>
						</div>
						<div v-else-if="fromAcc && toAcc" class="text-secondary small px-2">
							{{ t("Same currency") }}
						</div>

						<button
							type="button"
							class="btn btn-outline-secondary btn-icon"
							:disabled="!form.from_account && !form.to_account"
							:aria-label="t('Swap accounts')"
							@click="swap"
						>
							<i class="ti ti-arrows-exchange"></i>
						</button>
					</div>

					<!-- TO panel -->
					<div class="card card-sm mb-0" style="border: 1.5px solid var(--tblr-teal, #0ca678); border-radius: 6px">
						<div class="card-header py-2 px-3 d-flex align-items-center gap-2"
							style="background: var(--tblr-teal-lt, #d2f4ea); border-bottom: 1px solid var(--tblr-teal-lt, #b8ecdb); border-radius: 5px 5px 0 0">
							<span class="avatar avatar-xs bg-teal text-white rounded-circle" style="width:18px;height:18px;font-size:10px">↓</span>
							<span class="fw-semibold text-teal small">{{ t("To") }}</span>
						</div>
						<div class="card-body p-3">
							<div class="row g-2 align-items-end">
								<div class="col">
									<label class="form-label small mb-1 d-flex justify-content-between align-items-baseline">
										<span>{{ t("Account") }}
											<span v-if="toAcc" class="text-secondary fw-normal">({{ toCurrency }})</span>
										</span>
										<span v-if="toAcc && toAcc.account_balance != null" class="text-secondary fw-normal font-monospace">
											{{ fmtAmt(toAcc.account_balance, toCurrency) }} {{ toCurrency }}
										</span>
									</label>
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
								<div class="col-5">
									<label class="form-label small mb-1">{{ t("Amount received") }}</label>
									<MoneyInput
										:model-value="form.to_amount"
										:currency="toCurrency"
										:language="user.language"
										:group-while-typing="true"
										:disabled="submitting || !isCrossCurrency"
										@update:model-value="onRecvInput"
									/>
								</div>
							</div>
						</div>
					</div>

					<!-- Memo -->
					<div class="mt-3">
						<label class="form-label small mb-1">{{ t("Memo") }}</label>
						<input
							v-model="form.memo"
							type="text"
							class="form-control"
							:placeholder="t('Optional')"
							:disabled="submitting"
						/>
					</div>

					<!-- Summary line -->
					<div
						v-if="form.from_account && form.to_account && Number(form.from_amount) > 0"
						class="mt-3 px-1 text-secondary small"
					>
						{{ t("Transfer") }}
						<span class="font-monospace">{{ fmtAmt(form.from_amount, fromCurrency) }} {{ fromCurrency }}</span>
						→
						<span class="font-monospace">{{ fmtAmt(form.to_amount ?? form.from_amount, toCurrency) }} {{ toCurrency }}</span>
						<template v-if="isCrossCurrency && Number(form.exchange_rate) > 0">
							@ <span class="font-monospace">{{ fmtRate(form.exchange_rate) }}</span>
						</template>
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
								<i class="ti ti-x me-2"></i>{{ t("Record & close") }}
							</a>
							<a href="#" class="dropdown-item stbl-menu-item" @click.prevent="submitCreate('new')">
								<i class="ti ti-plus me-2"></i>{{ t("Record & new") }}
							</a>
							<a href="#" class="dropdown-item stbl-menu-item" @click.prevent="submitCreate('clear')">
								<i class="ti ti-eraser me-2"></i>{{ t("Record & clear") }}
							</a>
						</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
