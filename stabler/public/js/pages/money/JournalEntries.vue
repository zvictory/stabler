<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney, moneyFractionDigits } from "../../composables/money.js";
import {
	balanceCacheKey,
	balanceTolerance,
	computeBalancePlug,
	describePlugResidual,
	isDraftDirty,
	isPostingFrozen,
	isRowOrphaned,
	journalFreezeDate,
	postableRows,
	ratesToRefresh,
	snapshotDraft,
} from "../../composables/journal.js";
import { formatDate, formatDateTime, todayIso, daysAgoIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { accountLabel } from "../../composables/accounts.js";
import { getDocstatusLabel, getStatusBadgeClass } from "../../composables/status.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { readableRate, toLineRate, formatRate } from "../../composables/fx.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";

const session = useSession();
const route = useRoute();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();


const statusFilter = ref("");
const statusOptions = computed(() => [
	{ value: "", label: t("Draft + submitted") },
	{ value: "Draft", label: t("Draft") },
	{ value: "Submitted", label: t("Submitted") },
	{ value: "Cancelled", label: t("Cancelled") },
]);
const acting = ref(false);

const today = todayIso();
const monthAgo = daysAgoIso(30);

const fromDate = ref(monthAgo);
const toDate = ref(today);
const limit = ref(50);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

// Right pane: 'empty' | 'view' | 'edit'
const pane = ref("empty");
const detail = ref(null);
const detailLoading = ref(false);

// ESC → back (general app rule). There were two listeners here, and neither
// knew about the other: the generic one navigated away and the page-local one
// navigated again, so a draft in the edit pane was discarded — twice over —
// without a word. One listener, and the edit pane gets first refusal.
useEscapeBack(() => {
	if (pane.value !== "edit") return false;
	requestCancelEdit();
	return true;
}, "/money");

const VOUCHER_TYPES = [
	"Journal Entry", "Bank Entry", "Cash Entry", "Credit Card Entry",
	"Contra Entry", "Excise Entry", "Write Off Entry", "Opening Entry", "Depreciation Entry",
];

const submitting = ref(false);
const submitError = ref("");
const accountsLoading = ref(false);
const accountOptions = ref([]);

// `_auto` marks an amount this form derived rather than one the user typed.
// It is a UI concern only — submitForm rebuilds the payload field by field.
// `_rateTouched` marks a rate the user typed over — the bank's, the
// contract's — so moving the posting date does not quietly undo it.
const emptyRow = () => ({ account: "", account_currency: "", party_type: "", party: "", party_name: "", exchange_rate: 1, debit: null, credit: null, _auto: false, _rateTouched: false });
const form = ref(blankForm());
const editName = ref(null);
// The draft as it was opened — what "dirty" is measured against.
const pristine = ref(null);
// The posting date this draft was opened with; see the watcher at the bottom.
let formDate = null;
const isEdit = computed(() => !!editName.value);

const PARTY_TYPES = computed(() => [
	{ value: "", label: t("— No party —") },
	{ value: "Employee", label: t("Employee") },
	{ value: "Customer", label: t("Customer") },
	{ value: "Supplier", label: t("Supplier") },
]);

function blankForm() {
	return { posting_date: today, voucher_type: "Journal Entry", user_remark: "", cheque_no: "", cheque_date: "", accounts: [emptyRow(), emptyRow()] };
}

const currencyCode = computed(() => (session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency || "USD");
const currency = currencyCode;

// A line is "foreign" when its account currency differs from the company base.
const isForeign = (r) => !!r.account_currency && r.account_currency !== currencyCode.value;
const rateOf = (r) => (isForeign(r) ? Number(r.exchange_rate) || 0 : 1);
// The entry as the server will see it. An amount on a line whose account is
// still blank is dropped by submitForm and again by _clean_je_rows, so it must
// not reach the totals either — see postableRows() for what that cost.
const postable = computed(() => postableRows(form.value.accounts));
const isMultiCurrency = computed(() => postable.value.some(isForeign));
const baseDebit = computed(() => postable.value.reduce((s, r) => s + (Number(r.debit) || 0) * rateOf(r), 0));
const baseCredit = computed(() => postable.value.reduce((s, r) => s + (Number(r.credit) || 0) * rateOf(r), 0));
const baseLine = (r) => (Number(r.debit) || Number(r.credit) || 0) * rateOf(r);

// Single-currency: balance in that currency. Multi-currency: balance in the
// company base (each leg × its rate); sub-unit residuals are sealed by the JE
// FX hook, so allow a tiny tolerance. Foreign legs must carry a positive rate.
const totalDebit = computed(() => postable.value.reduce((s, r) => s + (Number(r.debit) || 0), 0));
const totalCredit = computed(() => postable.value.reduce((s, r) => s + (Number(r.credit) || 0), 0));
const diff = computed(() => (isMultiCurrency.value ? baseDebit.value - baseCredit.value : totalDebit.value - totalCredit.value));

// THE CONTRACT, stated once. balanceTolerance() mirrors residual_tolerance()
// in stabler/api/_fx_residual.py — the FX hook's threshold, and the last word
// on whether a document actually saves.
//
// The Math.min is the part that should not have to exist. api/money.py's
// _clean_je_rows rejects the payload BEFORE the hook can run, at a flat
// `1.0 if saw_foreign else 0.01` — two constants that know nothing about the
// base currency or the number of lines. Until they are derived from
// residual_tolerance(len(cleaned), base_precision_for(base_currency)) too, the
// form has to obey whichever gate is tighter, or it goes green on a payload
// the server throws straight out. Delete the Math.min when that lands.
const balanceTol = computed(() => {
	const ledger = balanceTolerance(postable.value.length, moneyFractionDigits(currencyCode.value));
	return Math.min(ledger, isMultiCurrency.value ? 1 : 0.01);
});
const balanced = computed(() => {
	if (isMultiCurrency.value && !postable.value.every((r) => !isForeign(r) || rateOf(r) > 0)) return false;
	// +1e-9 as in within_tolerance(): two exactly equal sums can still land an
	// ulp apart, and a form that calls that an imbalance cannot be satisfied.
	return Math.abs(diff.value) <= balanceTol.value + 1e-9;
});

// One line under the badge when the plug had to land on a foreign account and
// its own rounding is what is holding Save shut. See describePlugResidual().
const plugResidual = computed(() => describePlugResidual(form.value.accounts, { rateOf, tolerance: balanceTol.value }));

// Readable "1 strong = N weak" quote for a line (always the ≥1 direction).
const rateQuote = (row) => readableRate(row.exchange_rate, row.account_currency, currencyCode.value);
const fmtRate = (v) => formatRate(v, user.value.language);
// Readable quote string for a view-pane line, e.g. "1 USD = 12 034 сўм".
function viewQuote(a) {
	const q = readableRate(a.exchange_rate, a.account_currency, detail.value?.base_currency || currency.value);
	return q ? `1 ${q.strong} = ${fmtRate(q.value)} ${q.weak}` : "";
}
// User edits the readable N; store it back as the ERPNext per-line rate.
// Correcting a rate to the bank's or the contract's is the rule in a
// multi-currency entry, not the exception, and it moves every base figure the
// balance is measured in — so the plug has to be re-derived with it. -1: no
// line is off-limits; a rate is not an amount the user typed into a side.
function setRateQuote(row, val) {
	const q = rateQuote(row);
	if (!q) return;
	row.exchange_rate = toLineRate(val, q.strong, row.account_currency);
	row._rateTouched = true;
	runAutoBalance(-1);
}

async function fetchRate(row) {
	if (!isForeign(row) || !activeCompany.value) return;
	try {
		const rate = await call("stabler.api.money.get_exchange_rate_for_currencies", {
			from_currency: row.account_currency,
			to_currency: currencyCode.value,
			posting_date: form.value.posting_date,
		});
		if (Number(rate) > 0) row.exchange_rate = Number(rate);
	} catch {
		/* leave the rate for the user to enter */
	}
}

// ── Party + account pickers ──────────────────────────────────────────────────
function searchParty(row) {
	return async (q) => {
		if (!row.party_type || !activeCompany.value) return [];
		if (row.party_type === "Customer") {
			const r = await call("stabler.api.sales.list_customers", { company: activeCompany.value, search: q, limit: 10 });
			return (r || []).map((x) => ({ value: x.name, label: x.customer_name || x.name }));
		}
		if (row.party_type === "Supplier") {
			const r = await call("stabler.api.purchasing.list_suppliers", { company: activeCompany.value, search: q, limit: 10 });
			return (r || []).map((x) => ({ value: x.name, label: x.supplier_name || x.name }));
		}
		const r = await call("stabler.api.hr.list_employees", { company: activeCompany.value, search: q, limit: 10 });
		return (r || []).map((x) => ({ value: x.name, label: x.employee_name || x.name }));
	};
}
function pickParty(row, item) { row.party = item.value; row.party_name = item.label; }
function onPartyTypeChange(row) { row.party = ""; row.party_name = ""; }
function onAccountChange(row) {
	const a = accountOptions.value.find((o) => o.name === row.account);
	row.account_currency = (a && a.account_currency) || currencyCode.value;
	row._rateTouched = false; // a different account is a different rate question
	if (isForeign(row)) {
		if (!(Number(row.exchange_rate) > 0) || row.exchange_rate === 1) fetchRate(row);
	} else {
		row.exchange_rate = 1;
	}
	loadAcctBalance(row.account);
}

// ── Current account balance hint (cached per account AND date) ───────────────
// The figure is asked for `as_of` the posting date, so the date belongs in the
// key; caching it under the account alone left July's balance on screen next to
// an August entry, and "what is in the till" is exactly the decision it is for.
const acctBalances = ref({});
async function loadAcctBalance(account) {
	const key = balanceCacheKey(account, form.value.posting_date);
	if (!account || !activeCompany.value || acctBalances.value[key]) return;
	try {
		const b = await call("stabler.api.money.account_balance", {
			company: activeCompany.value, account, as_of: form.value.posting_date,
		});
		acctBalances.value = { ...acctBalances.value, [key]: b };
	} catch {
		/* hint is best-effort */
	}
}
function acctBalanceText(account) {
	const b = acctBalances.value[balanceCacheKey(account, form.value.posting_date)];
	if (!b) return "";
	const amount = formatMoney(b.balance_acc ?? b.balance_base, b.account_currency || currencyCode.value, user.value.language);
	// The date is not decoration: the hint answers a different question on
	// every posting date, and it used to answer all of them the same way.
	return `${t("Bal")}: ${amount} · ${formatDate(form.value.posting_date)}`;
}

// ── Contextual back-dating freeze ────────────────────────────────────────────
// Same source as the money-page banner, but NOT the same date: that banner
// speaks for every document type and takes the later of stock and accounting.
// A journal entry writes no stock ledger. See journalFreezeDate().
const backdating = ref(null);
const freezeDate = computed(() => journalFreezeDate(backdating.value));
const postingFrozen = computed(() => isPostingFrozen(form.value.posting_date, freezeDate.value));

// The cancelled JE this draft amends (set by amendJE), passed through on save.
const amendedFrom = ref(null);

function onAccountPicked(row, idx) {
	onAccountChange(row);
	runAutoBalance(idx);
}

async function loadAccountOptions() {
	if (!activeCompany.value || accountOptions.value.length) return;
	accountsLoading.value = true;
	try {
		const r = await call("stabler.api.money.chart_of_accounts", { company: activeCompany.value });
		accountOptions.value = (r || []).filter((a) => !a.is_group);
	} catch (err) {
		accountOptions.value = [];
		submitError.value = err?.message || t("Failed to load accounts.");
	} finally {
		accountsLoading.value = false;
	}
}

// ── List + selection ─────────────────────────────────────────────────────────
async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.money.list_journal_entries", {
			company: activeCompany.value, from_date: fromDate.value, to_date: toDate.value,
			status: statusFilter.value || undefined, limit: limit.value,
		});
	} catch (err) {
		error.value = err?.message || t("Failed to load journal entries.");
	} finally {
		loading.value = false;
	}
}

