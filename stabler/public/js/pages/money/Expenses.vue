<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney, moneyFractionDigits } from "../../composables/money.js";
import { quotedLeg, readableRate, toLineRate } from "../../composables/fx.js";
import { SAVE_MODES, resolveSaveMode } from "../../composables/saveMode.js";
import { formatDate, formatDateTime, todayIso, daysAgoIso} from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useToast } from "../../composables/useToast.js";
import StatusBadge from "../../components/StatusBadge.vue";
import { createIntentKey } from "../../composables/idempotency.js";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import { useFocusTrap } from "../../composables/useFocusTrap.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
// Tender (Deal) picker is gated on the "tender" module — mirrors the pattern
// used by crm/Deals.vue and the tender/* pages (router.js meta.module).
const tenderOn = computed(() => session.canAccessModule("tender"));
const importsOn = computed(() => session.canAccessModule("imports"));


const { confirm } = useConfirm();
const toast = useToast();
// One key per intent, not per request: a save that fails leaves the filled form
// on screen, and the retry the operator then makes must reach the server as the
// same click rather than as a second expense. Settled on success so the next
// save is a new intent. Backed by the unique `custom_idempotency_key`.
const intent = createIntentKey();


const today = todayIso();
const monthAgo = daysAgoIso(30);

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

// ESC → close the open form/detail first, otherwise go back (general app rule).
useEscapeBack(() => {
	if (createOpen.value) { closeCreate(); return true; }
	if (detailOpen.value) { closeDetail(); return true; }
	return false;
}, "/money");
const submitting = ref(false);
const submitError = ref("");
// A failed submit is not proof that nothing was written: the request can have
// reached the server and posted the entry, and only the response gone missing
// (gunicorn/nginx timeout on a shared bench). The form stays filled in, so the
// obvious next move is to click Submit again — and nothing on the server stops
// it. Two identical bank entries are indistinguishable apart from their serial.
// Until the entry carries a payload-derived key, this warning is the guard.
const resubmitWarning = ref(false);
const editingName = ref("");
// Tracks `editingName`. The badge and the heading are only honest while it
// does, so every place that clears the name clears this too -- otherwise the
// next NEW entry renders wearing the last-amended voucher's badge.
const editingDocstatus = ref(null);

const payAccounts = ref([]);
const expAccounts = ref([]);
const assetAccounts = ref([]);
const equityAccounts = ref([]);
const assets = ref([]); // existing ERPNext Asset records (asset-purchase picker)
const optionsLoading = ref(false);

// QuickBooks-style save mode — persisted per user. Which modes may be
// remembered is decided in composables/saveMode.js: whatever is in the store
// becomes the default action of the primary button, so a mode that does not
// save cannot be one of them. "Save & clear" used to be, and discarded.
const SAVE_MODE_KEY = "stabler.expenses.saveMode";
const savedMode = ref(resolveSaveMode(localStorage.getItem(SAVE_MODE_KEY)));
const SAVE_LABELS = { close: "Save & close", new: "Save & new" };
const saveModeLabel = computed(() => t(SAVE_LABELS[savedMode.value] || "Save & close"));

function persistSaveMode(mode) {
	if (!SAVE_MODES.includes(mode)) return;
	savedMode.value = mode;
	localStorage.setItem(SAVE_MODE_KEY, mode);
}

const baseCurrency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD",
);

// Exchange rate context. `fetchedLineRate` holds the server's rate in ERPNext's
// own direction — base currency per 1 payment-account unit, which is exactly
// what `submit_expense_entry` multiplies the payment total by. Everything the
// operator sees (label, input, base preview) and everything the payload carries
// is derived from it through composables/fx.js, so the three cannot disagree.
const fetchedLineRate = ref(0);
const cbuRate = ref(null);
const rateDate = ref(null);
const rateError = ref("");


function fmtAmt(v, cur) {
	// Precision belongs to money.js, which reads it off the ledger. This line
	// held a third private copy of "UZS -> whole so'm" and outlived c7607d9's
	// correction, so a 1 500 000,50 balance rendered here as 1 500 001.
	const dp = moneyFractionDigits(cur);
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
	return { id: `g${++ghostSeq}`, account: "", amount: null, memo: "", asset: "" };
}

const ghost = ref(newGhost());
const form = ref(blankForm());
const linesTableEl = ref(null);
// Display label for form.deal (a CRM Deal name/id) — kept separate since the
// Typeahead only stores the id in v-model; resolved via searchDeals/pickDeal
// or loadDealLabel() when prefilling from an existing entry.
const dealLabel = ref("");

