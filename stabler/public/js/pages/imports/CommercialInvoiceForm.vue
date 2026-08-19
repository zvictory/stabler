<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { accountLabel } from "../../composables/accounts.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { blockerText, cascadeRows, recordRoute } from "../../composables/deleteImpact.js";
import { buildAllocationPlan, rowCeiling } from "../../composables/piAllocation.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import CiLogisticsOverview from "./CiLogisticsOverview.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/commercial-invoices");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const form = ref(blankForm());
// True when the remaining-qty tracking data could not be fetched, so Smart Fill
// must not treat an empty remaining list as "fully shipped".
const piTrackingFailed = ref(false);

const transportData = ref(null);
const loadingTransport = ref(false);

async function fetchTransportCosts() {
	if (isCreate.value || !docName.value) {
		transportData.value = null;
		return;
	}
	loadingTransport.value = true;
	try {
		const res = await call("stabler.api.imports.ci_transport_costs", {
			commercial_invoice: docName.value,
		});
		transportData.value = res || null;
	} catch (err) {
		console.error("Failed to load transport costs", err);
		transportData.value = null;
	} finally {
		loadingTransport.value = false;
	}
}

// Fallback carton weight when a PI line carries no box_weight_kg.
const DEFAULT_BOX_WEIGHT_KG = 20;

const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];
const incotermOptions = computed(() => [
	{ value: "", label: t("Not set") },
	...INCOTERMS.map((i) => ({ value: i, label: i })),
]);

const currencies = ref([]);
const currencyOptions = computed(() =>
	currencies.value.map((c) => ({ value: c.name, label: c.name }))
);
const companyPOs = ref([]);
const costVisible = computed(() => {
	if (!isCreate.value) return form.value.docs_total !== null;
	return session.costVisible === true;
});
const canRollback = computed(() =>
	(session.roles || []).some((r) => ["Imports Manager", "System Manager", "Stabler Admin"].includes(r))
);

// Vendor categories for the per-line category dropdown
const lineCategories = ref([]);
const categoryOptions = computed(() =>
	lineCategories.value.map((c) => c.display_name || c.category_name).filter(Boolean)
);

function blankForm() {
	return {
		name: null,
		modified: null,
		company: null,
		supplier: "",
		supplier_name: "",
		custom_proforma_invoice: "",
		ci_number: "",
		ci_date: "",
		currency: "USD",
		import_pi_group: "",
		status: "BOOKED",
		incoterm: "CIF",
		incoterm_location: "",
		vessel: "",
		voyage: "",
		bl_number: "",
		port_of_loading: "",
		port_of_discharge: "",
		eta_transit_port: "",
		etd: "",
		eta: "",
		atd: "",
		ata: "",
		total_boxes: 0,
		total_kg: 0,
		agreed_total: 0,
		docs_total: null,
		cash_difference: null,
		customs_fee: 0,
		customs_fee_override: null,
		customs_fee_off_hours: 0,
		allowed_transitions: [],
		items: [],
		po_links: [],
		containers: [],
		trucks: [],
		customs_declarations: [],
		packing_summary: {
			status: "Incomplete",
			container_count: 0,
			containers_with_items: 0,
			expected_items: [],
			reconciliation: [],
		},
		grn: null,
		ci_advance_share: null,
	};
}

const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100;

function rowAmount(row) {
	return (Number(row.qty) || 0) * (Number(row.rate) || 0);
}
function rowDocsAmount(row) {
	return (Number(row.qty) || 0) * (Number(row.docs_price) || 0);
}

// Same normalisation the backend uses (`_imports_rules.norm_key`): collapse
// runs of whitespace, trim, upper-case. "Whole leg" and "WHOLE  LEG" are the
// same contract line; comparing the raw text invents 40 phantom mismatches.
const normKey = (v) => String(v ?? "").replace(/\s+/g, " ").trim().toUpperCase();
const round4 = (n) => Math.round((Number(n) || 0) * 1e4) / 1e4;

const itemsAgreedTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowAmount(r), 0));
const itemsDocsTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowDocsAmount(r), 0));
const itemsCashDiff = computed(() => itemsAgreedTotal.value - itemsDocsTotal.value);
const costOverviewData = ref(null);
const loadingCostOverview = ref(false);
const discrepancyData = ref(null);
const loadingDiscrepancies = ref(false);

// This CI's share of the PI advance — read-only, one row per source PI. The
// backend gates it behind `_cost_visible()`, so a null here means either "no
// cost access" or "no source PI"; both render nothing.
const advanceShare = computed(() => {
	if (!costVisible.value) return null;
	const s = form.value.ci_advance_share;
	return s && (s.sources || []).length ? s : null;
});

// "Applied" belongs to the posted branch alone — a planned figure read as booked
// money is the one real risk this card carries.
const advanceShareState = computed(() => {
	const state = advanceShare.value?.state || "planned";
	return state.charAt(0).toUpperCase() + state.slice(1);
});

const advanceShareTotal = computed(() => {
	const s = advanceShare.value;
	if (!s) return 0;
	if (s.state === "posted") return s.advance_posted;
	if (s.state === "reserved") return s.advance_reserved;
	return s.advance_planned;
});

const advanceShareNote = computed(() => {
	const s = advanceShare.value;
	if (!s) return "";
	if (s.state === "posted") return t("Advance applied to this CI");
	if (s.state === "reserved") return t("Advance reserved for this CI");
	return t("Advance planned for this CI");
});

function advanceShareRowAmount(row) {
	const s = advanceShare.value;
	if (!s) return 0;
	if (s.state === "posted") return row.posted;
	if (s.state === "reserved") return row.reserved;
	return row.planned;
}

const containerCostMap = computed(() => {
	const map = {};
	if (!costOverviewData.value || !costOverviewData.value.by_container) return map;
	for (const c of costOverviewData.value.by_container) {
		map[c.container] = c;
	}
	return map;
});

// ---------------------------------------------------------------------------
// Containers & trucks — link an existing record, or create a real one. Both
// paths persist: the lists below are `get_commercial_invoice`'s side-loads, so
// anything that is not written to the database disappears on the next load().
// ---------------------------------------------------------------------------
const newContainerNumber = ref("");
const newTruckNumber = ref("");
const linkingContainer = ref(false);
const linkingTruck = ref(false);

async function searchContainers(q) {
	if (isCreate.value) return [];
	try {
		const res = await importsApi.listImportContainers({
			company: activeCompany.value,
			search: q || "",
			limit_page_length: 20,
		});
		return (res?.rows || []).filter((r) => r.commercial_invoice !== docName.value);
	} catch (err) {
		console.error("Container search failed", err);
		return [];
	}
}

async function searchTrucks(q) {
	if (isCreate.value) return [];
	try {
		const res = await importsApi.listImportTrucks({
			company: activeCompany.value,
			search: q || "",
			limit_page_length: 20,
		});
		const linked = new Set((form.value.trucks || []).map((r) => r.name));
		return (res?.rows || []).filter((r) => !linked.has(r.name));
	} catch (err) {
		console.error("Truck search failed", err);
		return [];
	}
}

async function linkContainer(row) {
	if (!row?.name || linkingContainer.value) return;
	// Stealing a container from another CI would silently move its cost lines.
	if (row.commercial_invoice && row.commercial_invoice !== docName.value) {
		toast.error(
			t("{container} is already linked to {ci}. Unlink it there first.", {
				container: row.container_number || row.name,
				ci: row.commercial_invoice,
			})
		);
		return;
	}
	linkingContainer.value = true;
	try {
		await importsApi.updateImportContainer({
			name: row.name,
			values: { commercial_invoice: docName.value },
		});
		await loadDoc();
		toast.success(t("Container linked."));
	} catch (err) {
		toast.error(err);
	} finally {
		linkingContainer.value = false;
	}
}

async function createContainer() {
	const number = (newContainerNumber.value || "").trim();
	if (!number || linkingContainer.value) return;
	linkingContainer.value = true;
	try {
		await importsApi.createImportContainer({
			company: activeCompany.value,
			values: { container_number: number, commercial_invoice: docName.value },
		});
		newContainerNumber.value = "";
		await loadDoc();
		toast.success(t("Container created and linked."));
	} catch (err) {
		toast.error(err);
	} finally {
		linkingContainer.value = false;
	}
}

async function unlinkContainer(row) {
	if (!row?.name || linkingContainer.value) return;
	const ok = await confirm({
		title: t("Unlink this container?"),
		body: t("{container} stays in the system but is no longer part of this commercial invoice.", {
			container: row.container_number || row.name,
		}),
		confirmLabel: t("Unlink"),
	});
	if (!ok) return;
	linkingContainer.value = true;
	try {
		await importsApi.updateImportContainer({ name: row.name, values: { commercial_invoice: "" } });
		await loadDoc();
		toast.success(t("Container unlinked."));
	} catch (err) {
		toast.error(err);
	} finally {
		linkingContainer.value = false;
	}
}

async function linkTruck(row) {
	if (!row?.name || linkingTruck.value) return;
	linkingTruck.value = true;
	try {
		await importsApi.updateImportTruck({
			name: row.name,
			values: { commercial_invoice: docName.value },
		});
		await loadDoc();
		toast.success(t("Truck linked."));
	} catch (err) {
		toast.error(err);
	} finally {
		linkingTruck.value = false;
	}
}

async function createTruck() {
	const number = (newTruckNumber.value || "").trim();
	if (!number || linkingTruck.value) return;
	linkingTruck.value = true;
	try {
		await importsApi.createImportTruck({
			company: activeCompany.value,
			values: { truck_number: number, commercial_invoice: docName.value },
		});
		newTruckNumber.value = "";
		await loadDoc();
		toast.success(t("Truck created and linked."));
	} catch (err) {
		toast.error(err);
	} finally {
		linkingTruck.value = false;
	}
}

async function unlinkTruck(row) {
	if (!row?.name || linkingTruck.value) return;
	const ok = await confirm({
		title: t("Unlink this truck?"),
		body: t("{truck} stays in the system but is no longer part of this commercial invoice.", {
			truck: row.truck_number || row.name,
		}),
		confirmLabel: t("Unlink"),
	});
	if (!ok) return;
	linkingTruck.value = true;
	try {
		await importsApi.updateImportTruck({ name: row.name, values: { commercial_invoice: "" } });
		await loadDoc();
		toast.success(t("Truck unlinked."));
	} catch (err) {
		toast.error(err);
	} finally {
		linkingTruck.value = false;
	}
}

// ---------------------------------------------------------------------------
// Import expenses — every row is a real `Import Expense`, and every save moves
// real money: the backend posts a Bank Entry out of the selected cash desk.
// ---------------------------------------------------------------------------
const expenses = ref([]);
const loadingExpenses = ref(false);
const showExpenseModal = ref(false);
const savingExpense = ref(false);
const payAccounts = ref([]);
const expenseAccounts = ref([]);
const loadingAccounts = ref(false);

function blankExpenseForm() {
	return {
		category: "Handling",
		expense_date: new Date().toISOString().slice(0, 10),
		description: "",
		invoice_reference: "",
		amount: 0,
		paid_from_account: "",
		expense_account: "",
		container: "",
		truck: "",
	};
}
const expenseForm = ref(blankExpenseForm());

// Mirrors the `category` Select options on the `Import Expense` doctype.
const expenseCategoryOptions = [
	"Border Crossing",
	"Transport",
	"Handling",
	"Storage",
	"Insurance",
	"Documentation",
	"Customs",
	"Other",
].map((value) => ({ value, label: t(value) }));

// Tag targets come from the invoice's own containers/trucks — an expense can
// only be attributed to something already linked to this CI.
const expenseContainerOptions = computed(() =>
	(form.value.containers || []).map((c) => ({
		value: c.name,
		label: c.container_number || c.name,
	}))
);
const expenseTruckOptions = computed(() =>
	(form.value.trucks || []).map((tr) => ({
		value: tr.name,
		label: tr.truck_number || tr.name,
	}))
);

const expensePayAccount = computed(
	() => payAccounts.value.find((a) => a.name === expenseForm.value.paid_from_account) || null
);
const expenseDebitAccount = computed(
	() => expenseAccounts.value.find((a) => a.name === expenseForm.value.expense_account) || null
);
// The currency is the cash desk's, never a free choice — `submit_expense_entry`
// rejects a line whose expense account is in a different currency.
const expenseCurrency = computed(() => expensePayAccount.value?.account_currency || "");
const expenseCurrencyMismatch = computed(
	() =>
		!!expensePayAccount.value &&
		!!expenseDebitAccount.value &&
		expenseDebitAccount.value.account_currency !== expensePayAccount.value.account_currency
);
const canSaveExpense = computed(
	() =>
		!!expenseForm.value.paid_from_account &&
		!!expenseForm.value.expense_account &&
		Number(expenseForm.value.amount) > 0 &&
		!expenseCurrencyMismatch.value
);

// One line per currency: a single sum would add UZS to USD.
const expenseTotals = computed(() => {
	const map = new Map();
	for (const e of expenses.value) {
		const ccy = e.currency || "";
		map.set(ccy, (map.get(ccy) || 0) + (Number(e.amount) || 0));
	}
	return [...map.entries()].map(([currency, amount]) => ({ currency, amount }));
});

async function fetchExpenses() {
	if (isCreate.value || !docName.value) {
		expenses.value = [];
		return;
	}
	loadingExpenses.value = true;
	try {
		const res = await importsApi.listImportExpenses({
			company: activeCompany.value,
			commercial_invoice: docName.value,
			limit_page_length: 100,
		});
		expenses.value = res?.rows || [];
	} catch (err) {
		expenses.value = [];
		toast.error(err);
	} finally {
		loadingExpenses.value = false;
	}
}

// Reloaded on every open so the cash-desk balances in the picker are current.
async function loadAccountOptions() {
	loadingAccounts.value = true;
	try {
		const [pay, exp] = await Promise.all([
			call("stabler.api.money.bank_cash_accounts", { company: activeCompany.value }),
			call("stabler.api.money.expense_accounts", { company: activeCompany.value }),
		]);
		payAccounts.value = Array.isArray(pay) ? pay : [];
		expenseAccounts.value = Array.isArray(exp) ? exp : [];
	} catch (err) {
		toast.error(err);
	} finally {
		loadingAccounts.value = false;
	}
}

async function openExpenseModal() {
	expenseForm.value = blankExpenseForm();
	showExpenseModal.value = true;
	await loadAccountOptions();
}

function closeExpenseModal() {
	showExpenseModal.value = false;
}

async function saveImportExpense() {
	if (savingExpense.value || !canSaveExpense.value) return;
	savingExpense.value = true;
	try {
		const res = await importsApi.createImportExpense({
			company: activeCompany.value,
			values: {
				commercial_invoice: docName.value,
				category: expenseForm.value.category,
				expense_date: expenseForm.value.expense_date,
				description: expenseForm.value.description,
				invoice_reference: expenseForm.value.invoice_reference,
				amount: Number(expenseForm.value.amount) || 0,
				currency: expenseCurrency.value,
				paid_from_account: expenseForm.value.paid_from_account,
				expense_account: expenseForm.value.expense_account,
				container: expenseForm.value.container || "",
				truck: expenseForm.value.truck || "",
			},
		});
		closeExpenseModal();
		if (res?.pending_approval) {
			toast.info(t("Expense saved and sent for approval — no money has left the cash desk yet."));
		} else if (res?.journal_entry) {
			toast.success(t("Expense recorded. Journal Entry {je} posted.", { je: res.journal_entry }));
		} else {
			toast.success(t("Expense recorded."));
		}
		await Promise.all([
			fetchExpenses(),
			fetchLandedCostUzs(),
			fetchTransportCosts(),
			fetchCostOverview(),
		]);
	} catch (err) {
		toast.error(err);
	} finally {
		savingExpense.value = false;
	}
}

// ---------------------------------------------------------------------------
// Landed cost. A cash-paid expense can be capitalized into the containers'
// cost lines. The backend is the authority — `set_expense_landed_cost` re-runs
// the cost-visibility, valuation-account, currency and already-vouchered
// checks; this screen only picks the component and reports what came back.
// ---------------------------------------------------------------------------
const showLandedCostModal = ref(false);
const landedCostExpense = ref(null);
const landedCostComponent = ref("Other");
// Which expense currently has a call in flight — a page-wide flag would grey
// out every row while a single one is being capitalized.
const landedCostBusy = ref("");

// Mirrors the `cost_component` Select on the `Container Cost Line` doctype;
// `_resolve_expense_cost_component` validates the value against that meta.
const costComponentOptions = [
	"Freight",
	"Iran Customs Duty",
	"Iran Port & THC",
	"Iran Storage",
	"Iran Demurrage",
	"Iran Inspection",
	"Cross-Border Transport",
	"Insurance",
	"Certificate",
	"Uzbekistan Customs Duty",
	"Uzbekistan Port Handling",
	"Customs Clearance Fee",
	"Other",
].map((value) => ({ value, label: t(value) }));

function openLandedCostModal(exp) {
	landedCostExpense.value = exp;
	landedCostComponent.value = exp.cost_component || "Other";
	showLandedCostModal.value = true;
}

function closeLandedCostModal() {
	showLandedCostModal.value = false;
	landedCostExpense.value = null;
}

async function confirmLandedCost() {
	const exp = landedCostExpense.value;
	if (!exp || landedCostBusy.value) return;
	landedCostBusy.value = exp.name;
	try {
		const res = await importsApi.setExpenseLandedCost(exp.name, landedCostComponent.value);
		closeLandedCostModal();
		// Containers whose component is already vouchered are skipped, not failed.
		// Reporting only the success would overstate what actually landed.
		for (const warning of res?.warnings || []) toast.warning(warning);
		toast.success(
			t("Expense capitalized on {count} container cost line(s).", {
				count: (res?.cost_lines || []).length,
			})
		);
		await Promise.all([fetchExpenses(), fetchLandedCostUzs(), fetchTransportCosts(), fetchCostOverview()]);
	} catch (err) {
		toast.error(err);
	} finally {
		landedCostBusy.value = "";
	}
}

async function removeLandedCost(exp) {
	if (landedCostBusy.value) return;
	const ok = await confirm({
		title: t("Remove from landed cost"),
		body: t("The container cost lines created from {name} will be deleted. The expense itself stays.", {
			name: exp.name,
		}),
		danger: true,
		confirmLabel: t("Remove"),
		cancelLabel: t("Cancel"),
	});
	if (!ok) return;
	landedCostBusy.value = exp.name;
	try {
		const res = await importsApi.clearExpenseLandedCost(exp.name);
		toast.success(
			t("Expense removed from the landed cost ({count} cost line(s) deleted).", {
				count: res?.cost_lines_removed || 0,
			})
		);
		await Promise.all([fetchExpenses(), fetchLandedCostUzs(), fetchTransportCosts(), fetchCostOverview()]);
	} catch (err) {
		toast.error(err);
	} finally {
		landedCostBusy.value = "";
	}
}