async function select(name) {
	pane.value = "view";
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.money.journal_entry_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || t("Failed to load.") };
	} finally {
		detailLoading.value = false;
	}
}

// ── Create / edit ────────────────────────────────────────────────────────────
async function openCreate() {
	form.value = blankForm();
	formDate = form.value.posting_date;
	editName.value = null;
	amendedFrom.value = null;
	submitError.value = "";
	pane.value = "edit";
	await loadAccountOptions();
	pristine.value = snapshotDraft(form.value);
}

async function openEdit(d) {
	submitError.value = "";
	await loadAccountOptions();
	editName.value = d.name;
	form.value = {
		posting_date: d.posting_date,
		voucher_type: d.voucher_type || "Journal Entry",
		user_remark: d.user_remark || "",
		cheque_no: d.cheque_no || "",
		cheque_date: d.cheque_date || "",
		accounts: (d.accounts || [])
			.filter((a) => !a.is_fx_rounding)
			.map((a) => ({
				account: a.account,
				account_currency: a.account_currency || currencyCode.value,
				party_type: a.party_type || "",
				party: a.party || "",
				party_name: a.party_name || "",
				exchange_rate: Number(a.exchange_rate) > 0 ? Number(a.exchange_rate) : 1,
				debit: a.debit_in_account_currency || null,
				credit: a.credit_in_account_currency || null,
				_auto: false, // an amount already posted is the user's, never ours to replace
				_rateTouched: false, // …but its rate follows the date until the user says otherwise
			})),
	};
	formDate = form.value.posting_date;
	while (form.value.accounts.length < 2) form.value.accounts.push(emptyRow());
	form.value.accounts.forEach((r) => r.account && loadAcctBalance(r.account));
	pristine.value = snapshotDraft(form.value);
	pane.value = "edit";
}