// Unsaved-changes guard: if the form is open and edited, confirm before leaving
// the page (sidebar click, browser back/refresh). Gated on createOpen so the list
// view never triggers it.
const dirtyPristine = ref("");
function markFormPristine() {
	dirtyPristine.value = JSON.stringify(form.value);
}
const formDirty = computed(
	() => createOpen.value && JSON.stringify(form.value) !== dirtyPristine.value,
);
onBeforeRouteLeave(async () => {
	if (!formDirty.value) return true;
	return await confirm({
		title: t("Discard unsaved changes?"),
		body: t("You have unsaved changes. Leaving this page will discard them."),
		danger: true,
		confirmLabel: t("Discard"),
		cancelLabel: t("Keep Editing"),
	});
});
function onBeforeUnloadGuard(e) {
	if (formDirty.value) {
		e.preventDefault();
		e.returnValue = "";
	}
}
onMounted(() => window.addEventListener("beforeunload", onBeforeUnloadGuard));
onBeforeUnmount(() => window.removeEventListener("beforeunload", onBeforeUnloadGuard));

function blankForm() {
	lineSeq = 0;
	return {
		posting_date: today,
		entry_kind: "Expense",
		payee: "",
		payment_from: "",
		exchange_rate: null,
		deal: "",
		commercial_invoice: "",
		import_truck: "",
		import_container: "",
		import_category: "",
		lines: [],
	};
}


function materialGhost(item) {
	form.value.lines.push({
		id: ++lineSeq,
		account: item.name,
		amount: ghost.value.amount,
		memo: ghost.value.memo,
		asset: "",
	});
	ghost.value = newGhost();
	// Like the Sales Order line editor: once the account is picked, drop the cursor
	// into the new line's amount so the user can keep typing without reaching for
	// the mouse.
	nextTick(focusNewLineAmount);
}

function lineRows() {
	const tbody = linesTableEl.value?.querySelector("tbody");
	return tbody ? Array.from(tbody.querySelectorAll("tr")) : [];
}

function focusNewLineAmount() {
	const rows = lineRows();
	// Real lines render before the trailing ghost row, so the just-added line is
	// the second-to-last row; its amount is the 2nd input.
	const inputs = Array.from(rows[rows.length - 2]?.querySelectorAll("input") || []);
	inputs[1]?.focus();
	inputs[1]?.select?.();
}

// Tab flow in line rows: Amount → Memo (same row) → ghost account (new line).
function handleLineKeyDown(e) {
	if (e.key !== "Tab" || e.shiftKey) return;
	const activeEl = document.activeElement;
	if (!activeEl || activeEl.tagName !== "INPUT") return;
	const row = activeEl.closest("tr");
	const tbody = row?.closest("tbody");
	if (!tbody) return;
	const rows = Array.from(tbody.querySelectorAll("tr"));
	const inputs = Array.from(row.querySelectorAll("input"));
	const idx = inputs.indexOf(activeEl);
	if (idx === 1) {
		// Tab from Amount → Memo (same row)
		e.preventDefault();
		inputs[2]?.focus();
	} else if (idx === 2 && row !== rows[rows.length - 1]) {
		// Tab from Memo of a real line → ghost row's account
		e.preventDefault();
		rows[rows.length - 1]?.querySelector("input")?.focus();
	}
}

const paymentFromAccount = computed(() =>
	payAccounts.value.find((a) => a.name === form.value.payment_from) || null,
);

const payCurrency = computed(
	() => paymentFromAccount.value?.account_currency || baseCurrency.value,
);

const isCrossCurrency = computed(
	() => payCurrency.value && payCurrency.value !== baseCurrency.value,
);

// The quote the operator reads: always the ≥ 1 direction, "1 strong = N weak".
// Derived from the currency pair currently on screen, so a rate fetched for an
// account that has since been swapped out can never keep its direction on the
// label — the number under it would then be read the wrong way round.
const rateQuote = computed(() =>
	readableRate(fetchedLineRate.value, payCurrency.value, baseCurrency.value),
);
const fxBaseCur = computed(() => rateQuote.value?.strong || "");
const fxCounterCur = computed(() => rateQuote.value?.weak || "");

const totalAmount = computed(() =>
	form.value.lines.reduce((sum, l) => sum + (Number(l.amount) || 0), 0),
);

const lineAccounts = computed(() => {
	const base = form.value.entry_kind === "Asset Purchase" ? assetAccounts.value : expAccounts.value;
	return [...base, ...equityAccounts.value];
});

// "Amend" is the word for cancelling a POSTED voucher and posting a replacement
// against it. A draft edit deletes the draft outright and re-creates it under a
// new name (money.py:3518-3522) -- a different promise, and the one that does
// not touch the ledger, so it says so.
const formTitle = computed(() =>
	editingName.value
		? editingDocstatus.value === 1
			? t("Amend expense")
			: t("Edit draft expense")
		: form.value.entry_kind === "Asset Purchase"
			? t("New asset purchase")
			: t("New expense"),
);

// `form.exchange_rate` is the number in the input, in the direction the label
// states — never the raw API quote. quotedLeg() is the single place that turns
// it into base currency, and the payload below calls into the same file for the
// rate it sends, so the preview and the posting cannot drift apart.
const baseEquivalent = computed(() => {
	if (!isCrossCurrency.value) return totalAmount.value;
	return quotedLeg(form.value.exchange_rate, fxBaseCur.value, payCurrency.value, totalAmount.value)
		.baseAmount;
});