// ---------------------------------------------------------------------------
// UZS landed cost — computed server-side from the CI's real cost lines.
// ---------------------------------------------------------------------------
// Null until the server tells us the real rate. Seeding a number here would put
// a made-up rate into every landed cost figure below before the first response
// ever arrives — and it would look exactly like a real one.
const usdToUzsRate = ref(null);
const allocationMethod = ref("By Weight");
// The four branches `calculate_ci_landed_cost_uzs` actually recognises.
const allocationOptions = [
	{ value: "By Weight", label: t("By weight") },
	{ value: "By Value", label: t("By value") },
	{ value: "By Quantity", label: t("By quantity") },
	{ value: "Equal", label: t("Split equally") },
];
const landedCostUzs = ref(null);
const loadingLandedCost = ref(false);
let landedCostTimer = null;

async function fetchLandedCostUzs() {
	if (isCreate.value || !docName.value) {
		landedCostUzs.value = null;
		return;
	}
	// A blank/zero box means "you decide" — the server then resolves the CBU rate
	// for the CI's own currency pair on its CI date.
	const rate = Number(usdToUzsRate.value) || 0;
	loadingLandedCost.value = true;
	try {
		const res = await importsApi.calculateCiLandedCostUzs(
			docName.value,
			rate > 0 ? rate : null,
			allocationMethod.value
		);
		landedCostUzs.value = res;
		// Show what was actually used, without re-triggering the watch: writing the
		// same value back is a no-op for Vue, and a different one is the server
		// correcting us, which deserves exactly one more render, not a loop.
		if (res?.exchange_rate && res.rate_source !== "manual") {
			usdToUzsRate.value = Number(res.exchange_rate);
		}
	} catch (err) {
		landedCostUzs.value = null;
		console.error("Failed to load UZS landed cost", err);
	} finally {
		loadingLandedCost.value = false;
	}
}

watch([usdToUzsRate, allocationMethod], () => {
	clearTimeout(landedCostTimer);
	landedCostTimer = setTimeout(fetchLandedCostUzs, 400);
});

// No rate → nothing below it is computable. A table of zeros would read as
// "these costs are zero", which is a different and false statement.
const landedCostRateMissing = computed(() => landedCostUzs.value?.rate_source === "missing");
const uzsLandedTableItems = computed(() => landedCostUzs.value?.items || []);
const totalUzsLandedCostSum = computed(() => Number(landedCostUzs.value?.total_landed_uzs) || 0);
const totalExtraUzs = computed(() => Number(landedCostUzs.value?.total_extra_uzs) || 0);
const landedTotalKg = computed(() =>
	uzsLandedTableItems.value.reduce((s, i) => s + (Number(i.qty_kg) || 0), 0)
);
const avgUzsLandedRatePerKg = computed(() =>
	landedTotalKg.value > 0 ? totalUzsLandedCostSum.value / landedTotalKg.value : 0
);

async function fetchCostOverview() {
	if (isCreate.value || !docName.value) {
		costOverviewData.value = null;
		return;
	}
	loadingCostOverview.value = true;
	try {
		costOverviewData.value = await call("stabler.api.imports.ci_cost_overview", {
			commercial_invoice: docName.value,
		});
	} catch (e) {
		console.error("Failed to load cost overview", e);
		costOverviewData.value = null;
	} finally {
		loadingCostOverview.value = false;
	}
}

// Hand-linking transport/service bills to this CI (W2). The panel is
// on-demand and company-wide (`unlinked_transport_bills` ignores the CI's own
// company scoping only insofar as it filters by it server-side) — nothing
// fetches until the user asks, and a `configured:false` or permission failure
// (no cost visibility) hides the whole panel rather than showing an error.
const unlinkedBillsRequested = ref(false);
const unlinkedBillsHidden = ref(false);
// Non-empty only when the server judged the session user able to fix the gap
// itself (an admin-only setting). Everyone else keeps the silent hide.
const unlinkedBillsNotConfigured = ref("");
const loadingUnlinkedBills = ref(false);
const unlinkedBillsResult = ref(null);
const selectedUnlinkedBills = ref([]);
const linkingSelected = ref(false);
const linkResults = ref([]);

const unlinkedBillRows = computed(() => unlinkedBillsResult.value?.rows || []);
const allUnlinkedSelected = computed(
	() => unlinkedBillRows.value.length > 0 && selectedUnlinkedBills.value.length === unlinkedBillRows.value.length
);

async function fetchUnlinkedBills({ clearResults = false } = {}) {
	if (isCreate.value || !docName.value) return;
	if (clearResults) linkResults.value = [];
	loadingUnlinkedBills.value = true;
	try {
		const res = await importsApi.unlinkedTransportBills(docName.value);
		unlinkedBillsResult.value = res;
		unlinkedBillsRequested.value = true;
		// Silent, not an error state: unconfigured means the feature is off for
		// this company and the panel must render nothing at all (C4).
		unlinkedBillsHidden.value = !res?.configured;
		unlinkedBillsNotConfigured.value = res?.configured ? "" : res?.reason || "";
		selectedUnlinkedBills.value = selectedUnlinkedBills.value.filter((n) =>
			(res?.rows || []).some((r) => r.name === n)
		);
	} catch (e) {
		// Most likely a cost-visibility permission failure — fail quietly, no
		// red banner, per the masking rule the rest of this page follows.
		console.error("Failed to load unlinked bills", e);
		unlinkedBillsResult.value = null;
		unlinkedBillsRequested.value = true;
		unlinkedBillsHidden.value = true;
		unlinkedBillsNotConfigured.value = "";
	} finally {
		loadingUnlinkedBills.value = false;
	}
}

function toggleUnlinkedBill(name, on) {
	const set = new Set(selectedUnlinkedBills.value);
	if (on) set.add(name);
	else set.delete(name);
	selectedUnlinkedBills.value = Array.from(set);
}

function toggleAllUnlinkedBills(on) {
	selectedUnlinkedBills.value = on ? unlinkedBillRows.value.map((r) => r.name) : [];
}

async function linkSelectedBills() {
	if (!selectedUnlinkedBills.value.length || linkingSelected.value) return;
	linkingSelected.value = true;
	const results = [];
	for (const name of selectedUnlinkedBills.value) {
		try {
			await importsApi.setBillImportRefs({ purchase_invoice: name, commercial_invoice: docName.value });
			results.push({ name, ok: true });
		} catch (e) {
			results.push({ name, ok: false, message: e?.message || t("Failed to link.") });
		}
	}
	linkResults.value = results;
	selectedUnlinkedBills.value = [];
	linkingSelected.value = false;
	// Re-fetch, never mutate optimistically — the CI's own cost figures always,
	// and the candidate panel only if it is actually on screen (it must stay
	// on-demand, not spring open from an unrelated action).
	const refetches = [fetchCostOverview()];
	if (unlinkedBillsRequested.value) refetches.push(fetchUnlinkedBills());
	await Promise.all(refetches);
}

const unlinkingBill = ref(null);

// What the already-fetched data tells us without another round trip. Both
// checks mirror gates `clear_bill_import_refs` also enforces server-side —
// this is a hint to greyed-out the button, never the actual gate. Whether the
// bill is already vouchered into a Landed Cost Voucher is NOT knowable from
// this data, so it is deliberately absent here: the button stays enabled and
// the server's refusal reaches the user verbatim.
function billUnlinkBlockedReason(bill) {
	if (bill.custom_import_expense) {
		return t("Raised by the Import Expense automation — cannot be unlinked here.");
	}
	if (form.value.supplier && bill.supplier === form.value.supplier) {
		return t("This is the goods invoice of this Commercial Invoice — its link cannot be cleared here.");
	}
	return "";
}

async function unlinkBill(bill) {
	if (unlinkingBill.value) return;
	unlinkingBill.value = bill.name;
	try {
		await importsApi.clearBillImportRefs(bill.name);
		toast.success(t("{bill} unlinked.", { bill: bill.name }));
		const refetches = [fetchCostOverview()];
		if (unlinkedBillsRequested.value) refetches.push(fetchUnlinkedBills());
		await Promise.all(refetches);
	} catch (e) {
		toast.error(e?.message || t("Failed to unlink the bill."));
	} finally {
		unlinkingBill.value = null;
	}
}

// ---------------------------------------------------------------------------
// Transport Purchase Invoices (Linked to CI & Landed Cost)
// ---------------------------------------------------------------------------
const transportInvoicesData = ref(null);
const loadingTransportInvoices = ref(false);

const showTransportModal = ref(false);
const transportModalTab = ref("existing"); // "existing" | "new"
const linkableInvoices = ref([]);
const loadingLinkableInvoices = ref(false);
const linkableSearch = ref("");
const linkingInvoiceName = ref(null);

const newTransportForm = ref({
	supplier: "",
	supplier_name: "",
	amount: 0,
	currency: "USD",
	bill_no: "",
	posting_date: "",
});
const creatingTransportInvoice = ref(false);

async function fetchTransportInvoices() {
	if (isCreate.value || !docName.value) {
		transportInvoicesData.value = null;
		return;
	}
	loadingTransportInvoices.value = true;
	try {
		const res = await call("stabler.api.imports.get_ci_transport_invoices", {
			commercial_invoice: docName.value,
		});
		transportInvoicesData.value = res || null;
	} catch (err) {
		console.error("Failed to load transport invoices", err);
		transportInvoicesData.value = null;
	} finally {
		loadingTransportInvoices.value = false;
	}
}

async function openTransportModal(tab = "existing") {
	transportModalTab.value = tab;
	showTransportModal.value = true;
	newTransportForm.value = {
		supplier: "",
		supplier_name: "",
		amount: 0,
		currency: form.value.currency || "USD",
		bill_no: "",
		posting_date: new Date().toISOString().slice(0, 10),
	};
	if (tab === "existing") {
		await fetchLinkableInvoices();
	}
}

function closeTransportModal() {
	showTransportModal.value = false;
	linkableInvoices.value = [];
	linkableSearch.value = "";
}

async function fetchLinkableInvoices() {
	loadingLinkableInvoices.value = true;
	try {
		const res = await call("stabler.api.imports.list_linkable_transport_invoices", {
			company: activeCompany.value,
			commercial_invoice: docName.value,
			search: linkableSearch.value || undefined,
		});
		linkableInvoices.value = res || [];
	} catch (err) {
		toast.error(err?.message || t("Could not load linkable invoices"));
		linkableInvoices.value = [];
	} finally {
		loadingLinkableInvoices.value = false;
	}
}

async function handleLinkInvoice(inv) {
	linkingInvoiceName.value = inv.name;
	try {
		await call("stabler.api.imports.link_transport_purchase_invoice", {
			commercial_invoice: docName.value,
			purchase_invoice: inv.name,
		});
		toast.success(t("Transport invoice {name} linked to CI.", { name: inv.bill_no || inv.name }));
		await Promise.all([
			fetchTransportInvoices(),
			fetchCostOverview(),
			fetchTransportCosts(),
			fetchLandedCostUzs(),
		]);
		closeTransportModal();
	} catch (err) {
		toast.error(err?.message || t("Failed to link invoice"));
	} finally {
		linkingInvoiceName.value = null;
	}
}

function pickTransportSupplier(item) {
	newTransportForm.value.supplier = item.name;
	newTransportForm.value.supplier_name = item.supplier_name || item.name;
}

async function handleCreateTransportInvoice() {
	if (!newTransportForm.value.supplier) {
		toast.error(t("Supplier is required"));
		return;
	}
	if (!newTransportForm.value.amount || Number(newTransportForm.value.amount) <= 0) {
		toast.error(t("Amount must be greater than 0"));
		return;
	}
	creatingTransportInvoice.value = true;
	try {
		const res = await call("stabler.api.imports.create_transport_purchase_invoice", {
			commercial_invoice: docName.value,
			supplier: newTransportForm.value.supplier,
			amount: newTransportForm.value.amount,
			currency: newTransportForm.value.currency,
			bill_no: newTransportForm.value.bill_no || undefined,
			posting_date: newTransportForm.value.posting_date || undefined,
		});
		toast.success(t("Transport invoice {name} created and linked.", { name: res.bill_no || res.name }));
		await Promise.all([
			fetchTransportInvoices(),
			fetchCostOverview(),
			fetchTransportCosts(),
			fetchLandedCostUzs(),
		]);
		closeTransportModal();
	} catch (err) {
		toast.error(err?.message || t("Failed to create transport invoice"));
	} finally {
		creatingTransportInvoice.value = false;
	}
}

async function fetchDiscrepancies() {
	if (isCreate.value || !docName.value || !activeCompany.value) {
		discrepancyData.value = null;
		return;
	}
	loadingDiscrepancies.value = true;
	try {
		discrepancyData.value = await call("stabler.api.imports.get_ci_pi_discrepancies", {
			company: activeCompany.value,
			ci: docName.value,
		});
	} catch (e) {
		console.error("Failed to load discrepancies", e);
		discrepancyData.value = null;
	} finally {
		loadingDiscrepancies.value = false;
	}
}

const discrepancyRowMap = computed(() => {
	const map = {};
	if (!discrepancyData.value || !discrepancyData.value.rows) return map;
	for (const r of discrepancyData.value.rows) {
		if (r.row_name) map[r.row_name] = r;
		if (r.idx !== undefined) map[`idx_${r.idx}`] = r;
	}
	return map;
});

function itemPriceValidation(row) {
	if (!row) return null;
	const match = (row.name && discrepancyRowMap.value[row.name]) ||
		(row.idx && discrepancyRowMap.value[`idx_${row.idx}`]);

	if (!match || !match.diffs || !match.diffs.length) {
		return {
			hasDiff: false,
			agreedPrice: row.rate,
		};
	}

	const priceDiff = match.diffs.find((d) => d.code === "price_agreed" || d.code === "price_docs");
	if (!priceDiff) {
		return {
			hasDiff: false,
			agreedPrice: row.rate,
		};
	}

	const piPrices = priceDiff.pi_value ? (Array.isArray(priceDiff.pi_value) ? priceDiff.pi_value : [priceDiff.pi_value]) : [];
	const mainAgreed = piPrices[0] !== undefined ? piPrices[0] : row.rate;
	const diffAmount = (Number(row.rate || 0) - Number(mainAgreed || 0)) * (Number(row.qty) || 0);

	return {
		hasDiff: true,
		code: priceDiff.code,
		label: priceDiff.label ? t(priceDiff.label) : t("Price differs from contract"),
		mainAgreed,
		piPrices,
		diffAmount,
		tooltip: piPrices.length ? `${t("contract")}: ${piPrices.join(" / ")}` : null,
	};
}

function itemLandedCostPerKg(row) {
	const agreedRate = Number(row.rate) || 0;
	const transPerKg = costOverviewData.value?.operational?.per_kg || 0;
	return round4(agreedRate + transPerKg);
}

function getContainerGateInDiff(cnt) {
	const gateIn = cnt.gate_in_date;
	if (!gateIn) return null;
	const decl = (form.value.customs_declarations || []).find((d) => d.container === cnt.name || d.name === cnt.customs_declaration);
	const declDate = decl?.declaration_date || decl?.creation;
	if (declDate) {
		return { status: "ok", text: `${formatDate(gateIn)} → ${formatDate(declDate)}` };
	}
	const gDate = new Date(gateIn);
	const now = new Date();
	const diffDays = Math.max(0, Math.floor((now - gDate) / 86400000));
	return { status: "overdue", text: `${formatDate(gateIn)} → ${t("not submitted")}`, days: diffDays };
}

const priceDiscrepancyItemCount = computed(() => {
	return (form.value.items || []).filter((r) => {
		const val = itemPriceValidation(r);
		return val && val.hasDiff;
	}).length;
});

async function loadLineCategories() {
	if (!form.value.supplier) {
		lineCategories.value = [];
		return;
	}
	try {
		lineCategories.value = await call("stabler.api.imports.list_vendor_categories", {
			company: activeCompany.value,
			vendor: form.value.supplier,
		});
	} catch (_err) {
		lineCategories.value = [];
	}
}

async function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q || "",
		limit: 20,
		supplier_group_scope: "imports",
	});
}
function pickSupplier(item) {
	form.value.supplier = item.name;
	form.value.supplier_name = item.supplier_name || item.name;
	loadLineCategories();
}

const itemsList = ref([]);
async function loadItemsList() {
	try {
		itemsList.value = await call("stabler.api.inventory.list_items", { limit: 500 });
	} catch (_) {
		itemsList.value = [];
	}
}
function onItemSelect(row) {
	const found = itemsList.value.find((i) => (i.item_code || i.name) === row.item);
	if (found) {
		if (!row.description) row.description = found.item_name || "";
		if (!row.uom) row.uom = found.stock_uom || "Kg";
	}
}

function addItem() {
	form.value.items.push({
		category: "",
		item: "",
		item_name: "",
		description: "",
		hs_code: "",
		boxes: 0,
		box_weight_kg: 20,
		qty: 0,
		uom: "Kg",
		rate: 0,
		docs_price: 0,
	});
}
function removeItem(i) {
	form.value.items.splice(i, 1);
}

function onBoxesOrWeightInput(row) {
	if (!row._qtyManual) {
		row.qty = round2((Number(row.boxes) || 0) * (Number(row.box_weight_kg) || 0));
	}
}
function onQtyInput(row) {
	row._qtyManual = true;
}

// ---- Multi-PI Smart Fill Modal State ----
const multiPiModalOpen = ref(false);
const multiPiLoading = ref(false);
const multiPiProformas = ref([]);
const multiPiLines = ref([]);
const multiPiAllocations = ref({});
// Which sub-cut to book a bundle line against, keyed like the allocations.
const multiPiItems = ref({});
// Step 1 = pick the proformas, step 2 = allocate their lines. The selection
// survives "Back", so a user can widen or narrow it without starting over.
const multiPiStep = ref(1);
const multiPiSelected = ref([]);
// Step 2's own selection: which contract LINES get pushed, held as
// multiPiRowKey values. Deliberately not multiPiSelected — that one is step 1's
// list of PI names, and sharing it would make each step wipe the other's picks.
const multiPiPickedKeys = ref([]);

// The GROUP key mirrors the backend match key: (proforma, category). It used to
// include `item`, which is now empty on every compensated bundle — the whole
// modal would have collapsed onto one colliding key. This is the level the
// server guard enforces, so it stays exactly as it is.
const multiPiKey = (line) => `${line.pi_name}::${normKey(line.category)}`;

// One level down: a single PI line inside that group. A compensated bundle
// books thirteen cuts under one category and the user picks among the cuts, so
// allocations, item choices and checkboxes are all keyed here — never by array
// position, which a reload reorders.
const multiPiRowKey = (line, child) => `${multiPiKey(line)}::${child.row}`;