// Leaving the edit pane — by Escape or by the Cancel button — throws the draft
// away, and there is no undo behind it. Ask, but only when there is something
// to lose: a prompt in front of an untouched form teaches people to dismiss it.
async function requestCancelEdit() {
	if (submitting.value) return;
	if (isDraftDirty(form.value, pristine.value)) {
		const ok = await confirm({
			title: t("Discard this draft?"),
			body: t("The lines you entered have not been saved yet."),
			danger: true,
			confirmLabel: t("Discard"),
			cancelLabel: t("Keep editing"),
		});
		if (!ok) return;
	}
	cancelEdit();
}

function cancelEdit() {
	if (submitting.value) return;
	pristine.value = null;
	if (detail.value?.name) pane.value = "view";
	else pane.value = "empty";
}

function addRow() { form.value.accounts.push(emptyRow()); }
// The button used to be disabled at two lines, so on a two-line entry the wrong
// line could not be deleted at all. Delete it and get a fresh blank one back.
// -1: no line is off-limits, because nothing here is an amount the user typed.
function removeRow(idx) {
	form.value.accounts.splice(idx, 1);
	while (form.value.accounts.length < 2) form.value.accounts.push(emptyRow());
	runAutoBalance(-1);
}
// Both of these used to fire on @blur, so a row could hold a debit AND a
// credit while it had focus — the balance badge read "Balanced" on data the
// server rejects outright (api/money.py:_clean_je_rows). They run on the model
// update now, so the row is never inconsistent even for a keystroke.
function onAmountInput(row, idx, side) {
	const other = side === "debit" ? "credit" : "debit";
	if (Number(row[side])) row[other] = null;
	row._auto = false; // the user typed here; this amount is data now, not a derivation
	runAutoBalance(idx);
}