function lineBaseAmount(line) {
	if (!isCrossCurrency.value) return null;
	const leg = quotedLeg(
		form.value.exchange_rate,
		fxBaseCur.value,
		payCurrency.value,
		Number(line.amount) || 0,
	);
	return leg.lineRate > 0 ? leg.baseAmount : null;
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
	// Cleared first, on every path. This runs because the account or the date
	// just changed, which means any rate already on screen was quoted for a pair
	// or a day that is no longer the one being posted; the failure branches used
	// to leave it standing, and `canSubmit` only ever asked whether the number
	// was positive.
	fetchedLineRate.value = 0;
	cbuRate.value = null;
	rateDate.value = null;
	rateError.value = "";
	form.value.exchange_rate = null;
	if (!isCrossCurrency.value) return;
	const asked = `${baseCurrency.value}|${payCurrency.value}|${form.value.posting_date}`;
	try {
		const raw = await call("stabler.api.money.get_exchange_rate_for_currencies", {
			from_currency: baseCurrency.value,
			to_currency: payCurrency.value,
			posting_date: form.value.posting_date,
		});
		// The account or the date can have moved while this was in flight. A rate
		// that arrives for a pair nobody is looking at any more must not land on
		// the pair that is — it now decides the direction of the label too, not
		// only its magnitude.
		if (asked !== `${baseCurrency.value}|${payCurrency.value}|${form.value.posting_date}`) return;
		if (raw > 0) {
			// The API answers in payment units per 1 base unit; ERPNext and
			// `submit_expense_entry` want the reciprocal — base per payment unit.
			fetchedLineRate.value = 1 / raw;
			// The input holds the readable quote, which is what its own label
			// ("1 USD =") and the CBU hint beneath it both state. It used to hold
			// the raw API number instead: 0.0000772 under a label asking for
			// 12 953, rendered as "0.00", and retyping the 12 953 the label asked
			// for posted a $100 expense as 0.0077 сўм.
			cbuRate.value = rateQuote.value.value;
			form.value.exchange_rate = rateQuote.value.value;
			rateDate.value = form.value.posting_date;
		} else {
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

// ----- Asset picker (Asset-purchase mode) -----
const assetMode = computed(() => form.value.entry_kind === "Asset Purchase");

function searchAsset(q) {
	const n = norm(q);
	if (!n) return assets.value;
	return assets.value.filter(
		(a) => norm(a.asset_name || a.name).includes(n) || norm(a.name).includes(n),
	);
}

function assetDisplay(name) {
	const a = assets.value.find((x) => x.name === name);
	return a ? a.asset_name || a.name : name;
}

// Selecting an asset auto-fills the line's fixed-asset GL account (from the
// asset's category), so the user picks the asset and the accounting follows.
function pickAssetOnLine(line, asset) {
	line.asset = asset.name;
	if (asset.fixed_asset_account) line.account = asset.fixed_asset_account;
}

function materialAssetGhost(asset) {
	form.value.lines.push({
		id: ++lineSeq,
		account: asset.fixed_asset_account || "",
		amount: ghost.value.amount,
		memo: ghost.value.memo,
		asset: asset.name,
	});
	ghost.value = newGhost();
	nextTick(focusNewLineAmount);
}

function lineCurrencyMismatch(line) {
	// Don't accuse a line of a currency mismatch until a "Pay from" account is
	// actually chosen — before that, payCurrency falls back to the base currency
	// (often USD) and would wrongly flag every UZS expense account on open.
	if (!form.value.payment_from) return false;
	if (!line.account) return false;
	// Asset-purchase debits may sit in a different currency from the paying
	// account (e.g. UZS cash → USD asset account); the backend anchors those to
	// the base total, so a currency difference is not an error here.
	if (assetMode.value) return false;
	const picked = lineAccounts.value.find((a) => a.name === line.account);
	if (!picked) return false;
	return picked.account_currency && picked.account_currency !== payCurrency.value;
}

// --- Tender (Deal) picker — only rendered when tenderOn is true ------------

async function searchDeals(q) {
	// Şirket zorunlu: `_require_crm_company` yoksa 417 atıyor ve Typeahead hatayı
	// yutup boş liste gösteriyor.
	const r = await call("stabler.api.crm.list_deals", {
		company: activeCompany.value,
		search: q,
		page_length: 8,
	});
	return (r?.deals || []).map((d) => ({ name: d.name, label: d.organization || d.lead_name || d.name }));
}

function pickDeal(item) {
	form.value.deal = item.name;
	dealLabel.value = item.label;
}

function clearDeal() {
	form.value.deal = "";
	dealLabel.value = "";
}

async function loadDealLabel(dealName) {
	if (!dealName) {
		dealLabel.value = "";
		return;
	}
	try {
		const d = await call("stabler.api.crm.get_deal", { name: dealName });
		dealLabel.value = d?.organization || d?.lead_name || dealName;
	} catch (err) {
		dealLabel.value = dealName;
	}
}


// --- Import (Commercial Invoice) picker — gated on imports module ----------
const ciLabel = ref("");

async function searchCommercialInvoices(q) {
	const r = await call("stabler.api.imports.list_commercial_invoices", {
		company: activeCompany.value,
		search: q,
		limit_page_length: 8,
	});
	return (r?.rows || []).map((ci) => ({
		name: ci.name,
		label: `${ci.ci_number || ci.name} (${ci.supplier_name || ci.supplier || "—"})`,
		ci_number: ci.ci_number,
	}));
}

// Categories mirror Import Expense.category exactly — the spawned expense copies
// the value straight through, so a divergence here would fail its Select validation.
const IMPORT_CATEGORIES = [
	"Border Crossing",
	"Transport",
	"Handling",
	"Storage",
	"Insurance",
	"Documentation",
	"Customs",
	"Other",
];

// Only an "Expenses Included In Valuation" account can be capitalized onto the
// containers later (ERPNext's Landed Cost Voucher rejects anything else). The
// list already carries account_type, so no extra round-trip is needed.
const valuationAccount = computed(
	() => expAccounts.value.find((a) => a.account_type === "Expenses Included In Valuation")?.name || "",
);

function pickCI(item) {
	form.value.commercial_invoice = item.name;
	ciLabel.value = item.label;
	// The category Select only appears once a CI is picked, so seed it with the
	// same fallback the backend uses rather than showing an empty control.
	if (!form.value.import_category) form.value.import_category = "Other";
	// Steer the operator to the valuation account up front, so the landed-cost
	// account-type check is a safety valve rather than a dead end at submit time.
	// Only empty rows are touched — a deliberate account choice is never overwritten.
	if (valuationAccount.value) {
		for (const line of form.value.lines) {
			if (!line.account) line.account = valuationAccount.value;
		}
		if (!ghost.value.account) ghost.value.account = valuationAccount.value;
	}
}

function clearCI() {
	form.value.commercial_invoice = "";
	ciLabel.value = "";
	form.value.import_category = "";
}

async function loadCILabel(ciName) {
	if (!ciName) {
		ciLabel.value = "";
		return;
	}
	ciLabel.value = ciName;
}


async function loadOptions() {
	if (!activeCompany.value) return;
	optionsLoading.value = true;
	try {
		const [pay, exp, fixed, equity, assetRows] = await Promise.all([
			call("stabler.api.money.bank_cash_accounts", {
				company: activeCompany.value,
				include_equity: 1,
			}),
			call("stabler.api.money.expense_accounts", { company: activeCompany.value }),
			call("stabler.api.money.fixed_asset_accounts", { company: activeCompany.value }),
			call("stabler.api.money.equity_accounts", { company: activeCompany.value }),
			call("stabler.api.money.list_assets", { company: activeCompany.value }).catch(() => []),
		]);
		payAccounts.value = pay || [];
		expAccounts.value = exp || [];
		assetAccounts.value = fixed || [];
		equityAccounts.value = equity || [];
		assets.value = assetRows || [];
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
	editingDocstatus.value = null;
	submitError.value = "";
	cbuRate.value = null;
	rateError.value = "";
	dealLabel.value = "";
	detailOpen.value = false;
	createOpen.value = true;
	if (!payAccounts.value.length || !expAccounts.value.length || !assetAccounts.value.length) await loadOptions();
	await fetchExchangeRate();
	markFormPristine();
}

// P0-MONEY-2 / P0-MONEY-3. "Amend" is not an edit. `amend_*_entry` cancels the
// original voucher outright and posts a replacement in its place, and if the
// amount trips the maker-checker threshold `submit_or_route` leaves that
// replacement a DRAFT -- the original is gone from the ledger and nothing has
// taken its place until somebody approves. The only notice used to be a toast,
// fired after the save had already happened.
//
// A draft is deliberately NOT confirmed: editing one cancels nothing and posts
// nothing, and a dialog people learn to dismiss unread stops being a warning.
function amendConfirmationRequired(docstatus) {
	return docstatus === 1;
}

// The threshold cannot be named here. No whitelisted endpoint exposes it and the
// session does not carry it, so the approval clause is stated as a condition
// rather than as a prediction about this particular amount.
function confirmAmend(name) {
	return confirm({
		title: t("Amend a posted entry?"),
		body: t(
			"This cancels {name} and posts a replacement in its place. If the amount requires approval, the replacement stays a draft until it is approved — and until then the ledger is short by that amount.",
			{ name }
		),
		confirmLabel: t("Amend"),
		cancelLabel: t("Close"),
		danger: true,
	});
}

async function openEditFromDetail() {
	if (!detail.value?.name) return;
	if (amendConfirmationRequired(detail.value.docstatus) && !(await confirmAmend(detail.value.name))) return;
	if (!payAccounts.value.length || !expAccounts.value.length || !assetAccounts.value.length) await loadOptions();
	// Exclude the auto exchange-rounding line — it's a base-currency GL detail
	// (re-derived on save by fx_balance), never a user expense leg.
	// (Named accRows, not rows, to avoid shadowing the outer `rows` list ref
	// used below to look up the tender tag.)
	const accRows = (detail.value.accounts || []).filter((row) => !row.is_fx_rounding);
	const credit = accRows.find((row) => Number(row.credit_in_account_currency) > 0);
	const debits = accRows.filter((row) => Number(row.debit_in_account_currency) > 0);
	// journal_entry_detail doesn't carry the tender tag; pull it from the
	// already-loaded list row instead (list_bank_entries includes crm_deal).
	const listRow = rows.value.find((r) => r.name === detail.value.name);
	form.value = {
		posting_date: detail.value.posting_date || today,
		entry_kind: detail.value.entry_kind || "Expense",
		payee: detail.value.pay_to_recd_from || "",
		payment_from: credit?.account || "",
		exchange_rate: null,
		deal: listRow?.crm_deal || "",
		commercial_invoice: listRow?.commercial_invoice || "",
		import_truck: listRow?.import_truck || "",
		import_container: listRow?.import_container || "",
		// Entries booked before v82 carry no category; show the same fallback the
		// backend applies rather than an empty Select.
		import_category: listRow?.import_category || "Other",
		lines: debits.map((row) => ({
			id: ++lineSeq,
			account: row.account,
			amount: Number(row.debit_in_account_currency) || null,
			memo: row.user_remark || "",
			asset: row.asset || "",
		})),
	};
	ghost.value = newGhost();
	editingName.value = detail.value.name;
	editingDocstatus.value = detail.value.docstatus;
	submitError.value = "";
	cbuRate.value = null;
	rateError.value = "";
	dealLabel.value = "";
	ciLabel.value = "";
	// Skip the label round-trip when the picker itself is hidden (tender off).
	if (tenderOn.value && form.value.deal) await loadDealLabel(form.value.deal);
	if (importsOn.value && form.value.commercial_invoice) await loadCILabel(form.value.commercial_invoice);
	detailOpen.value = false;
	createOpen.value = true;
	await fetchExchangeRate();
	markFormPristine();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
	editingName.value = "";
	editingDocstatus.value = null;
}

function removeLine(idx) {
	form.value.lines.splice(idx, 1);
}

// Throw the form away without posting anything. This lived inside
// `submitCreate` under the label "Save & clear" — it saved nothing, and because
// the split button remembered the choice, the primary button then read
// "Save & clear" and discarded six typed lines on a single click. It is not a
// save mode (see composables/saveMode.js), it says what it does, and like every
// other destructive action on this screen it asks first.
async function clearForm() {
	if (formDirty.value) {
		const ok = await confirm({
			title: t("Discard unsaved changes?"),
			body: t("This clears the form without saving. The lines you entered will be lost."),
			danger: true,
			confirmLabel: t("Discard"),
			cancelLabel: t("Keep Editing"),
		});
		if (!ok) return;
	}
	submitError.value = "";
	resubmitWarning.value = false;
	const keepDate = form.value.posting_date;
	form.value = blankForm();
	form.value.posting_date = keepDate;
	ghost.value = newGhost();
	dealLabel.value = "";
	// blankForm() drops form.commercial_invoice, so the label has to go with it
	// — otherwise the next entry displays a CI it is not actually tagged with.
	ciLabel.value = "";
	await fetchExchangeRate();
	markFormPristine();
}

async function submitCreate(afterAction) {
	submitError.value = "";
	resubmitWarning.value = false;
	persistSaveMode(afterAction);

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
			asset: assetMode.value && l.asset ? l.asset : undefined,
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
	if (tenderOn.value && form.value.deal) payload.deal = form.value.deal;
	if (importsOn.value && form.value.commercial_invoice) {
		payload.commercial_invoice = form.value.commercial_invoice;
		if (form.value.import_truck) payload.import_truck = form.value.import_truck;
		if (form.value.import_container) payload.import_container = form.value.import_container;
		// Drives the cost component of the Import Expense the JE on_submit hook
		// mirrors; the backend falls back to "Other" when it is left blank.
		if (form.value.import_category) payload.import_category = form.value.import_category;
	}
	if (isCrossCurrency.value) {
		// `submit_expense_entry` wants base per 1 payment unit and does
		// `base_total = total_pay_amount * exchange_rate`. The operator typed the
		// rate in the direction the label showed them; fx.js is the only thing
		// that knows which direction that was.
		payload.exchange_rate = toLineRate(
			form.value.exchange_rate,
			fxBaseCur.value,
			payCurrency.value,
		);
	}

	submitting.value = true;
	try {
		const method = editingName.value
			? "stabler.api.money.amend_expense_entry"
			: "stabler.api.money.submit_expense_entry";
		const res = await call(
			method,
			editingName.value
				? { source_name: editingName.value, modified: detail.value?.modified, ...payload }
				: { ...payload, idempotency_key: intent.begin() },
		);
		intent.settle();

		load();
		// Maker-checker may route the expense to the approvals queue as a Draft.
		const pendingApproval = !!res?.pending_approval;

		if (editingName.value || afterAction === "close") {
			createOpen.value = false;
			editingName.value = "";
			editingDocstatus.value = null;
			if (res?.name) await openDetail(res.name);
			if (pendingApproval) toast.warning(t("Saved — pending approval before it posts."));
		} else if (afterAction === "new") {
			const keepDate = form.value.posting_date;
			form.value = blankForm();
			form.value.posting_date = keepDate;
			ghost.value = newGhost();
			dealLabel.value = "";
			if (pendingApproval) {
				toast.warning(t("Saved — pending approval before it posts."));
			} else {
				toast.success(t("Expense saved · {name}", { name: res?.name || "" }));
			}
			await fetchExchangeRate();
			// The saved entry is gone from the form, so the form has nothing left
			// to lose. Without this the dirty guard still thinks it does, and the
			// blank form would raise "Discard unsaved changes?" — on leaving the
			// page, and now also on Clear form. A dialog that fires when there is
			// nothing to discard is how operators learn to click through the one
			// that matters.
			markFormPristine();
		}
	} catch (err) {
		submitError.value = err?.message || t("Failed to submit expense.");
		resubmitWarning.value = true;
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
	createOpen.value = false;
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

// Read a saved expense back directly into the SAME form (view / edit / amend).
// P0-MONEY-2. A click on a list row used to land straight in the editor, and on
// a submitted voucher that editor's save runs the amend path -- `source.cancel()`
// on the original, then a replacement posted in its place (money.py). Nobody had
// asked for either. The read-only detail card below already exists and already
// offers a deliberate button, labelled "Amend" on a submitted entry, so the row
// click stops there and the person decides.
//
// Stated as "not a draft" rather than "is submitted" so it fails safe: a
// cancelled voucher -- which `openEditFromDetail` never checked for -- and a
// detail payload that arrives without a docstatus both stay read-only. Guessing
// "draft" wrong is the guess that has ledger consequences.
function opensReadOnly(docstatus) {
	return !(typeof docstatus === "number" && docstatus === 0);
}

async function openInForm(name) {
	createOpen.value = false;
	detailOpen.value = false;
	detailLoading.value = true;
	try {
		detail.value = await call("stabler.api.money.journal_entry_detail", { name });
		if (opensReadOnly(detail.value?.docstatus)) {
			detailOpen.value = true;
			return;
		}
		await openEditFromDetail(); // populates the form + sets amend/edit mode
	} catch (err) {
		detail.value = { error: err?.message || "Failed to load." };
		detailOpen.value = true; // fall back to the detail card to show the error
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
	<div v-if="!createOpen && !detailOpen" class="card">
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
						@click="openInForm(r.name)"
					>
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ formatDateTime(r.posting_date) }}</td>
						<td>
							<span class="badge bg-blue-lt">{{ r.entry_kind || t("Expense") }}</span>
						</td>
						<td style="max-width: 380px">
							<div class="d-flex align-items-center gap-1">
								<span class="text-truncate">{{ r.user_remark || "—" }}</span>
								<span
									v-if="r.crm_deal"
									class="badge bg-secondary-lt text-secondary flex-shrink-0"
									:title="t('Tender (Deal)')"
								>
									<i class="ti ti-briefcase me-1"></i>{{ r.crm_deal }}
								</span>
								<span
									v-if="r.commercial_invoice"
									class="badge bg-purple-lt text-purple flex-shrink-0 font-monospace"
									:title="t('Commercial Invoice')"
								>
									<i class="ti ti-file-invoice me-1"></i>{{ r.commercial_invoice }}
								</span>
							</div>
						</td>

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

	<!-- Detail page -->
	<div v-if="detailOpen" class="card">
		<div class="card-header">
			<button type="button" class="btn btn-sm btn-outline-secondary me-2" @click="closeDetail">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
			</button>
			<div class="card-title m-0 d-flex align-items-center gap-2">
				<span><i class="ti ti-receipt-2 me-1"></i>{{ t("Expense") }}</span>
				<!-- The row click now stops here instead of opening the editor, so this
				     card is where a person decides whether to touch a posted voucher.
				     It has to say which kind it is; the button labels alone did not. -->
				<StatusBadge
					v-if="detail && !detail.error"
					doctype="Journal Entry"
					:docstatus="detail.docstatus"
				/>
			</div>
		</div>
		<div class="card-body">
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
								<td>{{ a.account_name || a.account }}</td>
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

	<!-- Create / amend page -->
	<div v-if="createOpen" ref="modalEl" class="card">
		<div class="card-header">
			<button type="button" class="btn btn-sm btn-outline-secondary me-2" :disabled="submitting" @click="closeCreate">
				<i class="ti ti-arrow-left me-1"></i>{{ t("Back") }}
			</button>
			<div class="card-title m-0 d-flex align-items-center gap-2">
				<span><i class="ti ti-receipt-2 me-1"></i>{{ formTitle }}</span>
				<!-- Which document this is. Without it a draft and a posted voucher
				     being cancelled-and-replaced look exactly alike from in here. -->
				<StatusBadge
					v-if="editingName"
					doctype="Journal Entry"
					:docstatus="editingDocstatus"
				/>
			</div>
		</div>
		<div class="card-body p-3 d-flex flex-column gap-3">
					<div v-if="submitError" class="alert alert-danger mb-0">
						{{ submitError }}
						<div v-if="resubmitWarning" class="mt-2 small fw-bold">{{ t("The expense may already have been recorded. Open the expense list and check before submitting again — a repeat posts a second journal entry.") }}</div>
					</div>

					<!-- Panel A: Details (blue) -->
					<div class="card card-sm mb-0" style="border: 1.5px solid var(--tblr-blue, #206bc4); border-radius: 6px">
						<div class="card-header py-2 px-3 d-flex align-items-center gap-2" style="background: var(--tblr-blue-lt, #e9f0fb); border-bottom: 1px solid var(--tblr-blue-lt, #d0e0f7); border-radius: 5px 5px 0 0">
							<i class="ti ti-adjustments text-blue" style="font-size: 1rem"></i>
							<span class="fw-semibold text-blue small">{{ t("Details") }}</span>
						</div>
						<div class="card-body p-3">

					<div class="row g-2">
						<div class="col-md-3">
							<label class="form-label small">{{ t("Mode") }}</label>
							<div class="btn-group w-100" role="group">
								<input type="radio" class="btn-check" name="entry_kind" id="ek_expense" value="Expense" autocomplete="off" v-model="form.entry_kind">
								<label class="btn btn-outline-primary" for="ek_expense">{{ t("Expense") }}</label>
								<input type="radio" class="btn-check" name="entry_kind" id="ek_asset" value="Asset Purchase" autocomplete="off" v-model="form.entry_kind">
								<label class="btn btn-outline-primary" for="ek_asset">{{ t("Asset purchase") }}</label>
							</div>
						</div>
						<div class="col-md-3">
							<label class="form-label small">{{ t("Posting date") }}</label>
							<DateInput v-model="form.posting_date" required />
						</div>
						<div class="col-md-3">
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
						<!-- Exchange rate: inline, same row as Mode/Date/Pay from (cross-currency only) -->
						<div v-if="isCrossCurrency" class="col-md-3">
							<label class="form-label small">
								{{ fxBaseCur ? `1 ${fxBaseCur} =` : t("Rate") }}
							</label>
							<!-- The field is denominated in the OTHER side of the quote the
							     label states, never in the payment currency: the label says
							     "1 USD =" and what follows it is сўм. It carried
							     :currency="payCurrency" and the raw API rate, so a 12 953
							     сўм quote showed as "0.00" USD. Rates need more precision
							     than money does — formatRate's own ceiling is 6. -->
							<MoneyInput
								v-model="form.exchange_rate"
								:currency="fxCounterCur"
								:max-fraction-digits="6"
								:min="0"
								:language="user.language"
								:placeholder="fxCounterCur"
							/>
							<div v-if="cbuRate" class="text-secondary small mt-1">
								<i class="ti ti-building-bank" style="font-size: 0.75rem"></i>
								CBU: {{ fmtRate(cbuRate) }}<span v-if="rateDate"> · {{ formatDate(rateDate) }}</span>
							</div>
							<div v-if="rateError" class="text-danger small mt-1">
								<i class="ti ti-alert-triangle me-1"></i>{{ rateError }}
							</div>
						</div>
						<!-- Payee: shrinks to col-3 when no rate field; col-6 otherwise -->
						<div :class="isCrossCurrency ? 'col-md-6' : 'col-md-3'">
							<label class="form-label small">{{ t("Payee") }}</label>
							<input
								v-model="form.payee"
								type="text"
								class="form-control"
								:placeholder="t('Optional')"
							/>
						</div>
					</div>
					<!-- Tender (Deal) & Import CI pickers -->
					<div v-if="tenderOn || importsOn" class="row g-2 mt-0">
						<div v-if="tenderOn" class="col-md-4">
							<label class="form-label small">{{ t("Tender (Deal)") }}</label>
							<Typeahead
								:model-value="form.deal"
								:display="dealLabel"
								:search="searchDeals"
								:placeholder="t('Search a tender deal…')"
								@pick="pickDeal"
								@clear="clearDeal"
							>
								<template #option="{ item }">{{ item.label }}</template>
							</Typeahead>
						</div>
						<div v-if="importsOn" class="col-md-4">
							<label class="form-label small text-primary fw-semibold">
								<i class="ti ti-file-invoice me-1"></i>{{ t("Commercial Invoice") }}
							</label>
							<Typeahead
								:model-value="form.commercial_invoice"
								:display="ciLabel"
								:search="searchCommercialInvoices"
								:placeholder="t('Search commercial invoice…')"
								@pick="pickCI"
								@clear="clearCI"
							>
								<template #option="{ item }">
									<div class="fw-semibold font-monospace">{{ item.name }}</div>
									<div class="small text-secondary">{{ item.label }}</div>
								</template>
							</Typeahead>
						</div>
						<!-- Only meaningful once a CI is chosen: it labels the Import Expense
						     this entry becomes, and nothing is created without a CI. -->
						<div v-if="importsOn && form.commercial_invoice" class="col-md-4">
							<label class="form-label small">{{ t("Import expense category") }}</label>
							<select v-model="form.import_category" class="form-select">
								<option v-for="c in IMPORT_CATEGORIES" :key="c" :value="c">
									{{ t(c) }}
								</option>
							</select>
						</div>
					</div>
						</div><!-- /Panel A body -->

					</div><!-- /Panel A -->

					<!-- Panel B: Expense / Asset lines (amber) -->
					<div class="card card-sm mb-0" style="border: 1.5px solid var(--tblr-orange, #f76707); border-radius: 6px">
						<div class="card-header py-2 px-3 d-flex align-items-center gap-2" style="background: var(--tblr-orange-lt, #fff4e6); border-bottom: 1px solid var(--tblr-orange-lt, #ffd8a8); border-radius: 5px 5px 0 0">
							<i class="ti ti-list-details text-orange" style="font-size: 1rem"></i>
							<span class="fw-semibold text-orange small">
								{{ form.entry_kind === "Asset Purchase" ? t("Asset lines") : t("Expense lines") }}
							</span>
							<span class="ms-auto fw-bold font-monospace text-orange small">
								{{ formatMoney(totalAmount, payCurrency, user.language) }}
							</span>
						</div>
						<div class="card-body p-0">
					<div class="table-responsive">
						<table ref="linesTableEl" class="table table-vcenter card-table" @keydown="handleLineKeyDown">
							<thead>
								<tr>
									<th v-if="assetMode" style="min-width: 200px" class="text-uppercase text-secondary small">{{ t("Asset") }}</th>
									<th style="min-width: 240px" class="text-uppercase text-secondary small">{{ t("Account") }}</th>
									<th style="min-width: 160px" class="text-end text-uppercase text-secondary small">{{ t("Amount") }}</th>
									<th v-if="isCrossCurrency" class="text-end text-secondary" style="min-width: 120px; font-size: 0.8em">
										{{ baseCurrency }}
									</th>
									<th class="text-uppercase text-secondary small">{{ t("Memo") }}</th>
									<th class="w-1"></th>
								</tr>
							</thead>
							<SkeletonRows v-if="optionsLoading" :rows="3" :cols="(isCrossCurrency ? 5 : 4) + (assetMode ? 1 : 0)" />
							<tbody v-else>
								<!-- Real lines -->
								<tr v-for="(line, idx) in form.lines" :key="line.id">
									<td v-if="assetMode">
										<Typeahead
											v-model="line.asset"
											:search="searchAsset"
											:display="assetDisplay(line.asset)"
											:placeholder="t('Search an asset…')"
											open-on-focus
											@pick="(item) => pickAssetOnLine(line, item)"
											@clear="() => (line.asset = '')"
										>
											<template #option="{ item }">
												<span>{{ item.asset_name || item.name }}</span>
												<span v-if="item.status" class="ms-auto text-secondary small">{{ item.status }}</span>
											</template>
										</Typeahead>
									</td>
									<td>
										<Typeahead
											v-model="line.account"
											:search="searchLineAccount"
											:display="lineAccountDisplay(line.account)"
											:placeholder="t('Search account…')"
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
											class="form-control"
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
									<td v-if="assetMode">
										<Typeahead
											:model-value="''"
											:search="searchAsset"
											:display="''"
											:placeholder="t('Add an asset…')"
											open-on-focus
											@pick="(item) => materialAssetGhost(item)"
										>
											<template #option="{ item }">
												<span>{{ item.asset_name || item.name }}</span>
												<span v-if="item.status" class="ms-auto text-secondary small">{{ item.status }}</span>
											</template>
										</Typeahead>
									</td>
									<td>
										<Typeahead
											:model-value="''"
											:search="searchLineAccount"
											:display="''"
											:placeholder="t('Add a line…')"
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
										/>
									</td>
									<td v-if="isCrossCurrency"></td>
									<td>
										<input
											v-model="ghost.memo"
											type="text"
											class="form-control"
											:placeholder="t('Optional')"
										/>
									</td>
									<td></td>
								</tr>
							</tbody>
							<tfoot>
								<tr class="fw-bold">
									<td v-if="assetMode"></td>
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
					</div><!-- /table-responsive -->
						</div><!-- /Panel B body -->
					</div><!-- /Panel B -->
				</div><!-- /outer card-body -->
				<div class="card-footer d-flex align-items-center gap-2">
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
							<div class="dropdown-divider"></div>
							<a
								href="#"
								class="dropdown-item stbl-menu-item text-danger"
								@click.prevent="clearForm"
							>
								<i class="ti ti-eraser me-2"></i>{{ t("Clear form") }}
							</a>
						</div>
					</div>
				</div>
	</div>
</template>