// The ONE place the group/line nesting is flattened. Everything downstream —
// the plan, the summary, Apply, the select-all counters — reads this list, so
// there is no second traversal that could disagree about what is on screen.
// It is also where the "still shippable" filter lives, for the same reason: a
// closed row planned to 0 boxes already, so dropping it here cannot change what
// any other row gets, and no counter can end up promising a line Apply skips.
// The indices stay those of the unfiltered arrays — they only feed DOM ids.
const multiPiRows = computed(() => {
	const out = [];
	multiPiLines.value.forEach((line, lineIdx) => {
		(line.contract_lines || []).forEach((child, childIdx) => {
			if (!multiPiRowIsOpen(line, child)) return;
			out.push({ line, child, key: multiPiRowKey(line, child), groupKey: multiPiKey(line), lineIdx, childIdx });
		});
	});
	return out;
});

// Contract items first, then sub-cuts earlier invoices actually used — the
// second group is where a bundle's real cuts live, since they are on no PI.
function multiPiItemOptions(line) {
	const seen = new Set();
	const out = [];
	for (const code of [...(line.items || []), ...(line.sub_cuts || []).map((s) => s.item)]) {
		if (!code || seen.has(code)) continue;
		seen.add(code);
		out.push(code);
	}
	return out;
}

// A contract line's own code first — it is what this row actually books — then
// the bundle's other cuts, because a compensated line may legitimately ship as
// a cut that is on no PI at all.
function multiPiRowItemOptions(line, child) {
	const seen = new Set();
	const out = [];
	for (const code of [child.item, ...multiPiItemOptions(line)]) {
		if (!code || seen.has(code)) continue;
		seen.add(code);
		out.push(code);
	}
	return out;
}

// The category pool — the only ceiling the backend actually checks.
// `remaining_boxes` is signed and goes negative on over-shipped lines: that is
// real data (C2) and must keep rendering as-is everywhere else (the Remaining
// cell, the over-shipped badge). This is the ONLY place that value gets floored
// at 0, because a pool of "minus 300 boxes" cannot be shared out.
const poolRemaining = (line) => Math.max(0, line.remaining_boxes || 0);

// How many boxes of this bundle already shipped under this exact cut. Advisory
// only: attributing a shipment to one contract line is the item-level matching
// that finds 19.5% of live CI lines, so it may only ever NARROW a ceiling —
// which can never produce a row set the server would refuse.
function rowShippedAsThisCut(line, child) {
	const code = normKey(child.item);
	if (!code) return 0;
	// If the bundle books this cut on more than one contract line there is no
	// way to say which one a shipment belongs to, so claim none of it.
	if ((line.contract_lines || []).filter((c) => normKey(c.item) === code).length !== 1) return 0;
	let boxes = 0;
	for (const cut of line.sub_cuts || []) {
		if (normKey(cut.item) === code) boxes += Number(cut.boxes) || 0;
	}
	return boxes;
}

// Ceiling (a): what this contract line itself still has. Keyed off the contract
// line's own `item`, never the `<select>` value — otherwise changing the
// dropdown would silently re-clamp a number the user already typed.
function rowContractRemaining(line, child) {
	return Math.max(0, (Number(child.boxes) || 0) - rowShippedAsThisCut(line, child));
}

// Step 2 offers what can still be shipped, and nothing else. A row qualifies
// only while both of its ceilings are open: the category pool must have boxes
// left, and this contract line must not already be fully shipped as its own
// cut. Both numbers come from the server response and never from what the user
// is typing, so no row can vanish out from under a quantity being entered —
// which rules out `maxAllocatable`, whose value depends on the rows above it.
const multiPiRowIsOpen = (line, child) => poolRemaining(line) > 0 && rowContractRemaining(line, child) > 0;

// Pools follow the same rule with one exception: an over-shipped category has
// no boxes left either, but that is a discrepancy the user has to see (C2), not
// noise to hide.
const multiPiOpenLines = computed(() => multiPiLines.value.filter((line) => poolRemaining(line) > 0 || line.over_shipped));

// A picker that silently drops rows reads as "this is everything there is".
const multiPiHiddenCount = computed(() => {
	let total = 0;
	for (const line of multiPiLines.value) total += (line.contract_lines || []).length;
	return total - multiPiRows.value.length;
});

// The groups exactly as the plan consumes them, in contract order.
const multiPiGroups = computed(() => {
	const groups = new Map();
	for (const row of multiPiRows.value) {
		let group = groups.get(row.groupKey);
		if (!group) {
			group = { groupKey: row.groupKey, pool: poolRemaining(row.line), rows: [] };
			groups.set(row.groupKey, group);
		}
		group.rows.push({
			rowKey: row.key,
			ownRemaining: rowContractRemaining(row.line, row.child),
			requested: multiPiAllocations.value[row.key] || 0,
			picked: multiPiPickedKeys.value.includes(row.key),
		});
	}
	return groups;
});

// Single source of truth for "how many boxes does each row actually get".
// The group header, the summary bar and the Apply loop all read this one plan,
// which is what stops the screen promising one total and pushing another.
const multiPiPlan = computed(() => buildAllocationPlan([...multiPiGroups.value.values()]));

// The double cap: the row's own contract AND what the rows above it left in the
// category pool. Exceeding either is a save the server guard refuses.
const maxAllocatable = (row) => rowCeiling(multiPiGroups.value.get(row.groupKey), row.key);

const multiPiGroupAllocated = (line) => multiPiPlan.value.byGroup[multiPiKey(line)]?.allocated || 0;

// Clamps a typed/pasted/spinner value into [0, maxAllocatable]. The `max`
// attribute alone is not enforced by the browser for typed or pasted input,
// so this runs on every @input.
function setAllocation(row, ev) {
	const key = row.key;
	const raw = ev.target.value;
	const parsed = parseInt(raw, 10);
	const n = Number.isNaN(parsed) ? 0 : parsed;
	const clamped = Math.min(Math.max(n, 0), maxAllocatable(row));
	multiPiAllocations.value[key] = clamped;
	// Nothing is preselected any more, so a quantity typed into an unchecked row
	// would plan to zero and Apply would skip it in silence. Typing IS the intent.
	if (clamped > 0 && !multiPiPickedKeys.value.includes(key)) multiPiPickedKeys.value.push(key);
	// The input is `:value`-bound, so when the clamp lands on the value the
	// field already held, no state changes and Vue never re-renders — the box
	// would keep showing what was typed while a different number gets applied.
	// Push the clamped value back onto the element itself.
	if (raw !== String(clamped)) ev.target.value = clamped;
}

// The ONE per-row calculation behind step 2. Both the summary bar the user
// reads and the Apply loop that pushes the rows call this — a second copy is
// exactly how a screen ends up promising one total and delivering another.
function multiPiLineTotals(row) {
	const boxes = multiPiPlan.value.byRow[row.key] || 0;
	// Per contract line, not per bundle: a mixed bundle weighs its cuts
	// differently, and the kg written to the CI must follow the line.
	const bw = row.child.box_weight_kg || row.line.box_weight_kg || DEFAULT_BOX_WEIGHT_KG;
	const qty = round2(boxes * bw);
	const rate = row.child.agreed_rate || row.line.agreed_rate || 0;
	return { key: row.key, boxes, bw, qty, value: qty * rate };
}

// Step 1: just the supplier's open proformas. `include_lines: false` skips the
// whole shipped-vs-contract arithmetic — nothing on this step renders it.
async function openMultiPiSmartFill() {
	if (!form.value.supplier) {
		toast.error(t("Please select a supplier first."));
		return;
	}
	multiPiModalOpen.value = true;
	multiPiStep.value = 1;
	multiPiLoading.value = true;
	multiPiLines.value = [];
	multiPiAllocations.value = {};
	multiPiItems.value = {};
	multiPiPickedKeys.value = [];
	try {
		const res = await call("stabler.api.imports.get_vendor_available_pi_lines", {
			company: activeCompany.value,
			supplier: form.value.supplier,
			exclude_ci: form.value.name || undefined,
			include_lines: false,
		});
		multiPiProformas.value = res.proformas || [];
		// Everything preselected: pressing Load straight away is the old
		// one-step behaviour, and narrowing is an opt-in from there.
		multiPiSelected.value = multiPiProformas.value.map((p) => p.name);
	} catch (err) {
		toast.error(err?.message || t("Could not fetch available PI lines."));
	} finally {
		multiPiLoading.value = false;
	}
}

const multiPiAllSelected = computed(
	() => multiPiProformas.value.length > 0 && multiPiSelected.value.length === multiPiProformas.value.length
);

function multiPiSelectAll(on) {
	multiPiSelected.value = on ? multiPiProformas.value.map((p) => p.name) : [];
}

// Step 2. ONE request for the whole selection — the narrowing is server-side,
// so this never fans out into a request per proforma.
async function loadMultiPiLines() {
	multiPiStep.value = 2;
	multiPiLoading.value = true;
	multiPiLines.value = [];
	multiPiAllocations.value = {};
	multiPiItems.value = {};
	multiPiPickedKeys.value = [];
	try {
		const res = await call("stabler.api.imports.get_vendor_available_pi_lines", {
			company: activeCompany.value,
			supplier: form.value.supplier,
			exclude_ci: form.value.name || undefined,
			selected_pis: JSON.stringify(multiPiSelected.value),
		});
		// `proformas` stays the FULL open list even on a narrowed load — step 1's
		// checkbox list is fed from here and must survive going Back.
		multiPiProformas.value = res.proformas || multiPiProformas.value;
		multiPiLines.value = res.lines || [];

		for (const line of multiPiLines.value) {
			for (const child of line.contract_lines || []) {
				const key = multiPiRowKey(line, child);
				// Nothing is pre-allocated and nothing is pre-checked: the picker asks
				// for a quantity, it does not propose one. "Select All" is the one-click
				// way back to filling every line to its ceiling.
				multiPiAllocations.value[key] = 0;
				multiPiItems.value[key] = multiPiRowItemOptions(line, child)[0] || "";
			}
		}
	} catch (err) {
		toast.error(err?.message || t("Could not fetch available PI lines."));
	} finally {
		multiPiLoading.value = false;
	}
}

// Only the checked contract lines exist as far as the summary bar and Apply are
// concerned. Keyed by multiPiRowKey, never by array position — a reload reorders.
const multiPiSelectedLines = computed(() =>
	multiPiRows.value.filter((row) => multiPiPickedKeys.value.includes(row.key))
);

const multiPiAllLinesSelected = computed(
	() => multiPiRows.value.length > 0 && multiPiPickedKeys.value.length === multiPiRows.value.length
);

// Drives the header checkbox's indeterminate state: some, but not all.
const multiPiSomeLinesSelected = computed(
	() => multiPiPickedKeys.value.length > 0 && !multiPiAllLinesSelected.value
);

// The rows the template renders under one group header, in contract order.
const multiPiRowsByGroup = computed(() => {
	const out = {};
	for (const row of multiPiRows.value) {
		if (!out[row.groupKey]) out[row.groupKey] = [];
		out[row.groupKey].push(row);
	}
	return out;
});

const multiPiGroupRows = (line) => multiPiRowsByGroup.value[multiPiKey(line)] || [];

// Unchecking never touches multiPiAllocations — a user who unchecks a row and
// changes their mind gets their typed number back. CHECKING, though, has to
// clamp: the freed boxes may have been spent on a sibling in the meantime, and
// the stored number would otherwise push the group past its pool.
function multiPiToggleRow(row, on) {
	if (!on) {
		multiPiPickedKeys.value = multiPiPickedKeys.value.filter((key) => key !== row.key);
		return;
	}
	if (!multiPiPickedKeys.value.includes(row.key)) multiPiPickedKeys.value.push(row.key);
	multiPiAllocations.value[row.key] = Math.min(multiPiAllocations.value[row.key] || 0, maxAllocatable(row));
}

function multiPiSelectAllLines(on) {
	if (!on) {
		// Deselect drops the picks and nothing else — a typed quantity survives it.
		multiPiPickedKeys.value = [];
		return;
	}
	// Order matters: rowCeiling gives each row what the rows ABOVE it left in
	// the pool, so a sequential walk fills the group to exactly its pool.
	for (const row of multiPiRows.value) {
		if (!multiPiPickedKeys.value.includes(row.key)) multiPiPickedKeys.value.push(row.key);
		multiPiAllocations.value[row.key] = maxAllocatable(row);
	}
}

// What Apply is about to push, counted the same way Apply counts it: the
// boxes > 0 gate applies here too, so the bar can never promise a line the
// push then drops.
const multiPiSummary = computed(() => {
	const out = { lines: 0, boxes: 0, qty: 0, value: 0 };
	for (const line of multiPiSelectedLines.value) {
		const { boxes, qty, value } = multiPiLineTotals(line);
		if (boxes <= 0) continue;
		out.lines += 1;
		out.boxes += boxes;
		out.qty += qty;
		out.value += value;
	}
	out.qty = round2(out.qty);
	out.value = round2(out.value);
	return out;
});

function applyMultiPiAllocation() {
	let addedCount = 0;
	const addedPis = new Set();
	for (const row of multiPiSelectedLines.value) {
		const { line, child } = row;
		const { key, boxes, bw, qty } = multiPiLineTotals(row);
		if (boxes > 0) {
			form.value.items.push({
				// The PI and the category are the GROUP's, written verbatim. That
				// pair is the whole reason splitting one bundle into thirteen rows
				// is invisible to the server guard: it sums CI rows by
				// (PI, category) before comparing, so thirteen rows and one row
				// with the same total are the same thing to it.
				custom_proforma_invoice: line.pi_name,
				category: line.category,
				item: multiPiItems.value[key] || child.item || line.item || "",
				description: child.description || line.description || "",
				hs_code: child.hs_code || line.hs_code || "",
				boxes: boxes,
				box_weight_kg: bw,
				qty: qty,
				uom: "Kg",
				rate: child.agreed_rate || line.agreed_rate,
				docs_price: child.docs_price || line.docs_price,
				_qtyManual: true,
			});
			addedPis.add(line.pi_name);
			addedCount++;
		}
	}

	// The header answers only for rows that name no PI of their own, so it may be
	// stamped only when the whole allocation came from a single proforma. It used
	// to take multiPiProformas[0] -- the supplier's FULL open list, not what the
	// user ticked -- so a container could be pinned to a proforma it shipped
	// nothing from, and that one link attributed every box.
	if (!form.value.custom_proforma_invoice && addedPis.size === 1) {
		form.value.custom_proforma_invoice = [...addedPis][0];
	}

	multiPiModalOpen.value = false;
	toast.success(t("Added {count} item lines from selected PIs.", { count: addedCount }));
	// A mixed container leaves the header blank on purpose -- every row carries its
	// own link, and no one proforma is the reference for all of them -- but the
	// field used to fill itself, so say why it no longer does.
	if (!form.value.custom_proforma_invoice && addedPis.size > 1) {
		toast.info(
			t("Lines come from {count} proformas, so each line keeps its own PI reference.", {
				count: addedPis.size,
			})
		);
	}
}

async function loadDoc() {
	if (isCreate.value) {
		form.value = blankForm();
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		const d = await importsApi.getCommercialInvoice(docName.value);
		form.value = {
			...blankForm(),
			...d,
			items: (d.items || []).map((it) => ({
				// The row's own PI only. Falling back to the header here made every line
			// look linked, and itemsPayload() then wrote that guess back on save.
			custom_proforma_invoice: it.custom_proforma_invoice || "",
				category: it.category || "",
				item: it.item,
				item_name: it.item,
				description: it.description || "",
				hs_code: it.hs_code || "",
				boxes: it.boxes || 0,
				box_weight_kg: it.box_weight_kg || 0,
				qty: it.qty || 0,
				uom: it.uom || "Kg",
				rate: it.rate || 0,
				docs_price: it.docs_price || 0,
				_qtyManual: true,
			})),
			po_links: (d.po_links || []).map((p) => ({ purchase_order: p.purchase_order })),
			containers: d.containers || [],
			trucks: d.trucks || [],
			customs_declarations: d.customs_declarations || [],
		};
		loadLineCategories();
		await refreshPiTracking();
		await Promise.all([
			fetchTransportInvoices(),
			fetchTransportCosts(),
			fetchCostOverview(),
			fetchDiscrepancies(),
			fetchExpenses(),
			fetchLandedCostUzs(),
		]);
	} catch (err) {
		error.value = err?.message || t("Failed to load the commercial invoice.");
	} finally {
		loading.value = false;
	}
}

async function refreshPiTracking() {
	if (!activeCompany.value || !form.value.supplier) {
		form.value.pi_tracking = [];
		piTrackingFailed.value = true;
		return;
	}
	piTrackingFailed.value = false;
	try {
		const res = await call("stabler.api.imports.get_vendor_available_pi_lines", {
			company: activeCompany.value,
			supplier: form.value.supplier,
			exclude_ci: form.value.name || undefined,
		});
		const trackingList = [];
		for (const line of res?.lines || []) {
			const boxWeight = line.box_weight_kg || DEFAULT_BOX_WEIGHT_KG;
			// The PI's own kg figures are authoritative; boxes × box weight is
			// only the fallback for contracts that never filled the qty column.
			const contractKg = line.contract_qty || (line.contract_boxes || 0) * boxWeight;
			const shippedKg = line.shipped_qty || (line.shipped_boxes || 0) * boxWeight;
			const remainingKg = contractKg - shippedKg;

			trackingList.push({
				proforma_invoice: line.pi_name,
				pi_ref: line.pi_ref || line.pi_name,
				item: line.item,
				// A compensated bundle has no single item — `items` carries all of
				// the contract's item codes for the sub-cut check.
				items: line.items || (line.item ? [line.item] : []),
				category: line.category || "",
				description: line.description || "",
				contract_boxes: line.contract_boxes,
				shipped_boxes: line.shipped_boxes,
				remaining_boxes: line.remaining_boxes,
				contract_qty: contractKg,
				total_invoiced_qty: shippedKg,
				remaining_qty: remainingKg,
				pct: line.pct,
				over_shipped: !!line.over_shipped,
				over_boxes: line.over_boxes || 0,
				ci_count: line.ci_count || 0,
				sub_cuts: line.sub_cuts || [],
				agreed_rate: line.agreed_rate,
				docs_price: line.docs_price,
				// One key can legitimately carry several contract prices; the row
				// is compliant when it equals ANY of them.
				agreed_prices: line.agreed_prices || [],
				docs_prices: line.docs_prices || [],
				box_weight_kg: line.box_weight_kg,
			});
		}
		form.value.pi_tracking = trackingList;
	} catch (err) {
		form.value.pi_tracking = [];
		piTrackingFailed.value = true;
		toast.error(err?.message || t("Could not fetch available PI lines."));
	}
}