// A number this form derived and one the user typed used to look identical on
// screen. They are not the same kind of thing: the derived one is live and will
// change under you.
const isAutoAmount = (row, side) => !!row._auto && !!Number(row[side]);

// Fills the counter-line so an opening balance does not have to be added up by
// hand. Never touches an amount the user typed — see composables/journal.js.
function runAutoBalance(editedIdx) {
	const plug = computeBalancePlug(form.value.accounts, {
		editedIdx,
		rateOf,
		fractionDigitsOf: (r) => moneyFractionDigits(r.account_currency || currencyCode.value),
	});
	if (!plug) return;
	const target = form.value.accounts[plug.index];
	target[plug.field] = plug.value;
	target[plug.field === "debit" ? "credit" : "debit"] = null;
	target._auto = true;
}

async function submitForm() {
	submitError.value = "";
	if (!activeCompany.value) return (submitError.value = t("Select a company first."));
	// The band alone was the whole enforcement: the draft used to save and the
	// refusal arrived at Submit, from ERPNext, untranslated.
	if (postingFrozen.value) {
		return (submitError.value = t("Accounting is frozen before {0}.").replace("{0}", formatDate(freezeDate.value)));
	}
	if (!balanced.value) {
		// The two figures the badge is already showing, formatted the way the rest
		// of the screen formats money: .toFixed(2) printed "12000000.00" under a
		// footer that said "12 000 000 сўм" for the same amount.
		const shownDebit = isMultiCurrency.value ? baseDebit.value : totalDebit.value;
		const shownCredit = isMultiCurrency.value ? baseCredit.value : totalCredit.value;
		submitError.value = `${t("Debit")} ${formatMoney(shownDebit, currencyCode.value, user.value.language)} ≠ ${t("Credit")} ${formatMoney(shownCredit, currencyCode.value, user.value.language)}`;
		return;
	}
	const accounts = form.value.accounts
		.filter((r) => r.account && (Number(r.debit) || Number(r.credit)))
		.map((r) => ({ account: r.account, party_type: r.party_type || undefined, party: r.party || undefined, exchange_rate: rateOf(r), debit: Number(r.debit) || 0, credit: Number(r.credit) || 0 }));
	if (accounts.length < 2) return (submitError.value = t("At least two account lines are required."));
	submitting.value = true;
	try {
		let res;
		if (isEdit.value) {
			res = await call("stabler.api.money.update_journal_entry", {
				name: editName.value, posting_date: form.value.posting_date,
				user_remark: form.value.user_remark || undefined, cheque_no: form.value.cheque_no || undefined,
				cheque_date: form.value.cheque_date || undefined, accounts,
			});
		} else {
			res = await call("stabler.api.money.create_journal_entry", {
				company: activeCompany.value, posting_date: form.value.posting_date, voucher_type: form.value.voucher_type,
				user_remark: form.value.user_remark || undefined, cheque_no: form.value.cheque_no || undefined,
				cheque_date: form.value.cheque_date || undefined, accounts,
				amended_from: amendedFrom.value || undefined,
			});
			amendedFrom.value = null;
		}
		// The entry that just moved these balances is one of them now.
		acctBalances.value = {};
		await load();
		if (res?.name) await select(res.name);
		else pane.value = "empty";
	} catch (err) {
		submitError.value = err?.message || (isEdit.value ? t("Failed to update journal entry.") : t("Failed to create journal entry."));
	} finally {
		submitting.value = false;
	}
}