async function loadProformaIntoCi(piName) {
	if (!piName) return;
	loading.value = true;
	try {
		const detail = await call("stabler.api.imports.proforma_detail", { name: piName });
		if (!detail) return;
		form.value.custom_proforma_invoice = detail.name;
		if (detail.supplier) {
			form.value.supplier = detail.supplier;
			form.value.supplier_name = detail.supplier_name || detail.supplier;
		}
		if (detail.import_pi_group) {
			form.value.import_pi_group = detail.import_pi_group;
		}
		if (detail.currency) {
			form.value.currency = detail.currency;
		}
		if (detail.incoterm) {
			form.value.incoterm = detail.incoterm;
		}
		if (detail.port_of_loading) {
			form.value.port_of_loading = detail.port_of_loading;
		}
		if (detail.port_of_discharge) {
			form.value.port_of_discharge = detail.port_of_discharge;
		}

		await refreshPiTracking();

		const piLines = (form.value.pi_tracking || []).filter(
			(tr) => tr.proforma_invoice === detail.name && tr.remaining_boxes > 0
		);

		if (piLines.length > 0) {
			form.value.items = piLines.map((line) => {
				const bw = line.box_weight_kg || DEFAULT_BOX_WEIGHT_KG;
				const boxes = line.remaining_boxes;
				const qty = round2(boxes * bw);
				// `item` is required on the child row, but a compensated bundle has
				// no single one — seed the contract's first item and let the user
				// pick the actual sub-cut.
				const item = line.item || (line.items || [])[0] || "";
				return {
					custom_proforma_invoice: detail.name,
					category: line.category || "",
					item: item,
					item_name: item,
					description: line.description || "",
					hs_code: "",
					boxes: boxes,
					box_weight_kg: bw,
					qty: qty,
					uom: "Kg",
					rate: Number(line.agreed_rate || 0),
					docs_price: Number(line.docs_price || 0),
					_qtyManual: true,
				};
			});
			toast.success(
				t("Auto-filled {count} remaining item lines from Proforma Invoice {ref}", {
					count: piLines.length,
					ref: detail.supplier_pi_ref || detail.name,
				})
			);
		} else if (piTrackingFailed.value && detail.items && detail.items.length) {
			// Remaining quantities are unknown, so the contract quantities are the only
			// data we have. They can over-ship the PI — warn instead of loading silently.
			form.value.items = detail.items.map((it) => ({
				custom_proforma_invoice: detail.name,
				category: it.category || "",
				item: it.item,
				item_name: it.item,
				description: it.description || "",
				hs_code: "",
				boxes: Number(it.boxes || 0),
				box_weight_kg: Number(it.box_weight_kg || 0),
				qty: Number(it.qty || 0),
				uom: it.uom || "Kg",
				rate: Number(it.rate || 0),
				docs_price: Number(it.docs_price || 0),
				_qtyManual: true,
			}));
			toast.warning(
				t("Remaining quantities could not be calculated. Loaded the original Proforma quantities. Please check them.")
			);
		} else {
			form.value.items = [];
			toast.warning(t("No remaining (unshipped) items found on this Proforma Invoice."));
		}
		loadLineCategories();
	} catch (err) {
		toast.error(err?.message || t("Failed to load proforma details."));
	} finally {
		loading.value = false;
	}
}

async function loadRefData() {
	if (!activeCompany.value) return;
	try {
		currencies.value = await call("stabler.api.sales.list_currencies", {});
	} catch (_) {
		currencies.value = [{ name: "USD" }, { name: "EUR" }];
	}
	try {
		companyPOs.value = await call("stabler.api.purchasing.list_purchase_orders", {
			company: activeCompany.value,
			limit: 200,
		});
	} catch (_) {
		companyPOs.value = [];
	}
}

function buildValues() {
	const v = {
		import_pi_group: form.value.import_pi_group || undefined,
		custom_proforma_invoice: form.value.custom_proforma_invoice || undefined,
		ci_number: form.value.ci_number,
		ci_date: form.value.ci_date || undefined,
		currency: form.value.currency,
		incoterm: form.value.incoterm,
		incoterm_location: form.value.incoterm_location,
		vessel: form.value.vessel,
		voyage: form.value.voyage,
		bl_number: form.value.bl_number,
		port_of_loading: form.value.port_of_loading,
		port_of_discharge: form.value.port_of_discharge,
		eta_transit_port: form.value.eta_transit_port || undefined,
		etd: form.value.etd || undefined,
		eta: form.value.eta || undefined,
		atd: form.value.atd || undefined,
		ata: form.value.ata || undefined,
		customs_fee_off_hours: form.value.customs_fee_off_hours ? 1 : 0,
	};
	if (form.value.customs_fee_override !== null && form.value.customs_fee_override !== "") {
		v.customs_fee_override = form.value.customs_fee_override;
	}
	if (costVisible.value) {
		v.docs_total = itemsDocsTotal.value;
		v.cash_difference = itemsCashDiff.value;
	}
	return v;
}

function itemsPayload() {
	return form.value.items
		.filter((r) => r.item)
		.map((r) => ({
			// A row sends the PI it was actually allocated from, or nothing at all --
			// an empty one means "the header answers for me" (COALESCE server-side).
			custom_proforma_invoice: r.custom_proforma_invoice || undefined,
			category: r.category || undefined,
			item: r.item,
			description: r.description || undefined,
			hs_code: r.hs_code || undefined,
			boxes: Number(r.boxes || 0),
			box_weight_kg: Number(r.box_weight_kg || 0),
			qty: Number(r.qty || 0),
			uom: r.uom || undefined,
			rate: Number(r.rate || 0),
			docs_price: Number(r.docs_price || 0),
		}));
}