// ── Lifecycle actions: submit / cancel / amend ───────────────────────────────
async function submitJE() {
	if (!detail.value?.name) return;
	const ok = await confirm({
		title: t("Submit journal entry?"),
		body: t("This posts the entry to the ledger. Submitted entries can't be edited — only cancelled and amended."),
		confirmLabel: t("Submit"),
	});
	if (!ok) return;
	acting.value = true;
	try {
		await call("stabler.api.money.submit_journal_entry", { name: detail.value.name, modified: detail.value.modified });
		acctBalances.value = {}; // this entry is in the ledger now
		toast.success(t("Journal entry submitted."));
		await load();
		await select(detail.value.name);
	} catch (err) {
		toast.error(err?.message || t("Submit failed."));
	} finally {
		acting.value = false;
	}
}
async function cancelJE() {
	if (!detail.value?.name) return;
	const ok = await confirm({
		title: t("Cancel journal entry?"),
		body: t("This reverses the ledger postings. The entry stays as an audit record; create an amended one to correct it."),
		confirmLabel: t("Cancel entry"),
		danger: true,
	});
	if (!ok) return;
	acting.value = true;
	try {
		await call("stabler.api.money.cancel_journal_entry", { name: detail.value.name, modified: detail.value.modified });
		acctBalances.value = {}; // its postings are reversed out of these balances
		toast.success(t("Journal entry cancelled."));
		await load();
		await select(detail.value.name);
	} catch (err) {
		toast.error(err?.message || t("Cancel failed."));
	} finally {
		acting.value = false;
	}
}
// Amend = open the entry's lines as a fresh draft (new doc), leaving the
// cancelled original untouched.
async function amendJE() {
	if (!detail.value) return;
	const src = detail.value.name;
	await openEdit(detail.value);
	editName.value = null; // new doc, not an in-place edit
	amendedFrom.value = src; // …but linked to the cancelled original
}

onMounted(async () => {
	try {
		backdating.value = await call("stabler.api.money.get_backdating_status");
	} catch {
		backdating.value = null;
	}
	await load();
	const openName = route.query?.open;
	if (openName) select(String(openName));
});
watch(activeCompany, () => {
	accountOptions.value = [];
	acctBalances.value = {}; // another company's ledger, not this one's
	pane.value = "empty";
	detail.value = null;
	load();
});
watch(statusFilter, load);

// The posting date decides two things nothing was watching: the exchange rate
// the entry is booked at, and which day the "Bal:" hint is answering for. One
// watcher closes both. `formDate` is what the draft was opened with, so
// installing a different draft is not mistaken for the user moving the date —
// that would rewrite the rates a saved draft was created with.
watch(() => form.value.posting_date, (d) => {
	if (d === formDate) return;
	formDate = d;
	acctBalances.value = {};
	ratesToRefresh(form.value.accounts, isForeign).forEach(fetchRate);
	form.value.accounts.forEach((r) => r.account && loadAcctBalance(r.account));
});
</script>

<template>
	<!-- Toolbar -->
	<div class="d-flex flex-wrap align-items-end gap-2 mb-3">
		<div><label class="form-label small mb-1">{{ t("From") }}</label><DateInput v-model="fromDate" size="sm" /></div>
		<div><label class="form-label small mb-1">{{ t("To") }}</label><DateInput v-model="toDate" size="sm" /></div>
		<div style="min-width: 160px"><label class="form-label small mb-1">{{ t("Status") }}</label><Select v-model="statusFilter" :options="statusOptions" size="sm" /></div>
		<button type="button" class="btn btn-sm btn-outline-secondary" @click="load"><i class="ti ti-refresh me-1"></i>{{ t("Apply") }}</button>
		<button type="button" class="btn btn-sm btn-primary ms-auto" :disabled="!activeCompany" @click="openCreate">
			<i class="ti ti-plus me-1"></i>{{ t("New journal") }}
		</button>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<div class="card">
		<div class="row g-0">
			<!-- LEFT: entries -->
			<div class="col-12 col-md-5 col-lg-4 border-end">
				<div style="max-height: calc(100vh - 12rem); overflow-y: auto">
					<table class="table table-sm table-hover mb-0">
						<thead><tr>
							<th>{{ t("Entry") }}</th>
							<!-- The figure is total_debit_base — the COMPANY's currency, not the
							     entry's. Unlabelled, a multi-currency entry's so'm total read as
							     the USD figure the user had just typed. The detail table has
							     said "Total (UZS)" over the same number all along. -->
							<th class="text-end">{{ t("Total") }} ({{ currency }})</th>
						</tr></thead>
						<SkeletonRows v-if="loading" :rows="12" :cols="2" />
						<tbody v-else>
							<tr v-if="!rows.length"><td colspan="2" class="text-secondary text-center py-4">{{ t("No journal entries in this range") }}</td></tr>
							<tr
								v-for="r in rows"
								:key="r.name"
								class="cursor-pointer"
								:class="{ 'table-active': detail?.name === r.name && pane === 'view' }"
								@click="select(r.name)"
							>
								<td>
									<div class="d-flex align-items-center gap-1">
										<span class="fw-semibold font-monospace small text-truncate">{{ r.name }}</span>
										<i v-if="r.multi_currency" class="ti ti-arrows-exchange text-azure" :title="t('Multi-currency')" style="font-size:.85rem"></i>
									</div>
									<div v-if="r.user_remark" class="small text-truncate" style="max-width: 220px">{{ r.user_remark }}</div>
									<div class="small text-secondary">{{ formatDate(r.posting_date) }} ·
										<span class="badge" :class="getStatusBadgeClass('Journal Entry', r.docstatus)">{{ getDocstatusLabel(r.docstatus) }}</span>
									</div>
								</td>
								<td class="text-end font-monospace align-middle">{{ formatMoney(r.total_debit_base, r.base_currency || currency, user.language) }}</td>
							</tr>
						</tbody>
					</table>
				</div>
			</div>

			<!-- RIGHT: detail / editor -->
			<div class="col-12 col-md-7 col-lg-8 bg-light">
				<!-- empty -->
				<EmptyState
					v-if="pane === 'empty'"
					class="py-6"
					icon="ti-book"
					accentIcon="ti-plus"
					tone="info"
					:title="t('Select a journal entry')"
					:subtitle="t('Pick one on the left, or create a new journal.')"
				/>

				<!-- view -->
				<div v-else-if="pane === 'view'" class="p-3">
					<div v-if="detailLoading" class="text-center py-5"><span class="spinner-border text-primary"></span></div>
					<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
					<div v-else-if="detail">
						<div class="d-flex align-items-center justify-content-between mb-3">
							<div>
								<h3 class="m-0 font-monospace">{{ detail.name }}</h3>
								<div class="small text-secondary">{{ formatDateTime(detail.posting_date) }} · {{ detail.voucher_type }}
									· <span class="badge" :class="getStatusBadgeClass('Journal Entry', detail.docstatus)">{{ getDocstatusLabel(detail.docstatus) }}</span>
								</div>
							</div>
							<div class="d-flex gap-2">
								<template v-if="detail.docstatus === 0">
									<button type="button" class="btn btn-outline-secondary" :disabled="acting" @click="openEdit(detail)">
										<i class="ti ti-pencil me-1"></i>{{ t("Edit") }}
									</button>
									<button type="button" class="btn btn-primary" :disabled="acting" @click="submitJE">
										<i class="ti ti-check me-1"></i>{{ t("Submit") }}
									</button>
								</template>
								<button v-else-if="detail.docstatus === 1" type="button" class="btn btn-outline-danger" :disabled="acting" @click="cancelJE">
									<i class="ti ti-ban me-1"></i>{{ t("Cancel entry") }}
								</button>
								<button v-else-if="detail.docstatus === 2" type="button" class="btn btn-outline-primary" :disabled="acting" @click="amendJE">
									<i class="ti ti-copy me-1"></i>{{ t("Amend (new draft)") }}
								</button>
							</div>
						</div>

						<div v-if="detail.user_remark" class="text-secondary mb-3">{{ detail.user_remark }}</div>

						<table class="table table-sm table-vcenter">
							<thead><tr>
								<th>{{ t("Account") }}</th><th>{{ t("Party") }}</th>
								<th class="text-end">{{ t("Debit") }}</th><th class="text-end">{{ t("Credit") }}</th>
							</tr></thead>
							<tbody>
								<tr v-for="(a, i) in detail.accounts" :key="i">
									<td>{{ accountLabel(a) || a.account }}</td>
									<td>{{ a.party_name || a.party || "—" }}</td>
									<td class="text-end font-monospace">
										{{ a.debit_in_account_currency ? formatMoney(a.debit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language) : "—" }}
										<div v-if="a.debit_in_account_currency && a.account_currency && a.account_currency !== (detail.base_currency || currency)" class="text-secondary" style="font-size:.7rem">
											{{ viewQuote(a) }} → {{ formatMoney(a.debit_base, detail.base_currency || currency, user.language) }}
										</div>
									</td>
									<td class="text-end font-monospace">
										{{ a.credit_in_account_currency ? formatMoney(a.credit_in_account_currency, a.account_currency || detail.base_currency || currency, user.language) : "—" }}
										<div v-if="a.credit_in_account_currency && a.account_currency && a.account_currency !== (detail.base_currency || currency)" class="text-secondary" style="font-size:.7rem">
											{{ viewQuote(a) }} → {{ formatMoney(a.credit_base, detail.base_currency || currency, user.language) }}
										</div>
									</td>
								</tr>
							</tbody>
							<tfoot><tr class="fw-bold">
								<td colspan="2">{{ t("Total") }} ({{ detail.base_currency || currency }})</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_debit_base, detail.base_currency || currency, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(detail.total_credit_base, detail.base_currency || currency, user.language) }}</td>
							</tr></tfoot>
						</table>
					</div>
				</div>

				<!-- edit -->
				<div v-else class="p-3">
					<div class="d-flex align-items-center justify-content-between mb-3">
						<h3 class="m-0">
							{{ isEdit ? t("Edit journal entry") : t("New journal entry") }}
							<span v-if="isEdit" class="text-secondary fw-normal font-monospace small ms-1">· {{ editName }}</span>
							<span v-if="amendedFrom" class="badge bg-azure-lt ms-1">{{ t("Amending") }} {{ amendedFrom }}</span>
						</h3>
					</div>
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div v-if="postingFrozen" class="alert alert-warning py-2 px-3 d-flex align-items-center">
						<i class="ti ti-calendar-lock me-2"></i>
						<span class="flex-fill small">
							{{ t("Accounting is frozen before {0}.").replace("{0}", formatDate(freezeDate)) }}
							{{ t("Move the date forward or open the posting window to save.") }}
						</span>
						<RouterLink to="/admin/posting-window" class="small text-reset text-decoration-underline ms-2">{{ t("Change") }}</RouterLink>
					</div>

					<div class="row g-2 mb-2">
						<div class="col-sm-4"><label class="form-label small">{{ t("Posting date") }}</label><DateInput v-model="form.posting_date" size="sm" /></div>
						<div class="col-sm-4" v-if="!isEdit"><label class="form-label small">{{ t("Type") }}</label><Select v-model="form.voucher_type" size="sm" :options="VOUCHER_TYPES" /></div>
						<div class="col-sm-4"><label class="form-label small">{{ t("Cheque no.") }}</label><input v-model="form.cheque_no" type="text" class="form-control form-control-sm" :placeholder="t('optional')" /></div>
						<div class="col-12"><label class="form-label small">{{ t("Remark") }}</label><input v-model="form.user_remark" type="text" class="form-control form-control-sm" :placeholder="t('What is this entry for?')" /></div>
					</div>

					<table class="table table-sm table-vcenter mb-0">
						<thead><tr>
							<th style="min-width: 170px">{{ t("Account") }}</th>
							<th style="min-width: 200px">{{ t("Party") }}</th>
							<th v-if="isMultiCurrency" class="text-end" style="width: 152px">{{ t("Rate") }}</th>
							<th class="text-end" style="width: 148px">{{ t("Debit") }}</th>
							<th class="text-end" style="width: 148px">{{ t("Credit") }}</th>
							<th class="w-1"></th>
						</tr></thead>
						<tbody>
							<tr v-for="(row, idx) in form.accounts" :key="idx">
								<td>
									<Select v-model="row.account" size="sm" :class="{ 'is-invalid': isRowOrphaned(row) }" :options="accountOptions" value-key="name" :placeholder="t('— Choose account —')" @change="onAccountPicked(row, idx)">
										<template #option="{ option }">{{ option.account_number ? `${option.account_number} · ` : "" }}{{ accountLabel(option) }}</template>
										<template #selected="{ option }">{{ option.account_number ? `${option.account_number} · ` : "" }}{{ accountLabel(option) }}</template>
									</Select>
									<div v-if="isRowOrphaned(row)" class="text-danger je-hint mt-1">{{ t("No account — this line is not counted.") }}</div>
									<div v-if="row.account" class="d-flex align-items-center gap-1 mt-1">
										<span class="badge bg-secondary-lt text-uppercase je-ccy">{{ row.account_currency || currencyCode }}</span>
										<span v-if="acctBalanceText(row.account)" class="text-secondary je-hint">{{ acctBalanceText(row.account) }}</span>
									</div>
								</td>
								<td>
									<div class="d-flex gap-1">
										<Select v-model="row.party_type" size="sm" :options="PARTY_TYPES" style="max-width: 92px" @change="onPartyTypeChange(row)" />
										<Typeahead v-if="row.party_type" :model-value="row.party" :search="searchParty(row)" :display="row.party_name" size="sm" class="flex-fill" :placeholder="t('Search name…')" @pick="(item) => pickParty(row, item)" @clear="() => onPartyTypeChange(row)">
											<template #option="{ item }">{{ item.label }}</template>
										</Typeahead>
									</div>
								</td>
								<td v-if="isMultiCurrency" class="text-end">
									<template v-if="isForeign(row) && rateQuote(row)">
										<MoneyInput :model-value="rateQuote(row).value" :language="user.language" :min="0" size="sm" @update:model-value="(v) => setRateQuote(row, v)" />
										<div class="text-secondary je-hint text-nowrap">1 {{ rateQuote(row).strong }} = {{ fmtRate(rateQuote(row).value) }} {{ rateQuote(row).weak }}</div>
										<div v-if="baseLine(row)" class="text-secondary je-hint text-nowrap">= {{ formatMoney(baseLine(row), currencyCode, user.language) }}</div>
									</template>
									<span v-else class="text-secondary small">1</span>
								</td>
								<td :class="{ 'je-auto': isAutoAmount(row, 'debit') }" :title="isAutoAmount(row, 'debit') ? t('Filled in to balance the entry') : null">
									<MoneyInput v-model="row.debit" :currency="row.account_currency || currencyCode" hide-currency :language="user.language" size="sm" @update:model-value="onAmountInput(row, idx, 'debit')" />
								</td>
								<td :class="{ 'je-auto': isAutoAmount(row, 'credit') }" :title="isAutoAmount(row, 'credit') ? t('Filled in to balance the entry') : null">
									<MoneyInput v-model="row.credit" :currency="row.account_currency || currencyCode" hide-currency :language="user.language" size="sm" @update:model-value="onAmountInput(row, idx, 'credit')" />
								</td>
								<td><button type="button" class="btn btn-sm btn-ghost-danger" @click="removeRow(idx)"><i class="ti ti-trash"></i></button></td>
							</tr>
						</tbody>
						<tfoot>
							<tr class="fw-bold">
								<td :colspan="isMultiCurrency ? 3 : 2"><button type="button" class="btn btn-sm btn-ghost-primary" @click="addRow"><i class="ti ti-plus me-1"></i>{{ t("Add row") }}</button></td>
								<td class="text-end font-monospace">{{ formatMoney(isMultiCurrency ? baseDebit : totalDebit, currencyCode, user.language) }}</td>
								<td class="text-end font-monospace">{{ formatMoney(isMultiCurrency ? baseCredit : totalCredit, currencyCode, user.language) }}</td>
								<td><span class="badge" :class="balanced ? 'bg-green-lt' : 'bg-red-lt'">{{ balanced ? t("Balanced") : "Δ " + formatMoney(diff, currencyCode, user.language) }}</span></td>
							</tr>
							<tr v-if="plugResidual"><td colspan="6" class="text-warning small fw-normal pt-0">
								{{ t("{0} converts to {1}; the other lines come to {2}.")
									.replace("{0}", formatMoney(plugResidual.amount, plugResidual.currency || currencyCode, user.language))
									.replace("{1}", formatMoney(plugResidual.base, currencyCode, user.language))
									.replace("{2}", formatMoney(plugResidual.counterBase, currencyCode, user.language)) }}
							</td></tr>
							<tr v-if="isMultiCurrency"><td colspan="6" class="text-secondary small fw-normal pt-0">{{ t("Totals shown in base currency ({0}).").replace("{0}", currencyCode) }}</td></tr>
						</tfoot>
					</table>

					<div class="d-flex justify-content-end gap-2 mt-3">
						<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="requestCancelEdit">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="submitting || !balanced || accountsLoading || postingFrozen" @click="submitForm">
							<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
							{{ isEdit ? t("Save changes") : t("Save as Draft") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
/* The line hints (rate quote, base equivalent, account balance) sit under a
   form control in a table cell. At the default size they wrapped a rate quote
   into four lines — "1 USD =" / "12 000 UZS" / "=" / "12 000 000 сўм" — which
   is how a multi-currency journal row came apart on screen. */
.je-hint {
	font-size: 0.7rem;
	line-height: 1.15;
}
.je-ccy {
	font-size: 0.65rem;
	padding: 0.1rem 0.3rem;
}
/* An amount the form worked out for itself. It is live — it changes as the
   other lines change — and it looked exactly like a figure the user had typed,
   which is the whole reason a stale plug went unnoticed. */
.je-auto {
	background-color: var(--tblr-primary-lt, rgba(32, 107, 196, 0.06));
}
</style>