async function save() {
	if (!form.value.supplier) {
		toast.error(t("A supplier is required."));
		return;
	}
	if (!itemsPayload().length) {
		toast.error(t("At least one item is required."));
		return;
	}
	saving.value = true;
	try {
		const poLinks = form.value.po_links.filter((p) => p.purchase_order).map((p) => p.purchase_order);
		if (isCreate.value) {
			const res = await importsApi.createCommercialInvoice({
				company: activeCompany.value,
				supplier: form.value.supplier,
				values: buildValues(),
				items: itemsPayload(),
				po_links: poLinks,
			});
			toast.success(t("Commercial invoice created."));
			router.replace("/imports/commercial-invoices/" + res.name);
		} else {
			await importsApi.updateCommercialInvoice({
				name: docName.value,
				supplier: form.value.supplier,
				values: buildValues(),
				items: itemsPayload(),
				po_links: poLinks,
				modified: form.value.modified,
			});
			toast.success(t("Commercial invoice saved."));
			await loadDoc();
		}
	} catch (err) {
		toast.error(err?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

async function advanceStatus(nextStatus) {
	const backward = !form.value.allowed_transitions.includes(nextStatus);
	let reason = null;
	if (backward) {
		if (!canRollback.value) return;
		reason = window.prompt(t("Reason for the status correction:"));
		if (!reason) return;
	} else {
		const ok = await confirm({
			title: t("Change status"),
			body: t("Move this commercial invoice to {status}?", { status: t(nextStatus) }),
			confirmLabel: t("Confirm"),
		});
		if (!ok) return;
	}
	try {
		await importsApi.setCiStatus(docName.value, nextStatus, reason);
		toast.success(t("Status updated."));
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Status change failed."));
	}
}

const PIPELINE = [
	"BOOKED",
	"STUFFED",
	"GATE_IN",
	"ON_BOARD",
	"IN_TRANSIT",
	"DISCHARGED",
	"AVAILABLE",
	"ARRIVED_AT_IRAN",
	"DELIVERED_TO_UZBEKISTAN",
];
const rollbackTarget = computed(() => {
	const idx = PIPELINE.indexOf(form.value.status);
	return idx > 0 ? PIPELINE[idx - 1] : null;
});

// Every status move the current user may make, as one list, so the action bar
// can offer a single menu instead of one button per transition. Same set as
// before: forward transitions (never "Cancelled" — cancelling a shipment is not
// a routine step) plus the privileged single-step correction.
const statusActions = computed(() => {
	const actions = (form.value.allowed_transitions || [])
		.filter((s) => s !== "Cancelled")
		.map((s) => ({ status: s, backward: false }));
	if (canRollback.value && rollbackTarget.value) {
		actions.push({ status: rollbackTarget.value, backward: true });
	}
	return actions;
});

const fm = (v, ccy) => formatMoney(v, ccy || "USD", user.value?.language || "en");
const fn = (v) => {
	if (v === null || v === undefined || isNaN(v)) return "0.00";
	const localeCode = user.value?.language === "en" ? "en-US" : "ru-RU";
	return new Intl.NumberFormat(localeCode, {
		minimumFractionDigits: 2,
		maximumFractionDigits: 2,
		useGrouping: true,
	}).format(Number(v) || 0);
};

// --- Booked-invoice drift -------------------------------------------------
// A submitted Purchase Invoice can never follow the CI's later corrections, so
// the A/P silently stops describing the deal. We only ever REPORT the gap here;
// re-booking cancels GL vouchers and un-allocates payments, which is an
// explicit, approved action — never a side effect of opening this form.
const drift = ref(null);
async function loadDrift() {
	drift.value = null;
	if (isCreate.value || !docName.value || !activeCompany.value) return;
	try {
		const res = await call("stabler.api.imports.ci_invoice_drift", {
			company: activeCompany.value,
			commercial_invoice: docName.value,
		});
		drift.value = (res?.rows || [])[0] || null;
	} catch {
		drift.value = null; // never block the form on a diagnostic
	}
}

// Re-booking cancels a GL voucher and knocks its payments loose, so it never
// runs on a single click: fetch the plan, show exactly what will happen, and
// only act on an explicit confirmation.
const rebooking = ref(false);
async function rebookInvoice() {
	if (rebooking.value) return;
	rebooking.value = true;
	try {
		const plan = await call("stabler.api.imports.rebook_ci_invoice", {
			company: activeCompany.value,
			commercial_invoice: docName.value,
			dry_run: 1,
		});
		if (plan?.reason === "in_sync") {
			toast.success(t("The booked invoice already matches this document."));
			await loadDrift();
			return;
		}
		if (plan?.blockers?.length) {
			toast.error(plan.blockers[0]);
			return;
		}
		const lines = [
			t("Cancel {invoice} ({old}) and re-book at {new}.", {
				invoice: plan.old_invoice,
				old: fm(plan.old_total, form.value.currency),
				new: fm(plan.new_total, form.value.currency),
			}),
			plan.payments_to_reallocate.length
				? t("{count} payment(s) totalling {amount} will be re-allocated.", {
					count: plan.payments_to_reallocate.length,
					amount: fm(plan.payments_total, form.value.currency),
				})
				: t("No payments are allocated to it."),
		];
		const ok = await confirm({
			title: t("Re-book the invoice?"),
			body: lines.join(" "),
			confirmLabel: t("Cancel and re-book"),
			danger: true,
		});
		if (!ok) return;
		const res = await call("stabler.api.imports.rebook_ci_invoice", {
			company: activeCompany.value,
			commercial_invoice: docName.value,
			dry_run: 0,
		});
		toast.success(t("Re-booked as {invoice}.", { invoice: res.new_invoice }));
		await loadDrift();
	} catch (err) {
		toast.error(err?.message || t("Could not re-book the invoice."));
	} finally {
		rebooking.value = false;
	}
}

// Deleting a CI reaches into containers, trucks and — where an invoice was
// booked — the ledger. So the button never deletes: it asks the endpoint what
// would happen (dry run, writes nothing), puts that report on screen, and only
// an explicit red confirmation acts on it.
const deleteModalOpen = ref(false);
const deletePlan = ref(null);
const deletePlanning = ref(false);
const deleteCascade = ref(false);
const deleting = ref(false);

const deleteBlockers = computed(() => deletePlan.value?.blockers || []);
const deleteCascadeRows = computed(() => cascadeRows(deletePlan.value));
const deleteCascadeCount = computed(() => deletePlan.value?.cascade_count || 0);
// A blocker is the owner's job to clear; a cascade is theirs to accept.
const canDelete = computed(() => {
	if (!deletePlan.value?.deletable) return false;
	return !deleteCascadeCount.value || deleteCascade.value;
});

async function openDeletePlan() {
	if (deletePlanning.value || !docName.value) return;
	deletePlanning.value = true;
	deletePlan.value = null;
	deleteCascade.value = false;
	try {
		deletePlan.value = await call("stabler.api.imports.delete_commercial_invoice", {
			company: activeCompany.value,
			name: docName.value,
			dry_run: 1,
		});
		deleteModalOpen.value = true;
	} catch (err) {
		toast.error(err?.message || t("Could not check what depends on this invoice."));
	} finally {
		deletePlanning.value = false;
	}
}

async function confirmDelete() {
	if (deleting.value || !canDelete.value) return;
	const label = form.value.ci_number || docName.value;
	const ok = await confirm({
		title: t("Delete this commercial invoice?"),
		body: deleteCascadeCount.value
			? t("{name} and {count} linked record(s) will be removed. This cannot be undone.", {
				name: label,
				count: deleteCascadeCount.value,
			})
			: t("{name} will be removed. This cannot be undone.", { name: label }),
		confirmLabel: t("Delete permanently"),
		danger: true,
	});
	if (!ok) return;
	deleting.value = true;
	try {
		await call("stabler.api.imports.delete_commercial_invoice", {
			company: activeCompany.value,
			name: docName.value,
			cascade: deleteCascade.value ? 1 : 0,
			dry_run: 0,
		});
		deleteModalOpen.value = false;
		toast.success(t("Commercial invoice {name} deleted.", { name: label }));
		router.push("/imports/commercial-invoices");
	} catch (err) {
		toast.error(err?.message || t("Could not delete the commercial invoice."));
	} finally {
		deleting.value = false;
	}
}

// Linking a proforma to a CI used to be one-way, so a mis-match stayed wrong
// forever. Unlinking hands the proforma back its open balance.
const unlinking = ref(false);
async function unlinkProforma() {
	const proforma = form.value.custom_proforma_invoice;
	if (unlinking.value || !proforma || !docName.value) return;
	const ok = await confirm({
		title: t("Unlink the proforma?"),
		body: t("{proforma} goes back to open and this invoice loses its agreement link.", { proforma }),
		confirmLabel: t("Unlink"),
		danger: true,
	});
	if (!ok) return;
	unlinking.value = true;
	try {
		const res = await call("stabler.api.imports.unlink_proforma_from_ci", {
			company: activeCompany.value,
			proforma,
			commercial_invoice: docName.value,
		});
		toast.success(res?.changed ? t("Proforma unlinked.") : t("The proforma was already unlinked."));
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Could not unlink the proforma."));
	} finally {
		unlinking.value = false;
	}
}

onMounted(async () => {
	loadItemsList();
	loadRefData();
	await loadDoc();
	if (isCreate.value && route.query.proforma) {
		await loadProformaIntoCi(String(route.query.proforma));
	}
	loadDrift();
});
watch(docName, async () => {
	await loadDoc();
	loadDrift();
});
watch(activeCompany, loadRefData);
// A different supplier means different proformas: step 1's selection and step
// 2's lines both belong to the old one, so neither may survive the switch.
watch(
	() => form.value.supplier,
	() => {
		multiPiStep.value = 1;
		multiPiProformas.value = [];
		multiPiSelected.value = [];
		multiPiLines.value = [];
		multiPiAllocations.value = {};
		multiPiItems.value = {};
		multiPiPickedKeys.value = [];
	}
);
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-outline-secondary btn-icon me-3" @click="router.push('/imports/commercial-invoices')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div class="flex-grow-1">
				<div class="d-flex align-items-center gap-2 flex-wrap">
					<!-- Main Title: CI Number (e.g. MH/3054/2025-26) -->
					<h2 class="page-title mb-0 font-monospace">
						{{ isCreate ? t("New commercial invoice") : (form.ci_number || form.name) }}
					</h2>
					<span
						v-if="!isCreate && form.ci_number && form.ci_number !== form.name"
						class="badge bg-secondary-lt font-monospace text-secondary"
						:title="t('ERPNext System Reference ID')"
					>
						Ref: {{ form.name }}
					</span>
					<StatusBadge v-if="!isCreate" doctype="Commercial Invoice" :status="form.status" />
				</div>
				<div class="text-secondary small mt-1">
					{{ form.supplier_name || form.supplier || t("No supplier selected") }}
					<template v-if="form.incoterm"> · {{ form.incoterm }}</template>
					<template v-if="form.ci_date"> · {{ formatDate(form.ci_date) }}</template>
				</div>
			</div>
			<div class="ms-auto">
				<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
					<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- Booked A/P no longer matches this invoice -->
		<div v-if="drift" class="alert alert-warning d-flex flex-wrap align-items-center gap-2">
			<i class="ti ti-alert-triangle"></i>
			<div>
				<div class="fw-semibold">{{ t("This invoice no longer matches the booked payable.") }}</div>
				<div class="small">
					{{ t("Agreed now") }}: <span class="font-monospace">{{ fm(drift.agreed_total, form.currency) }}</span>
					· {{ t("Booked") }}: <span class="font-monospace">{{ fm(drift.invoiced_total, form.currency) }}</span>
					· {{ t("Difference") }}:
					<span class="font-monospace fw-bold" :class="drift.delta_total > 0 ? 'text-red' : 'text-orange'">
						{{ fm(drift.delta_total, form.currency) }}
					</span>
					<span v-if="drift.lines_changed.length" class="ms-1">
						· {{ t("{count} line(s) changed", { count: drift.lines_changed.length }) }}
					</span>
					<span v-if="drift.lines_added.length" class="ms-1">
						· {{ t("{count} line(s) added", { count: drift.lines_added.length }) }}
					</span>
					<span v-if="drift.lines_removed.length" class="ms-1">
						· {{ t("{count} line(s) removed", { count: drift.lines_removed.length }) }}
					</span>
				</div>
				<div class="small text-secondary">
					{{ t("Accounting must cancel and re-book the invoice to correct the ledger.") }}
				</div>
			</div>
			<div class="ms-auto d-flex gap-2">
				<router-link
					:to="{ name: 'purchasing-invoice', params: { name: drift.purchase_invoice } }"
					class="btn btn-outline-secondary btn-sm"
				>
					{{ t("Open the booked invoice") }}
				</router-link>
				<button type="button" class="btn btn-outline-danger btn-sm" :disabled="rebooking" @click="rebookInvoice">
					<span v-if="rebooking" class="spinner-border spinner-border-sm me-1"></span>
					{{ t("Cancel and re-book") }}
				</button>
			</div>
		</div>

		<!-- Status action bar -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-body d-flex align-items-center flex-wrap gap-2">
				<span class="text-secondary small fw-semibold">{{ t("Status") }}:</span>
				<StatusBadge doctype="Commercial Invoice" :status="form.status" />
				<div v-if="statusActions.length" class="dropdown">
					<button
						type="button"
						class="btn btn-primary btn-sm dropdown-toggle"
						data-bs-toggle="dropdown"
						aria-expanded="false"
					>
						{{ t("Change status") }}
					</button>
					<div class="dropdown-menu stbl-menu stbl-menu--nocheck">
						<a
							v-for="a in statusActions"
							:key="`${a.backward ? 'back' : 'fwd'}-${a.status}`"
							href="#"
							class="dropdown-item stbl-menu-item"
							@click.prevent="advanceStatus(a.status)"
						>
							<i
								class="ti me-2 text-secondary"
								:class="a.backward ? 'ti-arrow-back-up' : 'ti-arrow-right'"
							></i>
							<StatusBadge doctype="Commercial Invoice" :status="a.status" />
							<span v-if="a.backward" class="ms-2 small text-secondary">{{ t("Roll back") }}</span>
						</a>
					</div>
				</div>

				<div class="ms-auto d-flex align-items-center gap-2 small text-secondary">
					<span v-if="form.etd">ETD {{ formatDate(form.etd) }}</span>
					<span v-if="form.eta">· ETA {{ formatDate(form.eta) }}</span>
					<span v-if="form.ata">· {{ t("fact") }} {{ formatDate(form.ata) }}</span>
				</div>
			</div>
		</div>

		<!-- 4 Summary Metric Tiles -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Goods · agreed") }}</div>
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ fm(itemsAgreedTotal, form.currency) }}</div>
						<div class="text-secondary mt-1" style="font-size:0.75rem">
							{{ t("docs") }} {{ fm(itemsDocsTotal, form.currency) }} · {{ t("diff") }} {{ fm(itemsCashDiff, form.currency) }}
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Logistics & duties") }}</div>
						<div class="h3 mb-0 font-monospace text-orange fw-bold">
							{{ fm((costOverviewData?.operational?.transport || 0) + (costOverviewData?.operational?.duties || 0), form.currency) }}
						</div>
						<div class="text-secondary mt-1" style="font-size:0.75rem">
							{{ t("transport") }} {{ fm(costOverviewData?.operational?.transport, form.currency) }} · {{ t("duties") }} {{ fm(costOverviewData?.operational?.duties, form.currency) }}
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Cost / kg") }}</div>
						<div class="h3 mb-0 font-monospace text-purple fw-bold">
							{{ costOverviewData?.operational?.per_kg ? costOverviewData.operational.per_kg + ' $' : '—' }}
						</div>
						<div class="text-secondary mt-1" style="font-size:0.75rem">
							{{ t("in accounting") }} {{ costOverviewData?.accounting?.per_kg ? costOverviewData.accounting.per_kg + ' $' : '—' }} · {{ t("gap") }} {{ costOverviewData?.gap?.per_kg ? costOverviewData.gap.per_kg + ' $' : '—' }}
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Unpaid") }}</div>
						<div class="h3 mb-0 font-monospace text-danger fw-bold">
							{{ fm(costOverviewData?.totals?.outstanding, form.currency) }}
						</div>
						<div class="text-secondary mt-1" style="font-size:0.75rem">
							{{ t("supplier") }} {{ fm(itemsAgreedTotal - itemsDocsTotal, form.currency) }} · {{ t("carriers") }} {{ fm(costOverviewData?.totals?.outstanding, form.currency) }}
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- 1 Header Details -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Header Details") }}</h3>
			</div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-6">
						<label class="form-label required">{{ t("Supplier") }}</label>
						<Typeahead
							v-slot="{ item }"
							v-model="form.supplier"
							:search="searchSuppliers"
							:display="form.supplier_name"
							:placeholder="t('Search supplier…')"
							open-on-focus
							@pick="pickSupplier"
						>
							<div class="fw-semibold">{{ item.supplier_name || item.name }}</div>
						</Typeahead>
					</div>
					<div class="col-md-3">
						<label class="form-label required">{{ t("CI number") }}</label>
						<input v-model="form.ci_number" type="text" class="form-control font-monospace fw-bold text-primary" :placeholder="t('e.g. MH/3054/2025-26')" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Date") }}</label>
						<DateInput v-model="form.ci_date" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Currency") }}</label>
						<Select v-model="form.currency" :options="currencyOptions" :placeholder="t('Currency')" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Incoterm") }}</label>
						<Select v-model="form.incoterm" :options="incotermOptions" :placeholder="t('Incoterm')" />
					</div>
					<div class="col-md-6">
						<label class="form-label">{{ t("Named place") }}</label>
						<input v-model="form.incoterm_location" type="text" class="form-control" />
					</div>
				</div>
			</div>
		</div>

		<!-- Logistics -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Shipping & logistics") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-4">
						<label class="form-label">{{ t("Vessel") }}</label>
						<input v-model="form.vessel" type="text" class="form-control" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Voyage") }}</label>
						<input v-model="form.voyage" type="text" class="form-control" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("B/L number") }}</label>
						<input v-model="form.bl_number" type="text" class="form-control" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Port of loading") }}</label>
						<input v-model="form.port_of_loading" type="text" class="form-control" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Port of discharge") }}</label>
						<input v-model="form.port_of_discharge" type="text" class="form-control" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Transit ETA (Iran)") }}</label>
						<DateInput v-model="form.eta_transit_port" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("ETD") }}</label>
						<DateInput v-model="form.etd" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("ETA") }}</label>
						<DateInput v-model="form.eta" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("ATD") }}</label>
						<DateInput v-model="form.atd" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("ATA") }}</label>
						<DateInput v-model="form.ata" />
					</div>
				</div>
			</div>
		</div>

		<!-- 2 Items — colour-banded grid with Vendor Category dropdown -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">
					{{ t("Items") }}
					<span
						v-if="priceDiscrepancyItemCount"
						class="badge bg-warning-lt text-warning ms-2"
						:title="t('Lines where agreed price differs from contract')"
					>
						<i class="ti ti-alert-triangle me-1"></i>{{ t("1 line: price below agreed") }}
					</span>
				</h3>
				<div class="card-actions d-flex gap-2">
					<button
						type="button"
						class="btn btn-primary btn-sm fw-bold"
						:disabled="!form.supplier"
						:title="t('Smart Fill items and quantities from supplier Proforma Invoices')"
						@click="openMultiPiSmartFill"
					>
						<i class="ti ti-wand me-1"></i>{{ t("Smart Fill from PIs") }}
					</button>
					<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addItem">
						<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
					</button>
				</div>
			</div>
			<div class="card-body py-2">
				<div class="d-flex align-items-center gap-3 small text-secondary">
					<span><i class="ti ti-square-rounded-filled text-orange me-1"></i>{{ t("Physical") }}</span>
					<span><i class="ti ti-square-rounded-filled text-blue me-1"></i>{{ t("Agreed (true)") }}</span>
					<span><i class="ti ti-square-rounded-filled text-green me-1"></i>{{ t("Docs (customs)") }}</span>
				</div>
			</div>
			<div class="table-responsive" style="max-height: 560px; overflow-y: auto;">
				<table class="table table-sm table-bordered align-middle mb-0">
					<thead style="position: sticky; top: 0; z-index: 1">
						<tr>
							<th style="min-width: 140px">{{ t("Category") }}</th>
							<th style="min-width: 130px">{{ t("Ref PI") }}</th>
							<th style="min-width: 160px">{{ t("Product Code/Name") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 80px">{{ t("Boxes") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 90px">{{ t("Quantity (KG)") }}</th>
							<th class="text-end bg-blue-lt text-blue" style="width: 110px">{{ t("Agreed Price") }}</th>
							<th class="text-nowrap" style="width: 140px">{{ t("Against contract") }}</th>
							<th class="text-end bg-green-lt text-green" style="width: 110px">{{ t("Docs Price") }}</th>
							<th class="text-end bg-blue-lt text-blue" style="width: 130px">{{ t("Agreed Total") }}</th>
							<th class="text-end bg-purple-lt text-purple" style="width: 120px">{{ t("Cost / kg") }}</th>
							<th style="width: 36px"></th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="(row, idx) in form.items"
							:key="idx"
							:style="itemPriceValidation(row) && !itemPriceValidation(row).matched ? 'background: #fffdf7' : ''"
						>
							<td>
								<select v-if="categoryOptions.length" v-model="row.category" class="form-select form-select-sm fw-semibold">
									<option value="">— {{ t("N/A") }} —</option>
									<option v-for="cat in categoryOptions" :key="cat" :value="cat">{{ cat }}</option>
								</select>
								<input v-else v-model="row.category" type="text" class="form-control form-control-sm" :placeholder="t('Vendor Category')">
							</td>
							<td>
								<router-link
									v-if="row.custom_proforma_invoice || form.custom_proforma_invoice"
									:to="'/imports/proformas/' + (row.custom_proforma_invoice || form.custom_proforma_invoice)"
									class="fw-bold font-monospace text-primary text-decoration-none small text-truncate d-inline-block"
									style="max-width: 120px"
								>
									{{ row.custom_proforma_invoice || form.custom_proforma_invoice }}
								</router-link>
								<span v-else class="text-secondary">—</span>
							</td>
							<td>
								<select v-model="row.item" class="form-select form-select-sm fw-semibold" @change="onItemSelect(row)">
									<option value="">— {{ t("Select product") }} —</option>
									<option v-for="it in itemsList" :key="it.item_code || it.name" :value="it.item_code || it.name">
										{{ it.item_code || it.name }} — {{ it.item_name }}
									</option>
								</select>
							</td>
							<td><input v-model.number="row.boxes" type="number" step="1" class="form-control form-control-sm text-end font-monospace" @input="onBoxesOrWeightInput(row)"></td>
							<td><input v-model.number="row.qty" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace text-warning fw-semibold" @input="onQtyInput(row)"></td>
							<td><MoneyInput v-model="row.rate" :currency="form.currency" :language="user.language" :max-fraction-digits="4" hide-currency size="sm" /></td>
							<td>
								<span v-if="itemPriceValidation(row) && !itemPriceValidation(row).hasDiff" class="badge bg-success-lt text-success">
									= {{ fn(row.rate) }}
								</span>
								<span v-else-if="itemPriceValidation(row) && itemPriceValidation(row).hasDiff" class="badge bg-warning-lt text-warning" :title="itemPriceValidation(row).tooltip || undefined">
									≠ {{ fn(itemPriceValidation(row).mainAgreed) }} · {{ fm(itemPriceValidation(row).diffAmount, form.currency) }}
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td><MoneyInput v-model="row.docs_price" :currency="form.currency" :language="user.language" :max-fraction-digits="4" hide-currency size="sm" /></td>
							<td class="text-end font-monospace text-blue bg-blue-lt fw-semibold">{{ fn(rowAmount(row)) }}</td>
							<td class="text-end font-monospace text-purple bg-purple-lt fw-semibold">{{ fn(itemLandedCostPerKg(row)) }}</td>
							<td>
								<button type="button" class="btn btn-icon btn-sm btn-ghost-secondary" :title="t('Remove')" @click="removeItem(idx)">
									<i class="ti ti-trash"></i>
								</button>
							</td>
						</tr>
						<tr v-if="!form.items.length">
							<td colspan="11" class="text-secondary text-center py-3">{{ t("No items yet.") }}</td>
						</tr>
					</tbody>
					<tfoot v-if="form.items.length">
						<tr>
							<td colspan="8" class="text-end fw-semibold small">{{ t("Totals") }}</td>
							<td class="text-end font-monospace fw-semibold text-blue bg-blue-lt">{{ fm(itemsAgreedTotal, form.currency) }}</td>
							<td class="text-end font-monospace fw-semibold text-purple bg-purple-lt">{{ costOverviewData?.operational?.per_kg ? costOverviewData.operational.per_kg + ' $' : '—' }}</td>
							<td></td>
						</tr>
					</tfoot>
				</table>
			</div>
			<div class="card-footer py-2 small text-secondary d-flex align-items-center justify-content-between">
				<span>{{ t("Agreed price is matched against PI line key (PI + category); key can carry multiple prices — matching any is compliant (tolerance 0.005).") }}</span>
				<router-link to="/reports/pi-discrepancies" class="btn btn-ghost-primary btn-sm ms-2">
					{{ t("Discrepancies Report →") }}
				</router-link>
			</div>
		</div>

		<!-- 3b This CI's share of the PI advance (read-only) -->
		<div v-if="advanceShare" class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between flex-wrap gap-2">
				<h3 class="card-title m-0">
					<i class="ti ti-cash me-2"></i>{{ t("Advance for this CI") }}
				</h3>
				<span class="badge" :class="getStatusBadgeClass('CI Advance Share', advanceShareState)">
					{{ t(advanceShareState) }}
				</span>
			</div>
			<div class="table-responsive">
				<table class="table table-sm table-vcenter mb-0">
					<thead>
						<tr>
							<th>{{ t("Proforma Invoice") }}</th>
							<th class="text-end">{{ t("Advance %") }}</th>
							<th class="text-end">{{ t("Expected payment") }}</th>
							<th class="text-end">{{ t("Paid on PI") }}</th>
							<th class="text-end">{{ t("Allocated on PI") }}</th>
							<th class="text-end">{{ t("CI Amount") }}</th>
							<th class="text-end">{{ advanceShareNote }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="row in advanceShare.sources" :key="row.proforma_invoice">
							<td>
								<router-link
									:to="`/imports/proformas/${row.proforma_invoice}`"
									class="font-monospace"
									>{{ row.supplier_pi_ref || row.proforma_invoice }}</router-link
								>
							</td>
							<td class="text-end font-monospace">{{ row.advance_pct }}%</td>
							<td class="text-end font-monospace">
								{{ formatDate(row.expected_payment_date) }}
							</td>
							<td class="text-end font-monospace">
								{{ fm(row.pi_advance_paid, advanceShare.currency) }}
							</td>
							<td class="text-end font-monospace">
								{{ fm(row.pi_advance_allocated, advanceShare.currency) }}
							</td>
							<td class="text-end font-monospace">
								{{ fm(row.ci_amount, advanceShare.currency) }}
							</td>
							<td class="text-end font-monospace fw-bold">
								{{ fm(advanceShareRowAmount(row), advanceShare.currency) }}
							</td>
						</tr>
					</tbody>
					<tfoot v-if="advanceShare.sources.length > 1">
						<tr>
							<td colspan="6" class="text-end fw-semibold small">{{ t("Totals") }}</td>
							<td class="text-end font-monospace fw-semibold">
								{{ fm(advanceShareTotal, advanceShare.currency) }}
							</td>
						</tr>
					</tfoot>
				</table>
			</div>
			<div class="card-footer py-2 small text-secondary">
				<div>
					{{ t("Paid on PI and Allocated on PI are totals for the whole Proforma Invoice, not this CI's share.") }}
				</div>
				<template v-if="advanceShare.state === 'planned'">
					{{ t("Proportional share only — it is booked when a Purchase Invoice is created for this CI.") }}
				</template>
				<template v-else>
					{{ t("Purchase Invoice") }}:
					<span class="font-monospace">{{ advanceShare.purchase_invoice }}</span>
				</template>
			</div>
		</div>

		<!-- 4 Linked Containers -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between flex-wrap gap-2">
				<h3 class="card-title m-0"><i class="ti ti-box me-2"></i>{{ t("Linked Containers") }}</h3>
				<div class="d-flex align-items-center gap-2 flex-wrap">
					<div style="min-width: 220px">
						<Typeahead
							v-slot="{ item }"
							:search="searchContainers"
							:placeholder="t('Link an existing container…')"
							size="sm"
							open-on-focus
							:disabled="linkingContainer"
							@pick="linkContainer"
						>
							<div class="fw-semibold font-monospace">{{ item.container_number || item.name }}</div>
							<div class="small text-secondary">
								{{ item.status }} · {{ fn(item.total_kg) }} kg
								<span v-if="item.commercial_invoice"> · {{ item.commercial_invoice }}</span>
							</div>
						</Typeahead>
					</div>
					<div class="input-group input-group-sm" style="width: 240px">
						<input
							v-model="newContainerNumber"
							type="text"
							class="form-control"
							:placeholder="t('New container no.')"
							:disabled="linkingContainer"
							@keyup.enter="createContainer"
						/>
						<button
							type="button"
							class="btn btn-outline-secondary"
							:disabled="!newContainerNumber.trim() || linkingContainer"
							@click="createContainer"
						>
							<i class="ti ti-plus"></i>
						</button>
					</div>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter table-hover mb-0">
					<thead>
						<tr>
							<th>{{ t("Container") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Boxes / kg") }}</th>
							<th>{{ t("Advance 70%") }}</th>
							<th>{{ t("Telex / BL") }}</th>
							<th>{{ t("Gate-in → ГТД") }}</th>
							<th class="text-end">{{ t("Logistics") }}</th>
							<th class="text-end">{{ t("Cost / kg") }}</th>
							<th style="width: 40px;"></th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="(cnt, idx) in form.containers"
							:key="cnt.name || idx"
							style="cursor: pointer"
							:style="cnt.advance_70_status === 'UNPAID' ? 'background: #fff9f9' : (getContainerGateInDiff(cnt) && getContainerGateInDiff(cnt).status === 'overdue' ? 'background: #fffdf7' : '')"
						>
							<td class="font-monospace fw-bold text-primary" @click="router.push('/imports/containers/' + cnt.name)">{{ cnt.container_number || cnt.name }}</td>
							<td @click="router.push('/imports/containers/' + cnt.name)"><span class="badge bg-secondary-lt">{{ cnt.status }}</span></td>
							<td class="text-end font-monospace" @click="router.push('/imports/containers/' + cnt.name)">{{ fn(cnt.total_boxes) }} / {{ fn(cnt.total_kg) }} kg</td>
							<td @click="router.push('/imports/containers/' + cnt.name)">
								<span v-if="cnt.advance_70_status === 'PAID'" class="badge bg-success-lt text-success">
									{{ fm(cnt.advance_70_amount, form.currency) }} · {{ formatDate(cnt.advance_70_date) }}
								</span>
								<span v-else-if="cnt.advance_70_status === 'UNPAID'" class="badge bg-danger-lt text-danger">
									{{ t("unpaid") }} · {{ fm(cnt.advance_70_amount, form.currency) }}
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td @click="router.push('/imports/containers/' + cnt.name)">
								<span v-if="cnt.bl_type === 'TELEX'" class="badge bg-success-lt text-success">
									TELEX · {{ formatDate(cnt.telex_release_date) }}
								</span>
								<span v-else-if="cnt.bl_type" class="badge bg-secondary-lt">
									{{ cnt.bl_type }}
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="small" @click="router.push('/imports/containers/' + cnt.name)">
								<span v-if="getContainerGateInDiff(cnt)" :class="getContainerGateInDiff(cnt).status === 'overdue' ? 'text-danger fw-bold' : 'text-secondary'">
									{{ getContainerGateInDiff(cnt).text }}
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="text-end font-monospace text-azure fw-semibold" @click="router.push('/imports/containers/' + cnt.name)">
								{{ containerCostMap[cnt.name] ? fm(containerCostMap[cnt.name].logistics_amount, form.currency) : "—" }}
							</td>
							<td class="text-end font-monospace text-purple fw-semibold" @click="router.push('/imports/containers/' + cnt.name)">
								{{ containerCostMap[cnt.name] ? containerCostMap[cnt.name].landed_per_kg + ' $' : "—" }}
							</td>
							<td>
								<button
									type="button"
									class="btn btn-outline-secondary btn-sm p-1"
									:title="t('Unlink container')"
									:disabled="linkingContainer"
									@click.stop="unlinkContainer(cnt)"
								>
									<i class="ti ti-unlink"></i>
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- 5 Transport, expenses & supplier bills -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between flex-wrap gap-2">
				<h3 class="card-title m-0"><i class="ti ti-truck me-2 text-primary"></i>{{ t("Transport, expenses & supplier bills") }}</h3>
				<div class="card-actions d-flex gap-2 flex-wrap">
					<button
						type="button"
						class="btn btn-primary btn-sm fw-bold"
						@click="openTransportModal('existing')"
					>
						<i class="ti ti-link me-1"></i>{{ t("Link transport bill") }}
					</button>
					<button
						type="button"
						class="btn btn-outline-primary btn-sm fw-bold"
						@click="openTransportModal('new')"
					>
						<i class="ti ti-plus me-1"></i>{{ t("Create transport bill") }}
					</button>
					<router-link to="/imports/expenses" class="btn btn-outline-secondary btn-sm fw-bold">
						<i class="ti ti-cash me-1"></i>{{ t("Add expense") }}
					</router-link>
				</div>
			</div>
			<div class="card-body">
				<!-- Transport Landed Cost Summary Banner -->
				<div v-if="transportInvoicesData" class="row g-3 mb-3">
					<div class="col-sm-6 col-lg-3">
						<div class="card card-sm bg-light-subtle">
							<div class="card-body">
								<div class="d-flex align-items-center">
									<div class="subheader">{{ t("Total Transport Bills") }}</div>
								</div>
								<div class="h2 mb-0 font-monospace text-primary">
									{{ fm(transportInvoicesData.total_usd, "USD") }}
								</div>
								<div v-if="transportInvoicesData.company_currency !== 'USD'" class="small text-secondary font-monospace mt-1">
									≈ {{ fn(transportInvoicesData.total_company_currency) }} {{ transportInvoicesData.company_currency }}
								</div>
							</div>
						</div>
					</div>
					<div class="col-sm-6 col-lg-3">
						<div class="card card-sm bg-light-subtle">
							<div class="card-body">
								<div class="d-flex align-items-center">
									<div class="subheader">{{ t("Transport Cost / kg") }}</div>
								</div>
								<div class="h2 mb-0 font-monospace text-purple">
									${{ transportInvoicesData.rate_per_kg_usd }} / kg
								</div>
								<div v-if="transportInvoicesData.company_currency !== 'USD'" class="small text-secondary font-monospace mt-1">
									≈ {{ fn(transportInvoicesData.rate_per_kg_company) }} {{ transportInvoicesData.company_currency }} / kg
								</div>
							</div>
						</div>
					</div>
					<div class="col-sm-6 col-lg-3">
						<div class="card card-sm bg-light-subtle">
							<div class="card-body">
								<div class="d-flex align-items-center">
									<div class="subheader">{{ t("Linked Invoices") }}</div>
								</div>
								<div class="h2 mb-0 font-monospace">
									{{ transportInvoicesData.invoice_count }}
								</div>
								<div class="small text-secondary mt-1">
									{{ t("Across {kg} kg cargo", { kg: fn(transportInvoicesData.total_kg) }) }}
								</div>
							</div>
						</div>
					</div>
					<div class="col-sm-6 col-lg-3">
						<div class="card card-sm bg-light-subtle">
							<div class="card-body">
								<div class="d-flex align-items-center">
									<div class="subheader">{{ t("Accounting Routing") }}</div>
								</div>
								<div class="mt-1">
									<span class="badge bg-success-lt text-success">
										<i class="ti ti-shield-check me-1"></i>{{ t("Balance Sheet (Landed Cost)") }}
									</span>
								</div>
								<div class="small text-secondary mt-1">
									{{ t("Zero P&L impact — capitalized via LCV") }}
								</div>
							</div>
						</div>
					</div>
				</div>

				<h4 class="card-title mb-2">{{ t("Linked Transport Bills") }}</h4>
				<div class="table-responsive mb-3">
					<table class="table table-sm table-bordered align-middle mb-0">
						<thead class="table-light">
							<tr>
								<th>{{ t("Bill No") }}</th>
								<th>{{ t("Supplier / Carrier") }}</th>
								<th>{{ t("Posting Date") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
								<th class="text-end">{{ t("Outstanding") }}</th>
								<th>{{ t("Expense Account") }}</th>
								<th>{{ t("Status") }}</th>
								<th>{{ t("Actions") }}</th>
							</tr>
						</thead>
						<tbody v-if="loadingTransportInvoices">
							<SkeletonRows :rows="3" :cols="8" />
						</tbody>
						<tbody v-else>
							<tr v-if="!transportInvoicesData?.invoices?.length">
								<td colspan="8" class="text-center text-secondary py-2">{{ t("No supplier bills linked yet.") }}</td>
							</tr>
							<tr v-for="b in (transportInvoicesData?.invoices || [])" :key="b.name">
								<td>
									<router-link :to="'/purchasing/invoices/' + b.name" class="fw-bold font-monospace text-primary text-decoration-none">
										{{ b.bill_no || b.name }}
									</router-link>
									<span v-if="b.custom_import_truck" class="badge bg-secondary-lt ms-1 font-monospace small">
										{{ b.custom_import_truck }}
									</span>
								</td>
								<td>{{ b.supplier_name || b.supplier }}</td>
								<td>{{ b.posting_date ? formatDate(b.posting_date) : '—' }}</td>
								<td class="text-end font-monospace fw-bold">{{ fm(b.grand_total, b.currency) }}</td>
								<td class="text-end font-monospace" :class="b.outstanding_amount > 0 ? 'text-danger' : 'text-success'">
									{{ fm(b.outstanding_amount, b.currency) }}
								</td>
								<td>
									<span v-if="b.is_landed_cost_account" class="badge bg-success-lt text-success" :title="b.expense_account">
										<i class="ti ti-check me-1"></i>{{ b.expense_account || t("Landed Cost Clearing") }}
									</span>
									<span v-else class="badge bg-warning-lt text-warning" :title="b.expense_account">
										<i class="ti ti-alert-circle me-1"></i>{{ b.expense_account || t("P&L Expense") }}
									</span>
								</td>
								<td>
									<span class="badge" :class="getStatusBadgeClass('Purchase Invoice', b.status)">{{ b.status }}</span>
								</td>
								<td>
									<button
										v-if="!billUnlinkBlockedReason(b)"
										type="button"
										class="btn btn-outline-danger btn-sm p-1"
										:disabled="unlinkingBill === b.name"
										:title="t('Unlink from CI')"
										@click="unlinkBill(b)"
									>
										<i class="ti ti-unlink"></i>
									</button>
									<span v-else class="text-secondary small" :title="billUnlinkBlockedReason(b)">
										<i class="ti ti-lock"></i>
									</span>
								</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div class="mt-4 pt-3 border-top">
					<div class="d-flex align-items-center justify-content-between mb-2">
						<h4 class="card-title mb-0">{{ t("Bills you can attach") }}</h4>
						<button
							type="button"
							class="btn btn-outline-secondary btn-sm"
							:disabled="loadingUnlinkedBills"
							@click="fetchUnlinkedBills({ clearResults: true })"
						>
							<span v-if="loadingUnlinkedBills" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-search me-1"></i>
							{{ unlinkedBillsRequested ? t("Refresh") : t("Find bills to link") }}
						</button>
					</div>

					<div v-if="loadingUnlinkedBills" class="table-responsive">
						<table class="table table-sm table-bordered align-middle mb-0">
							<thead class="table-light">
								<tr>
									<th style="width: 30px"></th>
									<th>{{ t("Bill") }}</th>
									<th>{{ t("Supplier") }}</th>
									<th>{{ t("Supplier group") }}</th>
									<th class="text-end">{{ t("Amount") }}</th>
									<th class="text-end">{{ t("Outstanding") }}</th>
									<th>{{ t("Posting date") }}</th>
									<th>{{ t("Due date") }}</th>
									<th>{{ t("Status") }}</th>
								</tr>
							</thead>
							<SkeletonRows :rows="4" :cols="9" />
						</table>
					</div>

					<template v-else-if="unlinkedBillsRequested && !unlinkedBillsHidden">
						<div v-if="unlinkedBillsResult?.summary?.capped" class="alert alert-warning py-2 px-3 small mb-2">
							<i class="ti ti-alert-triangle me-1"></i>
							{{ t("Showing only the first {limit} bills — narrow the picture before assuming a missing bill was never entered.", { limit: unlinkedBillsResult.summary.limit }) }}
						</div>

						<div v-if="!unlinkedBillRows.length" class="text-secondary small py-2">
							{{ t("No unlinked transport bills found company-wide.") }}
						</div>

						<template v-else>
							<div class="table-responsive mb-2">
								<table class="table table-sm table-bordered align-middle mb-0">
									<thead class="table-light">
										<tr>
											<th style="width: 30px">
												<input
													type="checkbox"
													class="form-check-input"
													:checked="allUnlinkedSelected"
													@change="toggleAllUnlinkedBills($event.target.checked)"
												/>
											</th>
											<th>{{ t("Bill") }}</th>
											<th>{{ t("Supplier") }}</th>
											<th>{{ t("Supplier group") }}</th>
											<th class="text-end">{{ t("Amount") }}</th>
											<th class="text-end">{{ t("Outstanding") }}</th>
											<th>{{ t("Posting date") }}</th>
											<th>{{ t("Due date") }}</th>
											<th>{{ t("Status") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="r in unlinkedBillRows" :key="r.name">
											<td>
												<input
													type="checkbox"
													class="form-check-input"
													:checked="selectedUnlinkedBills.includes(r.name)"
													@change="toggleUnlinkedBill(r.name, $event.target.checked)"
												/>
											</td>
											<td>
												<router-link :to="'/purchasing/invoices/' + r.name" class="fw-bold font-monospace text-primary text-decoration-none">
													{{ r.bill_no || r.name }}
												</router-link>
											</td>
											<td>{{ r.supplier_name || r.supplier }}</td>
											<td class="small text-secondary">{{ r.supplier_group || '—' }}</td>
											<td class="text-end font-monospace">{{ fm(r.grand_total, r.currency) }}</td>
											<td class="text-end font-monospace text-danger">{{ fm(r.outstanding_amount, r.currency) }}</td>
											<td>{{ r.posting_date ? formatDate(r.posting_date) : '—' }}</td>
											<td>{{ r.due_date ? formatDate(r.due_date) : '—' }}</td>
											<td><span class="badge" :class="getStatusBadgeClass('Purchase Invoice', r.status)">{{ r.status }}</span></td>
										</tr>
									</tbody>
								</table>
							</div>

							<div class="d-flex align-items-center gap-2 flex-wrap">
								<button
									type="button"
									class="btn btn-primary btn-sm"
									:disabled="!selectedUnlinkedBills.length || linkingSelected"
									@click="linkSelectedBills"
								>
									<span v-if="linkingSelected" class="spinner-border spinner-border-sm me-1"></span>
									{{ t("Link {count} bill(s) to this CI", { count: selectedUnlinkedBills.length }) }}
								</button>
								<span class="text-secondary small">
									{{ t("{count} of {total} selected", { count: selectedUnlinkedBills.length, total: unlinkedBillRows.length }) }}
								</span>
							</div>

							<div v-if="linkResults.length" class="mt-2">
								<div v-for="o in linkResults" :key="o.name" class="small" :class="o.ok ? 'text-success' : 'text-danger'">
									<i class="me-1" :class="o.ok ? 'ti ti-check' : 'ti ti-x'"></i>{{ o.name }} — {{ o.ok ? t('Linked.') : o.message }}
								</div>
							</div>
						</template>
					</template>

					<!-- Reached only by users who can open Stabler Settings. One neutral
					     line, no action button: the fix lives on a different screen. -->
					<div v-else-if="unlinkedBillsRequested && unlinkedBillsNotConfigured" class="text-secondary small py-2">
						<i class="ti ti-info-circle me-1"></i>{{ unlinkedBillsNotConfigured }}
					</div>
				</div>

				<h4 class="card-title mb-2 mt-4">{{ t("Expenses without bills") }}</h4>
				<div class="table-responsive mb-3">
					<table class="table table-sm table-bordered align-middle mb-0">
						<thead class="table-light">
							<tr>
								<th>{{ t("Expense") }}</th>
								<th>{{ t("Category") }}</th>
								<th>{{ t("Supplier") }}</th>
								<th>{{ t("Linked to") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="e in (costOverviewData?.unbilled || [])" :key="e.name">
								<td class="fw-semibold font-monospace">{{ e.name }}</td>
								<td><span class="badge bg-secondary-lt">{{ e.category }}</span></td>
								<td>{{ e.supplier_name || e.supplier }}</td>
								<td class="font-monospace small">{{ e.container || e.truck || form.name }}</td>
								<td class="text-end font-monospace text-purple">{{ fm(e.amount, costOverviewData?.currency) }}</td>
							</tr>
							<tr v-if="!costOverviewData?.unbilled?.length">
								<td colspan="5" class="text-center text-secondary py-2">{{ t("All expenses are billed.") }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div class="p-2 bg-light-subtle rounded border text-secondary small d-flex align-items-center">
					<i class="ti ti-calculator me-2 text-primary"></i>
					<span>
						{{ t("Reconciliation: expenses {exp} − bills {bills} = {unbilled} unbilled", {
							exp: fm(costOverviewData?.totals?.transport, costOverviewData?.currency),
							bills: fm(costOverviewData?.totals?.billed, costOverviewData?.currency),
							unbilled: fm(costOverviewData?.totals?.unbilled, costOverviewData?.currency)
						}) }}
					</span>
					<router-link to="/imports/expenses" class="ms-auto btn btn-ghost-primary btn-sm">
						{{ t("Unallocated expenses →") }}
					</router-link>
				</div>
			</div>
		</div>

		<!-- 6 Shipment Cost Breakdown -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title"><i class="ti ti-calculator me-2 text-purple"></i>{{ t("Shipment Cost Breakdown") }}</h3>
			</div>
			<div class="card-body">
				<div class="row g-3 mb-3">
					<div class="col-md-6 border-end">
						<h4 class="card-title text-primary mb-2">{{ t("Operational") }}</h4>
						<div class="d-flex justify-content-between py-1 border-bottom">
							<span>{{ t("Goods") }}</span>
							<span class="font-monospace fw-semibold">{{ fm(costOverviewData?.operational?.goods, costOverviewData?.currency) }}</span>
						</div>
						<div class="d-flex justify-content-between py-1 border-bottom">
							<span>{{ t("Freight & Transport") }}</span>
							<span class="font-monospace fw-semibold text-orange">{{ fm(costOverviewData?.operational?.transport, costOverviewData?.currency) }}</span>
						</div>
						<div class="d-flex justify-content-between py-1 border-bottom">
							<span>{{ t("Port & Insurance") }}</span>
							<span class="font-monospace fw-semibold">{{ fm(costOverviewData?.operational?.other, costOverviewData?.currency) }}</span>
						</div>
						<div class="d-flex justify-content-between py-1 border-bottom">
							<span>
								{{ t("Duties") }}
								<span v-if="costOverviewData?.operational?.duties_estimated" class="badge bg-warning-lt ms-1">{{ t("estimate") }}</span>
							</span>
							<span class="font-monospace fw-semibold">{{ fm(costOverviewData?.operational?.duties, costOverviewData?.currency) }}</span>
						</div>
						<div class="d-flex justify-content-between py-2 fw-bold h4 mb-0 text-primary">
							<span>{{ t("Total operational") }}</span>
							<span class="font-monospace">{{ fm(costOverviewData?.operational?.total, costOverviewData?.currency) }}</span>
						</div>
					</div>

					<div class="col-md-6">
						<h4 class="card-title text-purple mb-2">{{ t("In Accounting") }}</h4>
						<div class="d-flex justify-content-between py-1 border-bottom">
							<span>{{ t("Billed goods") }}</span>
							<span class="font-monospace fw-semibold">{{ fm(costOverviewData?.accounting?.billed_goods, costOverviewData?.currency) }}</span>
						</div>
						<div class="d-flex justify-content-between py-1 border-bottom">
							<span>{{ t("LCV (Landed Cost Vouchers)") }}</span>
							<span class="font-monospace fw-semibold text-purple">{{ fm(costOverviewData?.accounting?.lcv_total, costOverviewData?.currency) }}</span>
						</div>
						<div class="d-flex justify-content-between py-2 fw-bold h4 mb-0 text-purple">
							<span>{{ t("Total accounting") }}</span>
							<span class="font-monospace">{{ fm(costOverviewData?.accounting?.total, costOverviewData?.currency) }}</span>
						</div>
					</div>
				</div>

				<div class="gapbox d-flex align-items-center">
					<i class="ti ti-alert-circle text-purple fs-2 me-2"></i>
					<div>
						<div class="fw-bold text-purple">
							{{ t("Gap {amount} · {per_kg} $/kg not allocated to inventory yet", {
								amount: fm(costOverviewData?.gap?.amount, costOverviewData?.currency),
								per_kg: costOverviewData?.gap?.per_kg || 0
							}) }}
						</div>
					</div>
					<router-link to="/imports/expenses" class="ms-auto btn btn-ghost-primary btn-sm">
						{{ t("Unallocated expenses →") }}
					</router-link>
				</div>
			</div>
		</div>

		<!-- 7 Document Status Strip -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header"><h3 class="card-title"><i class="ti ti-files me-2"></i>{{ t("Document status") }}</h3></div>
			<div class="card-body">
				<div class="row g-2">
					<div class="col">
						<div class="p-2 border rounded text-center">
							<div class="text-secondary small">{{ t("Packing List") }}</div>
							<div class="fw-bold text-success mt-1"><i class="ti ti-check me-1"></i>{{ t("Attached") }}</div>
						</div>
					</div>
					<div class="col">
						<div class="p-2 border rounded text-center">
							<div class="text-secondary small">{{ t("Vet Certificate") }}</div>
							<div class="fw-bold text-success mt-1"><i class="ti ti-check me-1"></i>{{ t("Valid") }}</div>
						</div>
					</div>
					<div class="col">
						<div class="p-2 border rounded text-center">
							<div class="text-secondary small">{{ t("Customs Declaration") }}</div>
							<div v-if="form.customs_declarations?.length" class="fw-bold text-primary mt-1 font-monospace">
								{{ form.customs_declarations[0].name }}
							</div>
							<div v-else class="text-secondary mt-1">—</div>
						</div>
					</div>
					<div class="col">
						<div class="p-2 border rounded text-center">
							<div class="text-secondary small">{{ t("GRN") }}</div>
							<div class="fw-bold text-azure mt-1">{{ t("Received") }}</div>
						</div>
					</div>
					<div class="col">
						<div class="p-2 border rounded text-center">
							<div class="text-secondary small">{{ t("LCV") }}</div>
							<div class="fw-bold text-purple mt-1">{{ costOverviewData?.accounting?.lcv_total ? t("Posted") : t("Pending") }}</div>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- 5 Linked Trucks -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between flex-wrap gap-2">
				<h3 class="card-title m-0"><i class="ti ti-truck me-2"></i>{{ t("Linked Trucks") }}</h3>
				<div class="d-flex align-items-center gap-2 flex-wrap">
					<div style="min-width: 220px">
						<Typeahead
							v-slot="{ item }"
							:search="searchTrucks"
							:placeholder="t('Link an existing truck…')"
							size="sm"
							open-on-focus
							:disabled="linkingTruck"
							@pick="linkTruck"
						>
							<div class="fw-semibold font-monospace">{{ item.truck_number || item.name }}</div>
							<div class="small text-secondary">
								{{ item.status }}
								<span v-if="item.trucking_company"> · {{ item.trucking_company }}</span>
							</div>
						</Typeahead>
					</div>
					<div class="input-group input-group-sm" style="width: 240px">
						<input
							v-model="newTruckNumber"
							type="text"
							class="form-control"
							:placeholder="t('New plate no.')"
							:disabled="linkingTruck"
							@keyup.enter="createTruck"
						/>
						<button
							type="button"
							class="btn btn-outline-secondary"
							:disabled="!newTruckNumber.trim() || linkingTruck"
							@click="createTruck"
						>
							<i class="ti ti-plus"></i>
						</button>
					</div>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter table-hover mb-0">
					<thead>
						<tr>
							<th>{{ t("Truck") }}</th>
							<th>{{ t("Carrier") }}</th>
							<th>{{ t("Driver") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Boxes / kg") }}</th>
							<th class="text-end">{{ t("Transport cost") }}</th>
							<th style="width: 40px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-if="!form.trucks?.length">
							<td colspan="7" class="text-center text-secondary py-3">{{ t("No trucks linked yet.") }}</td>
						</tr>
						<tr
							v-for="trk in form.trucks"
							:key="trk.name"
							style="cursor: pointer"
							@click="router.push('/imports/trucks/' + trk.name)"
						>
							<td class="font-monospace fw-bold text-primary">{{ trk.truck_number || trk.name }}</td>
							<td>{{ trk.trucking_company || "—" }}</td>
							<td>
								{{ trk.driver_name || "—" }}
								<span v-if="trk.driver_phone" class="text-secondary small d-block">{{ trk.driver_phone }}</span>
							</td>
							<td><StatusBadge :status="trk.status" /></td>
							<td class="text-end font-monospace">{{ fn(trk.total_boxes) }} / {{ fn(trk.total_kg) }} kg</td>
							<td class="text-end font-monospace">
								{{ trk.transport_cost === null || trk.transport_cost === undefined ? "—" : fm(trk.transport_cost, trk.transport_currency) }}
							</td>
							<td>
								<button
									type="button"
									class="btn btn-outline-secondary btn-sm p-1"
									:title="t('Unlink truck')"
									:disabled="linkingTruck"
									@click.stop="unlinkTruck(trk)"
								>
									<i class="ti ti-unlink"></i>
								</button>
							</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- 6 Import Expenses (real `Import Expense` records, paid from a real cash desk) -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between flex-wrap gap-2">
				<h3 class="card-title m-0"><i class="ti ti-cash me-2"></i>{{ t("Import Expenses") }}</h3>
				<button type="button" class="btn btn-outline-secondary btn-sm" @click="openExpenseModal">
					<i class="ti ti-plus me-1"></i>{{ t("Add expense") }}
				</button>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter mb-0">
					<thead>
						<tr>
							<th>{{ t("Expense") }}</th>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Description") }}</th>
							<th>{{ t("Category") }}</th>
							<th class="text-end">{{ t("Amount") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("Journal Entry") }}</th>
							<!-- Capitalizing is a cost action: the column follows the same
							     visibility gate the backend enforces on the endpoints. -->
							<th v-if="costVisible">{{ t("Landed cost") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loadingExpenses" :rows="3" :cols="costVisible ? 8 : 7" />
					<tbody v-else>
						<tr v-if="!expenses.length">
							<td :colspan="costVisible ? 8 : 7" class="text-center text-secondary py-3">{{ t("No expenses recorded for this invoice yet.") }}</td>
						</tr>
						<tr v-for="exp in expenses" :key="exp.name">
							<td class="font-monospace fw-bold text-primary">{{ exp.name }}</td>
							<td>{{ formatDate(exp.expense_date) }}</td>
							<td>{{ exp.description || "—" }}</td>
							<td><span class="badge bg-secondary-lt">{{ exp.category || "—" }}</span></td>
							<td class="text-end font-monospace">{{ fm(exp.amount, exp.currency) }}</td>
							<td><StatusBadge :status="exp.status" /></td>
							<td class="font-monospace small">{{ exp.journal_entry || exp.purchase_invoice || "—" }}</td>
							<td v-if="costVisible" class="text-nowrap">
								<template v-if="exp.include_in_landed_cost">
									<span class="badge bg-purple-lt me-1">{{ t(exp.cost_component || "Other") }}</span>
									<button
										type="button"
										class="btn btn-outline-secondary btn-sm"
										:disabled="landedCostBusy === exp.name"
										:title="t('Remove from landed cost')"
										@click="removeLandedCost(exp)"
									>
										<span v-if="landedCostBusy === exp.name" class="spinner-border spinner-border-sm"></span>
										<i v-else class="ti ti-x"></i>
									</button>
								</template>
								<button
									v-else
									type="button"
									class="btn btn-outline-secondary btn-sm"
									:disabled="landedCostBusy === exp.name"
									@click="openLandedCostModal(exp)"
								>
									<i class="ti ti-package-import me-1"></i>{{ t("Capitalize") }}
								</button>
							</td>
						</tr>
					</tbody>
					<tfoot v-if="expenseTotals.length">
						<tr v-for="tot in expenseTotals" :key="tot.currency" class="fw-bold">
							<td colspan="4">{{ t("Total expenses") }}</td>
							<td class="text-end font-monospace">{{ fm(tot.amount, tot.currency) }}</td>
							<td :colspan="costVisible ? 3 : 2"></td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>

		<!-- Logistics Readiness overview sits here -->
		<CiLogisticsOverview
			v-if="!isCreate && form.name"
			:commercial-invoice="form.name"
			:packing-summary="form.packing_summary"
			:grn="form.grn"
			:loading="loading"
			@reload="loadDoc"
		/>

		<!-- 7 Landed cost in UZS — computed server-side from the real cost lines -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between flex-wrap gap-2">
				<h3 class="card-title m-0"><i class="ti ti-calculator me-2"></i>{{ t("Landed cost (UZS)") }}</h3>
				<div class="d-flex align-items-center gap-3 flex-wrap">
					<div class="d-flex align-items-center gap-2">
						<label class="form-label small text-secondary mb-0">{{ t("USD rate") }}</label>
						<div style="width: 130px">
							<MoneyInput
								v-model="usdToUzsRate"
								currency="UZS"
								:language="user.language"
								:max-fraction-digits="2"
								hide-currency
								size="sm"
							/>
						</div>
					</div>
					<div class="d-flex align-items-center gap-2">
						<label class="form-label small text-secondary mb-0">{{ t("Allocation") }}</label>
						<div style="width: 190px">
							<Select
								v-model="allocationMethod"
								:options="allocationOptions"
								size="sm"
								:searchable="false"
							/>
						</div>
					</div>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter mb-0">
					<thead>
						<tr>
							<th>{{ t("Item") }}</th>
							<th class="text-end">{{ t("Weight (kg)") }}</th>
							<th class="text-end">{{ t("Invoice rate") }}</th>
							<th class="text-end">{{ t("Invoice rate (UZS/kg)") }}</th>
							<th class="text-end">{{ t("Allocated costs (UZS/kg)") }}</th>
							<th class="text-end">{{ t("Landed rate (UZS/kg)") }}</th>
							<th class="text-end">{{ t("Line total (UZS)") }}</th>
						</tr>
					</thead>
					<SkeletonRows v-if="loadingLandedCost" :rows="3" :cols="7" />
					<tbody v-else>
						<tr v-if="landedCostRateMissing">
							<td colspan="7" class="text-center text-secondary py-3">
								{{ t("No exchange rate found for this invoice date — landed cost cannot be calculated. Enter a rate above or add the CBU rate.") }}
							</td>
						</tr>
						<tr v-else-if="!uzsLandedTableItems.length">
							<td colspan="7" class="text-center text-secondary py-3">
								{{ t("Nothing to allocate yet — add invoice items and costs first.") }}
							</td>
						</tr>
						<tr v-for="uItem in uzsLandedTableItems" :key="uItem.item">
							<td>
								<div class="fw-semibold">{{ uItem.item }}</div>
								<div v-if="uItem.description" class="small text-secondary">{{ uItem.description }}</div>
							</td>
							<td class="text-end font-monospace">{{ fn(uItem.qty_kg) }}</td>
							<td class="text-end font-monospace">{{ fm(uItem.rate_usd, form.currency) }}</td>
							<td class="text-end font-monospace">{{ fn(uItem.base_rate_uzs) }}</td>
							<td class="text-end font-monospace">{{ fn(uItem.allocated_extra_per_kg_uzs) }}</td>
							<td class="text-end font-monospace fw-bold">{{ fn(uItem.final_landed_rate_per_kg_uzs) }}</td>
							<td class="text-end font-monospace fw-bold">{{ fn(uItem.line_total_landed_uzs) }}</td>
						</tr>
					</tbody>
					<tfoot v-if="uzsLandedTableItems.length">
						<tr class="fw-bold">
							<td>{{ t("Total") }}</td>
							<td class="text-end font-monospace">{{ fn(landedTotalKg) }}</td>
							<td class="text-end">—</td>
							<td class="text-end">—</td>
							<td class="text-end font-monospace">{{ fn(totalExtraUzs) }}</td>
							<td class="text-end font-monospace">{{ fn(avgUzsLandedRatePerKg) }}</td>
							<td class="text-end font-monospace">{{ fn(totalUzsLandedCostSum) }}</td>
						</tr>
					</tfoot>
				</table>
			</div>
			<div class="card-footer text-secondary small">
				{{ t("Allocated costs come from this invoice's container cost lines and recorded import expenses — the columns are empty until those exist.") }}
			</div>
		</div>

		<!-- Import expense — paid out of a real cash desk, posted as a real Bank Entry -->
		<div v-if="showExpenseModal" class="modal d-block" tabindex="-1" style="background: rgba(0, 0, 0, 0.4)">
			<div class="modal-dialog modal-dialog-centered modal-lg">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Add import expense") }}</h5>
						<button type="button" class="btn-close" @click="closeExpenseModal"></button>
					</div>
					<div class="modal-body">
						<div class="row g-3 mb-3">
							<div class="col-md-4">
								<label class="form-label">{{ t("Commercial Invoice") }}</label>
								<input type="text" :value="form.ci_number || form.name" readonly class="form-control font-monospace" />
							</div>
							<div class="col-md-4">
								<label class="form-label required">{{ t("Category") }}</label>
								<Select v-model="expenseForm.category" :options="expenseCategoryOptions" :searchable="false" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Expense date") }}</label>
								<DateInput v-model="expenseForm.expense_date" />
							</div>
						</div>

						<div class="row g-3 mb-3">
							<div class="col-md-6">
								<label class="form-label">{{ t("Description") }}</label>
								<input v-model="expenseForm.description" type="text" class="form-control" />
							</div>
							<div class="col-md-3">
								<label class="form-label">{{ t("Reference no.") }}</label>
								<input v-model="expenseForm.invoice_reference" type="text" class="form-control" />
							</div>
							<div class="col-md-3">
								<label class="form-label">{{ t("Currency") }}</label>
								<input
									type="text"
									class="form-control font-monospace"
									readonly
									:value="expenseCurrency || '—'"
									:placeholder="t('Pick a cash desk first')"
								/>
								<span class="form-hint">{{ t("Taken from the cash desk — never chosen by hand.") }}</span>
							</div>
						</div>

						<div class="row g-3 mb-3">
							<div class="col-md-6">
								<label class="form-label required">{{ t("Paid from (cash desk)") }}</label>
								<Select
									v-model="expenseForm.paid_from_account"
									:options="payAccounts"
									value-key="name"
									label-key="account_name"
									:disabled="loadingAccounts"
									:placeholder="loadingAccounts ? t('Loading…') : t('Select a cash desk')"
									:search-keys="['account_name', 'account_number', 'name']"
								>
									<template #option="{ item }">
										<div class="d-flex justify-content-between gap-3">
											<span>{{ accountLabel(item) }} <span class="text-secondary">({{ item.account_currency }})</span></span>
											<span class="font-monospace text-secondary">{{ fm(item.account_balance, item.account_currency) }}</span>
										</div>
									</template>
									<template #selected="{ item }">
										{{ accountLabel(item) }} ({{ item.account_currency }})
									</template>
								</Select>
							</div>
							<div class="col-md-6">
								<label class="form-label required">{{ t("Expense account") }}</label>
								<Select
									v-model="expenseForm.expense_account"
									:options="expenseAccounts"
									value-key="name"
									label-key="account_name"
									:disabled="loadingAccounts"
									:placeholder="loadingAccounts ? t('Loading…') : t('Select an expense account')"
									:search-keys="['account_name', 'account_number', 'name']"
								>
									<template #option="{ item }">
										{{ accountLabel(item) }} <span class="text-secondary">({{ item.account_currency }})</span>
									</template>
									<template #selected="{ item }">
										{{ accountLabel(item) }} ({{ item.account_currency }})
									</template>
								</Select>
							</div>
						</div>

						<div class="row g-3 mb-3">
							<div class="col-md-4">
								<label class="form-label required">{{ t("Amount") }}</label>
								<MoneyInput
									v-model="expenseForm.amount"
									:currency="expenseCurrency || form.currency"
									:language="user.language"
									hide-currency
								/>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Container") }}</label>
								<Select
									v-model="expenseForm.container"
									:options="expenseContainerOptions"
									clearable
									:placeholder="t('Whole invoice')"
								/>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Truck") }}</label>
								<Select
									v-model="expenseForm.truck"
									:options="expenseTruckOptions"
									clearable
									:placeholder="t('Whole invoice')"
								/>
							</div>
						</div>

						<div v-if="expenseCurrencyMismatch" class="alert alert-warning mb-0">
							<i class="ti ti-alert-triangle me-1"></i>
							{{ t("The expense account and the cash desk are in different currencies. Pick an account in {currency}.", { currency: expenseCurrency }) }}
						</div>
						<div v-else class="text-secondary small">
							{{ t("Saving posts a Journal Entry that takes the money out of the selected cash desk.") }}
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" :disabled="savingExpense" @click="closeExpenseModal">
							{{ t("Cancel") }}
						</button>
						<button type="button" class="btn btn-primary" :disabled="savingExpense || !canSaveExpense" @click="saveImportExpense">
							<span v-if="savingExpense" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>{{ t("Record expense") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Landed cost component picker. Which component the expense lands on is
		     the only decision the operator makes here — every rule (visibility,
		     valuation account, currency, already-vouchered) is enforced server-side. -->
		<div v-if="showLandedCostModal" class="modal d-block" tabindex="-1" style="background: rgba(0, 0, 0, 0.4)">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Add to landed cost") }}</h5>
						<button type="button" class="btn-close" @click="closeLandedCostModal"></button>
					</div>
					<div class="modal-body">
						<div class="mb-3">
							<label class="form-label required">{{ t("Cost component") }}</label>
							<Select v-model="landedCostComponent" :options="costComponentOptions" :searchable="false" />
						</div>
						<div class="text-secondary small">
							{{ t("The expense is split across this invoice's containers and added to their cost lines.") }}
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" :disabled="!!landedCostBusy" @click="closeLandedCostModal">
							{{ t("Cancel") }}
						</button>
						<button type="button" class="btn btn-primary" :disabled="!!landedCostBusy" @click="confirmLandedCost">
							<span v-if="landedCostBusy" class="spinner-border spinner-border-sm me-1"></span>
							<i v-else class="ti ti-package-import me-1"></i>{{ t("Capitalize") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Destructive actions sit at the bottom, away from Save -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-body d-flex flex-wrap align-items-center gap-2">
				<div class="text-secondary small flex-grow-1">
					{{ t("Deleting shows everything that depends on this invoice before anything is removed.") }}
				</div>
				<button
					v-if="form.custom_proforma_invoice"
					type="button"
					class="btn btn-outline-secondary"
					:disabled="unlinking"
					@click="unlinkProforma"
				>
					<span v-if="unlinking" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-unlink me-1"></i>{{ t("Unlink proforma") }}
				</button>
				<button type="button" class="btn btn-outline-danger" :disabled="deletePlanning" @click="openDeletePlan">
					<span v-if="deletePlanning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-trash me-1"></i>{{ t("Delete") }}
				</button>
			</div>
		</div>

		<!-- What deleting this invoice would touch — shown before anything happens -->
		<div v-if="deleteModalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
			<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Delete commercial invoice") }}</h5>
						<button type="button" class="btn-close" @click="deleteModalOpen = false"></button>
					</div>
					<div class="modal-body">
						<div v-if="deleteBlockers.length" class="mb-3">
							<div class="fw-semibold text-danger mb-2">
								<i class="ti ti-alert-triangle me-1"></i>{{ t("This cannot be deleted yet:") }}
							</div>
							<ul class="list-unstyled mb-0">
								<li v-for="(b, i) in deleteBlockers" :key="i" class="mb-2">
									<router-link
										v-if="recordRoute(b.doctype, b.name)"
										:to="recordRoute(b.doctype, b.name)"
										class="font-monospace fw-semibold"
									>{{ b.name }}</router-link>
									<span v-else class="font-monospace fw-semibold">{{ b.name }}</span>
									<div class="small text-danger">{{ blockerText(b) }}</div>
								</li>
							</ul>
						</div>

						<div v-if="deleteCascadeRows.length" class="mb-3">
							<div class="fw-semibold mb-2">{{ t("These linked records go with it:") }}</div>
							<ul class="list-unstyled mb-0">
								<li v-for="row in deleteCascadeRows" :key="row.doctype" class="mb-2">
									<div class="small text-secondary">
										{{ row.label }} · {{ row.detach ? t("link removed, record kept") : t("deleted") }}
									</div>
									<div>
										<template v-for="(n, i) in row.names" :key="n">
											<router-link
												v-if="recordRoute(row.doctype, n)"
												:to="recordRoute(row.doctype, n)"
												class="font-monospace"
											>{{ n }}</router-link>
											<span v-else class="font-monospace">{{ n }}</span>
											<span v-if="i < row.names.length - 1">, </span>
										</template>
									</div>
								</li>
							</ul>
							<label class="form-check mt-2">
								<input v-model="deleteCascade" class="form-check-input" type="checkbox">
								<span class="form-check-label">{{ t("Also delete the linked records") }}</span>
							</label>
						</div>

						<div v-if="!deleteBlockers.length && !deleteCascadeRows.length" class="text-secondary">
							{{ t("Nothing else points at this invoice.") }}
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" @click="deleteModalOpen = false">{{ t("Cancel") }}</button>
						<button
							type="button"
							class="btn btn-danger"
							:disabled="!canDelete || deleting"
							:title="deleteBlockers.length ? blockerText(deleteBlockers[0]) : ''"
							@click="confirmDelete"
						>
							<span v-if="deleting" class="spinner-border spinner-border-sm me-1"></span>{{ t("Delete") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Smart Fill from PIs — allocate boxes across every open proforma of this supplier -->
		<div v-if="multiPiModalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
			<div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title"><i class="ti ti-wand me-2"></i>{{ t("Smart Fill from PIs") }}</h5>
						<button type="button" class="btn-close" @click="multiPiModalOpen = false"></button>
					</div>
					<!-- Step 1 — which proformas to pull from -->
					<div v-if="multiPiStep === 1" class="modal-body">
						<div class="d-flex justify-content-between align-items-center mb-2">
							<div class="fw-semibold">{{ t("Step 1: Select Proforma Invoices") }}</div>
							<div class="btn-list">
								<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="multiPiLoading || multiPiAllSelected" @click="multiPiSelectAll(true)">
									{{ t("Select All") }}
								</button>
								<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="multiPiLoading || !multiPiSelected.length" @click="multiPiSelectAll(false)">
									{{ t("Deselect All") }}
								</button>
							</div>
						</div>
						<table class="table table-sm table-vcenter align-middle mb-0">
							<thead>
								<tr>
									<th style="width: 40px"></th>
									<th style="min-width: 160px">{{ t("Ref PI") }}</th>
									<th style="min-width: 120px">{{ t("PI date") }}</th>
								</tr>
							</thead>
							<SkeletonRows v-if="multiPiLoading" :rows="5" :cols="3" />
							<tbody v-else>
								<tr v-if="!multiPiProformas.length">
									<td colspan="3" class="text-secondary text-center py-3">{{ t("No open proforma invoices for this supplier.") }}</td>
								</tr>
								<tr v-for="pi in multiPiProformas" :key="pi.name">
									<td>
										<input :id="`multi-pi-${pi.name}`" v-model="multiPiSelected" type="checkbox" class="form-check-input m-0" :value="pi.name">
									</td>
									<td>
										<label class="form-check-label mb-0" :for="`multi-pi-${pi.name}`">
											<span class="badge bg-blue-lt font-monospace" style="font-size: 0.75rem">{{ pi.supplier_pi_ref || pi.name }}</span>
										</label>
									</td>
									<td class="text-secondary">{{ pi.pi_date ? formatDate(pi.pi_date) : "—" }}</td>
								</tr>
							</tbody>
						</table>
					</div>

					<!-- Step 2 — allocate boxes across the selected proformas' lines -->
					<div v-else class="modal-body">
						<div class="d-flex justify-content-between align-items-center mb-2">
							<div class="fw-semibold">
								{{ t("Step 2: Allocate Line Items") }}
								<span v-if="multiPiHiddenCount" class="small fw-normal text-secondary ms-2">
									{{ t("{count} fully shipped lines hidden", { count: multiPiHiddenCount }) }}
								</span>
							</div>
							<div class="btn-list">
								<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="multiPiLoading || multiPiAllLinesSelected" @click="multiPiSelectAllLines(true)">
									{{ t("Select All") }}
								</button>
								<button type="button" class="btn btn-sm btn-outline-secondary" :disabled="multiPiLoading || !multiPiPickedKeys.length" @click="multiPiSelectAllLines(false)">
									{{ t("Deselect All") }}
								</button>
							</div>
						</div>
						<!-- Exactly what Apply is about to push — same arithmetic, same gate. -->
						<div class="card card-sm mb-2">
							<div class="card-body py-2 d-flex flex-wrap align-items-center gap-3">
								<div>
									<span class="text-secondary small me-1">{{ t("Lines selected") }}:</span>
									<span class="fw-semibold font-monospace">{{ multiPiSummary.lines }}</span>
								</div>
								<div>
									<span class="text-secondary small me-1">{{ t("Total boxes") }}:</span>
									<span class="fw-semibold font-monospace">{{ fn(multiPiSummary.boxes) }}</span>
								</div>
								<div>
									<span class="text-secondary small me-1">{{ t("Total kg") }}:</span>
									<span class="fw-semibold font-monospace">{{ fn(multiPiSummary.qty) }}</span>
								</div>
								<div class="ms-auto">
									<span class="text-secondary small me-1">{{ t("Total agreed value") }}:</span>
									<span class="fw-semibold font-monospace">{{ fm(multiPiSummary.value, form.currency) }}</span>
								</div>
							</div>
						</div>
						<!-- The (PI, category) pools, read-only. These are the numbers the server
						     guard enforces; the table below lists the contract lines the bundle was
						     booked as, and they share this one balance. It sits above the table so
						     the rows are nothing but the product lines the user picks from. -->
						<div v-if="!multiPiLoading && multiPiOpenLines.length" class="d-flex flex-column gap-1 mb-2">
							<div v-for="line in multiPiOpenLines" :key="multiPiKey(line)" class="border rounded px-2 py-1">
								<div class="d-flex flex-wrap align-items-center gap-2">
									<span class="badge bg-blue-lt font-monospace" style="font-size: 0.75rem">{{ line.pi_ref || line.pi_name }}</span>
									<span class="fw-semibold">{{ line.category || "—" }}</span>
									<span v-if="line.description" class="small text-secondary">{{ line.description }}</span>
									<span class="badge bg-secondary-lt">{{ t("{count} PI lines", { count: multiPiGroupRows(line).length }) }}</span>
									<span class="small text-secondary ms-auto">
										{{ t("Contract") }}: <span class="font-monospace text-body">{{ fn(line.contract_boxes) }}</span>
									</span>
									<span class="small text-secondary">
										{{ t("Shipped") }}: <span class="font-monospace text-body">{{ fn(line.shipped_boxes) }}</span>
										<span v-if="line.ci_count">/ {{ line.ci_count }} CI</span>
									</span>
									<span class="small text-secondary">
										{{ t("Remaining") }}:
										<span v-if="line.over_shipped" class="badge bg-red-lt" :title="t('Shipped more than the contract allows')">
											−{{ fn(line.over_boxes) }} · {{ t("Over-shipped") }}
										</span>
										<span v-else class="font-monospace fw-semibold text-body">{{ fn(line.remaining_boxes) }}</span>
									</span>
									<span class="small text-secondary">
										{{ t("Allocated") }}:
										<span class="font-monospace text-body">{{ fn(multiPiGroupAllocated(line)) }} / {{ fn(poolRemaining(line)) }}</span>
									</span>
									<span v-if="!poolRemaining(line)" class="small text-secondary">{{ t("This category pool has no boxes left.") }}</span>
								</div>
								<div v-if="line.sub_cuts && line.sub_cuts.length" class="mt-1">
									<span class="small text-secondary me-2">{{ t("Already shipped as") }}:</span>
									<span v-for="sc in line.sub_cuts" :key="sc.item" class="badge bg-secondary-lt me-1 font-monospace" style="font-size: 0.7rem">
										{{ sc.item || "—" }} · {{ fn(sc.boxes) }}
									</span>
								</div>
							</div>
						</div>
						<div class="table-responsive">
						<table class="table table-sm table-vcenter align-middle mb-0">
							<thead>
								<tr>
									<th style="width: 40px">
										<input
											type="checkbox"
											class="form-check-input m-0"
											:aria-label="t('Select All')"
											:title="t('Select All')"
											:checked="multiPiAllLinesSelected"
											:indeterminate.prop="multiPiSomeLinesSelected"
											:disabled="!multiPiRows.length"
											@change="multiPiSelectAllLines($event.target.checked)"
										>
									</th>
									<th style="min-width: 130px">{{ t("Ref PI") }}</th>
									<th style="min-width: 180px">{{ t("PI product") }}</th>
									<th style="min-width: 150px">{{ t("Product Code/Name") }}</th>
									<th class="text-end" style="width: 100px">{{ t("Contract") }}</th>
									<th class="text-end" style="width: 100px">{{ t("Shipped") }}</th>
									<th class="text-end" style="width: 110px">{{ t("Remaining") }}</th>
									<th class="text-end" style="width: 130px">{{ t("Allocate boxes") }}</th>
								</tr>
							</thead>
							<SkeletonRows v-if="multiPiLoading" :rows="6" :cols="8" />
							<tbody v-else>
								<!-- "Nothing came back" and "everything that came back is already
								     shipped" are different answers, and only the second one tells the
								     user their proformas are done rather than their filter is wrong. -->
								<tr v-if="!multiPiRows.length">
									<td colspan="8" class="text-secondary text-center py-3">
										{{ multiPiLines.length ? t("Every line of the selected proformas is already fully shipped.") : t("No open proforma lines for this supplier.") }}
									</td>
								</tr>
								<!-- Index-based DOM id on purpose: a match key holds the PI name and the category
								     verbatim, so an id built from it carried "::" and spaces — legal for <label for>
								     but unaddressable by any CSS/querySelector id selector, which QA tooling needs. -->
								<tr v-for="row in multiPiRows" :key="row.key">
									<td>
										<input
											:id="`multi-pi-line-${row.lineIdx}-${row.childIdx}`"
											type="checkbox"
											class="form-check-input m-0"
											:checked="multiPiPickedKeys.includes(row.key)"
											@change="multiPiToggleRow(row, $event.target.checked)"
										>
									</td>
									<td>
										<!-- The PI badge lives on the row now that the group header is gone:
										     on a multi-PI load there is nothing else saying which proforma
										     this contract line belongs to. -->
										<label class="form-check-label mb-0" :for="`multi-pi-line-${row.lineIdx}-${row.childIdx}`" :title="t('Contract line')">
											<span class="badge bg-blue-lt font-monospace" style="font-size: 0.75rem">{{ row.line.pi_ref || row.line.pi_name }}</span>
										</label>
									</td>
									<td>
										<div class="fw-semibold">{{ row.child.item || "—" }}</div>
										<div v-if="row.child.description" class="small text-secondary">{{ row.child.description }}</div>
									</td>
									<td>
										<select v-model="multiPiItems[row.key]" class="form-select form-select-sm">
											<option v-for="code in multiPiRowItemOptions(row.line, row.child)" :key="code" :value="code">{{ code }}</option>
										</select>
									</td>
									<td class="text-end font-monospace">{{ fn(row.child.boxes) }}</td>
									<td
										class="text-end font-monospace text-secondary"
										:title="t('Shipped as this cut') + ' — ' + t('Indicative only — shipments are tracked per category')"
									>
										{{ rowShippedAsThisCut(row.line, row.child) ? fn(rowShippedAsThisCut(row.line, row.child)) : "—" }}
									</td>
									<td class="text-end font-monospace">{{ fn(rowContractRemaining(row.line, row.child)) }}</td>
									<td class="text-end">
										<input
											:value="multiPiAllocations[row.key]"
											type="number"
											min="0"
											:max="maxAllocatable(row)"
											step="1"
											inputmode="decimal"
											class="form-control form-control-sm text-end font-monospace"
											@input="setAllocation(row, $event)"
										>
									</td>
								</tr>
							</tbody>
						</table>
						</div>
					</div>
					<div v-if="multiPiStep === 1" class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" @click="multiPiModalOpen = false">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="multiPiLoading || !multiPiSelected.length" @click="loadMultiPiLines">
							{{ t("Load Available Lines") }}
						</button>
					</div>
					<div v-else class="modal-footer">
						<button type="button" class="btn btn-ghost-secondary me-auto" :disabled="multiPiLoading" @click="multiPiStep = 1">
							<i class="ti ti-arrow-left me-1"></i>{{ t("Back to PI selection") }}
						</button>
						<button type="button" class="btn btn-outline-secondary" @click="multiPiModalOpen = false">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="multiPiLoading || !multiPiSummary.lines" @click="applyMultiPiAllocation">
							{{ t("Apply") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Transport Purchase Invoice Link / Create Modal -->
		<div v-if="showTransportModal" class="modal d-block" tabindex="-1" style="background: rgba(0, 0, 0, 0.4)">
			<div class="modal-dialog modal-dialog-centered modal-lg">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">
							<i class="ti ti-truck me-2 text-primary"></i>{{ t("Transport Purchase Invoice") }}
						</h5>
						<button type="button" class="btn-close" @click="closeTransportModal"></button>
					</div>
					<div class="modal-body">
						<ul class="nav nav-tabs mb-3">
							<li class="nav-item">
								<a
									class="nav-link"
									:class="{ active: transportModalTab === 'existing' }"
									href="#"
									@click.prevent="openTransportModal('existing')"
								>
									<i class="ti ti-link me-1"></i>{{ t("Link existing invoice") }}
								</a>
							</li>
							<li class="nav-item">
								<a
									class="nav-link"
									:class="{ active: transportModalTab === 'new' }"
									href="#"
									@click.prevent="openTransportModal('new')"
								>
									<i class="ti ti-plus me-1"></i>{{ t("Create new transport invoice") }}
								</a>
							</li>
						</ul>

						<!-- Tab 1: Existing Invoices -->
						<div v-if="transportModalTab === 'existing'">
							<div class="input-icon mb-3">
								<span class="input-icon-addon"><i class="ti ti-search"></i></span>
								<input
									v-model="linkableSearch"
									type="text"
									class="form-control"
									:placeholder="t('Search by bill number, supplier or invoice ID…')"
									@input="fetchLinkableInvoices"
								/>
							</div>

							<div v-if="loadingLinkableInvoices" class="py-4 text-center text-secondary">
								<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Loading invoices…") }}
							</div>
							<div v-else class="table-responsive" style="max-height: 350px; overflow-y: auto;">
								<table class="table table-sm table-hover align-middle mb-0">
									<thead class="table-light sticky-top">
										<tr>
											<th>{{ t("Bill No") }}</th>
											<th>{{ t("Supplier") }}</th>
											<th>{{ t("Date") }}</th>
											<th class="text-end">{{ t("Amount") }}</th>
											<th>{{ t("Account") }}</th>
											<th>{{ t("Status") }}</th>
											<th style="width: 80px">{{ t("Action") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-if="!linkableInvoices.length">
											<td colspan="7" class="text-center text-secondary py-3">
												{{ t("No linkable transport invoices found.") }}
											</td>
										</tr>
										<tr v-for="inv in linkableInvoices" :key="inv.name">
											<td>
												<div class="fw-bold font-monospace text-primary">{{ inv.bill_no || inv.name }}</div>
												<div class="small text-secondary font-monospace">{{ inv.name }}</div>
											</td>
											<td>{{ inv.supplier_name || inv.supplier }}</td>
											<td>{{ inv.posting_date ? formatDate(inv.posting_date) : '—' }}</td>
											<td class="text-end font-monospace fw-semibold">{{ fm(inv.grand_total, inv.currency) }}</td>
											<td>
												<span v-if="inv.is_landed_cost_account" class="badge bg-success-lt" :title="inv.expense_account">
													{{ t("Landed Cost") }}
												</span>
												<span v-else class="badge bg-warning-lt" :title="inv.expense_account">
													{{ t("P&L") }}
												</span>
											</td>
											<td>
												<span class="badge" :class="getStatusBadgeClass('Purchase Invoice', inv.status)">{{ inv.status }}</span>
											</td>
											<td>
												<button
													v-if="!inv.is_linked"
													type="button"
													class="btn btn-primary btn-sm"
													:disabled="linkingInvoiceName === inv.name"
													@click="handleLinkInvoice(inv)"
												>
													<span v-if="linkingInvoiceName === inv.name" class="spinner-border spinner-border-sm me-1"></span>
													{{ t("Link") }}
												</button>
												<span v-else class="badge bg-success-lt">{{ t("Linked") }}</span>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>

						<!-- Tab 2: Create New Transport Invoice -->
						<div v-else-if="transportModalTab === 'new'">
							<div class="alert alert-info py-2 px-3 small mb-3">
								<i class="ti ti-info-circle me-1"></i>
								{{ t("This invoice will be created with the Landed Cost clearing expense account (Balance Sheet) so it capitalizes into inventory and does not hit P&L.") }}
							</div>
							<div class="row g-3">
								<div class="col-md-6">
									<label class="form-label required">{{ t("Supplier / Carrier") }}</label>
									<Typeahead
										v-model="newTransportForm.supplier"
										:search="searchSuppliers"
										:display="newTransportForm.supplier_name"
										:placeholder="t('Search carrier…')"
										@pick="pickTransportSupplier"
									>
										<template #item="{ item }">
											<div class="fw-semibold">{{ item.supplier_name || item.name }}</div>
											<div class="small text-secondary">{{ item.name }}</div>
										</template>
									</Typeahead>
								</div>
								<div class="col-md-6">
									<label class="form-label required">{{ t("Amount") }}</label>
									<MoneyInput
										v-model="newTransportForm.amount"
										:currency="newTransportForm.currency"
										:language="user.language"
									/>
								</div>
								<div class="col-md-4">
									<label class="form-label">{{ t("Currency") }}</label>
									<Select
										v-model="newTransportForm.currency"
										:options="currencyOptions"
										:searchable="false"
									/>
								</div>
								<div class="col-md-4">
									<label class="form-label">{{ t("Bill No (Fatura No)") }}</label>
									<input
										v-model="newTransportForm.bill_no"
										type="text"
										class="form-control"
										:placeholder="t('e.g. TRK-2026-001')"
									/>
								</div>
								<div class="col-md-4">
									<label class="form-label">{{ t("Posting Date") }}</label>
									<DateInput v-model="newTransportForm.posting_date" />
								</div>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" @click="closeTransportModal">
							{{ t("Close") }}
						</button>
						<button
							v-if="transportModalTab === 'new'"
							type="button"
							class="btn btn-primary"
							:disabled="creatingTransportInvoice || !newTransportForm.supplier || Number(newTransportForm.amount) <= 0"
							@click="handleCreateTransportInvoice"
						>
							<span v-if="creatingTransportInvoice" class="spinner-border spinner-border-sm me-1"></span>
							{{ t("Create & Link to CI") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
