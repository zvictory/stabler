<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
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
import ParentBulkPaymentDialog from "../../components/ParentBulkPaymentDialog.vue";
import ParentReallocateDialog from "../../components/ParentReallocateDialog.vue";
import NewDirectInvoiceModal from "../../components/NewDirectInvoiceModal.vue";
import BalanceChip from "../../components/BalanceChip.vue";
import PartyAvatar from "../../components/PartyAvatar.vue";
import ApexChart from "../../components/ApexChart.vue";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useListViewState } from "../../composables/useListViewState.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";

const session = useSession();
const route = useRoute();
const router = useRouter();
const { activeCompany, user } = storeToRefs(session);
// Direct (order-less) sales invoices are an imports-module capability.
const directInvoiceEnabled = computed(() => session.canAccessModule("imports"));

const { confirm } = useConfirm();
const toast = useToast();

const loading = ref(false);
const error = ref("");
const customers = ref([]);
const companyCurrency = ref("");

// Persistent list state: URL ↔ localStorage (URL = source of truth).
const { search, onlyWithBalance, onlyOverdue, filterGroup, filterTerritory, sortField, sortAsc, c: selectedName } = useListViewState(
	"stabler.customers.listState",
	{ search: "", filterGroup: "", filterTerritory: "", onlyWithBalance: false, onlyOverdue: false, sortField: "name", sortAsc: true, c: "" }
);

const selected = ref(null);
const selectedDetail = ref(null);

// ESC → deselect the open customer first (clear the right pane), else go back.
useEscapeBack(() => {
	if (selected.value) {
		selected.value = null;
		selectedName.value = ""; // composable clears c from URL + localStorage
		return true;
	}
	return false;
}, "/sales");
const recentInvoices = ref([]);
const ledger = ref(null);
const ledgerLoading = ref(false);
const ledgerError = ref("");
const ledgerFromDate = ref("");
const ledgerToDate = ref("");
const ledgerTypeFilter = ref("");
const ledgerSearch = ref("");
const ledgerSortAsc = ref(false); // newest date first by default

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
const bulkPayOpen = ref(false);
const reallocateOpen = ref(false);
const directInvoiceOpen = ref(false);
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
		parent_customer: "",
		job_status: "",
	};
}
const form = ref(blankCustomer());

const currency = computed(() => companyCurrency.value || session.currency);

// Sorting & Filtering for Master List — provided by useListViewState above.

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

// Master-list rows are built by `visibleRows` (flat/search or tree). Sorting and
// filtering live in `sortCustomerList` / `visibleRows` below.

function toggleSort(field) {
	if (sortField.value === field) {
		sortAsc.value = !sortAsc.value;
	} else {
		sortField.value = field;
		sortAsc.value = true;
	}
}

// Footer totals. Three rules this has to respect, and the old one-liner broke
// all three:
//   1. It summed `customers` (the raw API page) while the table renders
//      `visibleRows`, so picking a group or territory shrank the list but left
//      the total unchanged.
//   2. It summed `balance_base` while the rows show `balance_acc`, so in a
//      multi-currency tenant the column and the footer could never agree.
//      CLAUDE.md forbids base-currency conversion, so we group by currency.
//   3. Tree mode renders a parent row (cumulative) AND its children as separate
//      rows; summing what is on screen would count children twice. We sum OWN
//      balances only, and off the flat filtered set so expanding a parent does
//      not move the total.
const filteredCustomers = computed(() => {
	let list = customers.value;
	if (filterGroup.value) list = list.filter((c) => c.customer_group === filterGroup.value);
	if (filterTerritory.value) list = list.filter((c) => c.territory === filterTerritory.value);
	return list;
});

const visibleTotals = computed(() => {
	const byCurrency = new Map();
	for (const c of filteredCustomers.value) {
		const amount = Number(c.balance_acc ?? c.balance_base ?? 0);
		if (!amount) continue;
		const cur = c.account_currency || currency.value;
		byCurrency.set(cur, (byCurrency.get(cur) || 0) + amount);
	}
	return [...byCurrency.entries()].map(([cur, amount]) => ({ currency: cur, amount }));
});

// The server caps the page at `limit`. When it bites, the footer describes a
// slice of the book — say so instead of silently under-reporting.
// `truncated` comes from the server, decided before its only_with_balance /
// only_overdue filters thin the page out. Deriving it here as
// `totalCount > customers.length` would misread a filtered-but-complete list as
// a capped one and raise the warning badge over a total that is actually right.
const totalCount = ref(0);
const listTruncated = ref(false);

// Book-wide total for the server-side filter, unaffected by `limit`. Only shown
// when the page IS capped: otherwise the footer above already IS the whole book,
// and a second (drift-uncorrected) figure next to it would just look like a
// rounding disagreement. Group/territory/overdue narrow the set client-side, so
// the server figure would not match what is on screen — hide it for those too.
const grandTotals = ref([]);
const showGrandTotals = computed(
	() =>
		listTruncated.value &&
		grandTotals.value.length > 0 &&
		!onlyOverdue.value &&
		!filterGroup.value &&
		!filterTerritory.value
);

// --- Parent/child hierarchy (QuickBooks-style, single level) ----------------
// Auto-detected from the API (has_hierarchy). Tree mode groups children under
// their parent; parent rows show the CUMULATIVE (own + children) balance from a
// server-side, GL-accurate rollup map. Tenants without the field see flat mode.
const hasHierarchy = ref(false);
const HKEY_VIEW = "stabler.customers.viewMode";
const HKEY_EXPANDED = "stabler.customers.expanded";
const viewMode = ref(localStorage.getItem(HKEY_VIEW) === "flat" ? "flat" : "tree");
const childrenBalBase = ref({});
const childrenBalAcc = ref({});
const expanded = ref(loadExpanded());

function loadExpanded() {
	try {
		return JSON.parse(localStorage.getItem(HKEY_EXPANDED) || "{}") || {};
	} catch {
		return {};
	}
}
watch(viewMode, (v) => localStorage.setItem(HKEY_VIEW, v));
function toggleView() {
	viewMode.value = viewMode.value === "tree" ? "flat" : "tree";
}
function isExpanded(name) {
	return !!expanded.value[name];
}
function toggleExpand(name) {
	expanded.value = { ...expanded.value, [name]: !expanded.value[name] };
	localStorage.setItem(HKEY_EXPANDED, JSON.stringify(expanded.value));
}

const nameToCustomer = computed(() => {
	const m = {};
	for (const c of customers.value) m[c.name] = c;
	return m;
});
const childrenByParent = computed(() => {
	const m = {};
	for (const c of customers.value) {
		if (c.parent_customer) (m[c.parent_customer] ||= []).push(c);
	}
	return m;
});
const isSearching = computed(() => !!(search.value || "").trim());
const treeMode = computed(
	() => hasHierarchy.value && viewMode.value === "tree" && !isSearching.value
);

function ownBalanceOf(c) {
	return Number(c?.balance_acc ?? c?.balance_base ?? 0);
}
function rowIsParent(c) {
	return (childrenByParent.value[c.name] || []).length > 0;
}
function cumulativeAccOf(name) {
	return ownBalanceOf(nameToCustomer.value[name]) + Number(childrenBalAcc.value[name] || 0);
}

function sortCustomerList(list, useCumulative) {
	if (sortField.value === "name") {
		return [...list].sort((a, b) => {
			const cmp = (a.customer_name || "").localeCompare(b.customer_name || "");
			return sortAsc.value ? cmp : -cmp;
		});
	}
	if (sortField.value === "balance") {
		return [...list].sort((a, b) => {
			const av = useCumulative && rowIsParent(a) ? cumulativeAccOf(a.name) : ownBalanceOf(a);
			const bv = useCumulative && rowIsParent(b) ? cumulativeAccOf(b.name) : ownBalanceOf(b);
			return sortAsc.value ? av - bv : bv - av;
		});
	}
	return list;
}

// Unified row list the master table renders — flat entries in flat/search mode,
// parents + expanded children in tree mode. Each entry: { key, c, level,
// isParent, childCount, parentName }.
const visibleRows = computed(() => {
	if (!treeMode.value) {
		let list = customers.value;
		if (filterGroup.value) list = list.filter((c) => c.customer_group === filterGroup.value);
		if (filterTerritory.value) list = list.filter((c) => c.territory === filterTerritory.value);
		list = sortCustomerList(list, false);
		return list.map((c) => ({
			key: c.name,
			c,
			level: 0,
			isParent: false,
			childCount: 0,
			parentName: c.parent_customer
				? nameToCustomer.value[c.parent_customer]?.customer_name || c.parent_customer
				: "",
		}));
	}
	let tops = customers.value.filter((c) => !c.parent_customer);
	if (filterGroup.value) tops = tops.filter((c) => c.customer_group === filterGroup.value);
	if (filterTerritory.value) tops = tops.filter((c) => c.territory === filterTerritory.value);
	const out = [];
	for (const p of sortCustomerList(tops, true)) {
		const kids = childrenByParent.value[p.name] || [];
		const isParent = kids.length > 0;
		out.push({ key: p.name, c: p, level: 0, isParent, childCount: kids.length, parentName: "" });
		if (isParent && isExpanded(p.name)) {
			for (const k of sortCustomerList(kids, false)) {
				out.push({ key: k.name, c: k, level: 1, isParent: false, childCount: 0, parentName: "" });
			}
		}
	}
	return out;
});

function rowBalanceValue(row) {
	return row.isParent ? cumulativeAccOf(row.c.name) : ownBalanceOf(row.c);
}
function rowBalanceCurrency(row) {
	return rowBalanceValue(row) ? row.c.account_currency || currency.value : currency.value;
}
function rowCumulativeTooltip(row) {
	if (!row.isParent) return "";
	const cur = row.c.account_currency || currency.value;
	const own = formatMoney(ownBalanceOf(row.c), cur, user.value.language);
	const kids = formatMoney(Number(childrenBalAcc.value[row.c.name] || 0), cur, user.value.language);
	return `${t("Own")}: ${own} · ${t("Children")}: ${kids}`;
}

async function loadChildrenBalanceMap() {
	try {
		const res = await call("stabler.api.sales.customer_children_balance_map", {
			company: activeCompany.value,
		});
		childrenBalBase.value = res.base || {};
		childrenBalAcc.value = res.acc || {};
	} catch {
		childrenBalBase.value = {};
		childrenBalAcc.value = {};
	}
}

// Right-panel hierarchy helpers.
const selectedIsParent = computed(() => !!selectedDetail.value?.is_parent);
// Legacy parent-PE reallocation is a finance-only tool (also enforced server-side).
const canReallocate = computed(
	() =>
		selectedIsParent.value &&
		(session.isAdmin || (session.roles || []).includes("Accounts Manager"))
);
const headerBalanceValue = computed(() => {
	if (selectedIsParent.value) return selectedDetail.value?.cumulative_balance_acc ?? 0;
	return selected.value?.balance_acc ?? selected.value?.balance_base ?? 0;
});
const headerBalanceCurrency = computed(
	() => selected.value?.account_currency || selectedDetail.value?.account_currency || currency.value
);

// Names the party and the amount so the click is never ambiguous. Parents keep
// the bulk-split flow, so the wording differs there on purpose.
const paymentButtonTitle = computed(() => {
	if (!selected.value) return "";
	const who = selected.value.customer_name || selected.value.name;
	const amount = formatMoney(headerBalanceValue.value, headerBalanceCurrency.value, user.value.language);
	if (selectedIsParent.value) return `${t("Split one payment across child locations")} — ${who}`;
	return `${t("Payment")} — ${who} (${selected.value.name}) · ${amount}`;
});

function goToCustomerByName(name) {
	const row = nameToCustomer.value[name];
	if (row) selectCustomer(row);
}

// Parent picker (New/Edit): only standalone/parent customers (no own parent),
// excluding the customer being edited. Job status shown only when a parent is set.
const parentPickerOptions = computed(() => {
	const self = editingName.value;
	return customers.value
		.filter((c) => !c.parent_customer && c.name !== self)
		.map((c) => ({ name: c.name, label: c.customer_name || c.name }));
});
const jobStatusOptions = computed(() => [
	{ value: "", label: t("— none —") },
	{ value: "Active", label: t("Active") },
	{ value: "Completed", label: t("Completed") },
	{ value: "On Hold", label: t("On Hold") },
	{ value: "Cancelled", label: t("Cancelled") },
]);

const ledgerRows = computed(() => {
	const e = ledger.value?.entries || [];
	let runBase = Number(ledger.value?.opening_base || 0);
	let runAcc = Number(ledger.value?.opening_acc || 0);
	return e.map((row, idx) => {
		runBase += Number(row.debit || 0) - Number(row.credit || 0);
		runAcc +=
			Number(row.debit_in_account_currency || 0) -
			Number(row.credit_in_account_currency || 0);
		// _seq preserves the backend chronological order (posting_date, creation ASC)
		// so same-date rows sort correctly and the running balance stays monotonic.
		return { ...row, _seq: idx, running_base: runBase, running_acc: runAcc };
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

	// Hide pure FX-revaluation rows — base-currency-only "Exchange Gain Or Loss"
	// entries that adjust the USD value of the UZS receivable but have ZERO
	// account-currency (UZS) movement. They never change the UZS running balance,
	// so in this account-currency ledger they're just empty "—/—" noise.
	list = list.filter((r) =>
		Math.abs(Number(r.debit_in_account_currency || 0)) > 0.005 ||
		Math.abs(Number(r.credit_in_account_currency || 0)) > 0.005
	);

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
		const cmp = String(a.posting_date || "").localeCompare(String(b.posting_date || ""))
			|| ((a._seq || 0) - (b._seq || 0)); // same-date tiebreak by chronological order
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
			only_overdue: onlyOverdue.value ? 1 : 0,
			limit: 500,
		});
		customers.value = res.rows || [];
		totalCount.value = Number(res.total_count || 0);
		listTruncated.value = !!res.truncated;
		grandTotals.value = res.grand_totals || [];
		companyCurrency.value = res.company_currency || "";
		hasHierarchy.value = !!res.has_hierarchy;
		if (hasHierarchy.value) loadChildrenBalanceMap();
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
	// LOCAL date (not toISOString → UTC shift, off-by-one in UTC+N zones).
	const iso = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
	return { from: iso(from), to: iso(to) };
}

const includeChildren = ref(true);

watch(includeChildren, () => {
	if (selected.value) {
		loadLedger(selected.value);
		loadCustOrders(selected.value);
		call("stabler.api.sales.customer_detail", {
			name: selected.value.name,
			company: activeCompany.value,
			include_children: includeChildren.value ? 1 : 0,
		}).then((detail) => {
			recentInvoices.value = detail.recent_invoices || [];
			selectedDetail.value = detail;
		}).catch(console.error);
	}
});

async function loadLedger(customer) {
	if (!customer) return;
	ledgerLoading.value = true;
	ledgerError.value = "";
	try {
		const params = {
			company: activeCompany.value,
			customer: customer.name,
			include_children: includeChildren.value ? 1 : 0,
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
	selectedName.value = c.name; // composable syncs → URL + localStorage
	custOrders.value = [];
	recentInvoices.value = [];
	ledgerTypeFilter.value = "";
	ledgerSearch.value = "";
	ledgerSortAsc.value = false; // newest date first by default

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
			include_children: includeChildren.value ? 1 : 0,
		});
		recentInvoices.value = detail.recent_invoices || [];
		selectedDetail.value = detail;
		// The Children tab only exists for parents — fall back to Ledger otherwise.
		if (currentTab.value === "children" && !detail.is_parent) currentTab.value = "ledger";
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
			include_children: includeChildren.value ? 1 : 0,
			limit: 50,
		});
	} catch {
		custOrders.value = [];
	} finally {
		custOrdersLoading.value = false;
	}
}

function openVoucher(entry) {
	if (!entry?.voucher_no) return;
	const name = entry.voucher_no;
	const type = entry.voucher_type;
	if (type === "Payment Entry") {
		router.push(`/money/payments/${name}`);
	} else if (type === "Sales Invoice") {
		router.push(`/sales/invoices/${name}`);
	} else if (type === "Sales Order") {
		router.push(`/sales/orders/${name}`);
	} else if (type === "Journal Entry") {
		router.push({ path: "/money/journals", query: { open: name } });
	}
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
			parent_customer: data.parent_customer || "",
			job_status: data.job_status || "",
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
	// Job status only applies to a child (parent set); clear it otherwise.
	const jobStatus = f.parent_customer ? f.job_status || "" : "";
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
				parent_customer: f.parent_customer || "",
				job_status: jobStatus,
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
				parent_customer: f.parent_customer || "",
				job_status: jobStatus,
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

onMounted(async () => {
	await loadCustomers();
	loadCockpit();
	// selectedName is hydrated from URL/localStorage by useListViewState before this runs.
	if (selectedName.value) {
		const match = customers.value.find((c) => c.name === selectedName.value);
		if (match) selectCustomer(match);
	}
});

watch(activeCompany, () => {
	selected.value = null;
	ledger.value = null;
	selectedName.value = ""; // composable clears c from URL + localStorage
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
							<button
								v-if="hasHierarchy"
								type="button"
								class="btn btn-sm btn-ghost-secondary px-2"
								:title="viewMode === 'tree' ? t('Flat view') : t('Tree view')"
								@click="toggleView"
							>
								<i class="ti" :class="viewMode === 'tree' ? 'ti-list' : 'ti-sitemap'"></i>
							</button>
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
							<label class="form-check form-check-inline mb-0">
								<input
									v-model="onlyOverdue"
									type="checkbox"
									class="form-check-input"
									@change="loadCustomers"
								/>
								<span class="form-check-label small">{{ t("Overdue only") }}</span>
							</label>
						</div>
						
						<div class="cust-list-scroll" style="overflow-y: auto; height: calc(100vh - 12rem);">
							<!-- Yukleme, gelecek icerigin seklinde: 2 kolonlu liste.
							     SkeletonRows.vue koku <tbody> render ettigi icin yalnizca
							     bir <table> icine takilabiliyor; burada yukleme aninda
							     tablo yok (o v-else dalinda), o yuzden bilesenin ic
							     deseni yerinde tekrar ediliyor. -->
							<div v-if="loading" class="table-responsive m-0">
								<table class="table table-vcenter card-table table-no-stripe m-0 placeholder-glow">
									<tbody>
										<tr v-for="n in 8" :key="n">
											<td>
												<div class="d-flex align-items-center gap-2">
													<span class="placeholder rounded-2" style="width: 1.75rem; height: 1.75rem"></span>
													<span class="flex-fill">
														<span class="placeholder col-7 d-block py-1 rounded-1"></span>
														<span class="placeholder col-4 d-block py-1 mt-1 rounded-1"></span>
													</span>
												</div>
											</td>
											<td class="text-end">
												<span class="placeholder col-8 py-2 rounded-1"></span>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
							<div v-else-if="error" class="alert alert-danger m-2">{{ error }}</div>
							<EmptyState
								v-else-if="!visibleRows.length"
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
											v-for="row in visibleRows"
											:key="row.key"
											:class="{ 'table-active': selected?.name === row.c.name, 'cust-child-row': row.level === 1 }"
											class="cursor-pointer"
											@click="selectCustomer(row.c)"
										>
											<td>
												<div class="d-flex align-items-center gap-1" :style="row.level === 1 ? 'padding-left: 1.5rem' : ''">
													<button
														v-if="row.isParent"
														type="button"
														class="btn btn-ghost-secondary btn-icon btn-sm p-0 flex-shrink-0 cust-chevron"
														:title="isExpanded(row.c.name) ? t('Collapse') : t('Expand')"
														@click.stop="toggleExpand(row.c.name)"
													>
														<i class="ti" :class="isExpanded(row.c.name) ? 'ti-chevron-down' : 'ti-chevron-right'"></i>
													</button>
													<span v-else-if="row.level === 1" class="cust-tree-line flex-shrink-0"></span>
													<PartyAvatar :name="row.c.customer_name || row.c.name" size="sm" class="flex-shrink-0" />
													<div class="text-truncate min-w-0" style="max-width: 160px;">
														<div class="text-truncate text-body" :class="row.isParent ? 'fw-bold' : 'fw-semibold'">
															{{ row.c.customer_name }}
															<span v-if="row.isParent" class="badge bg-secondary-subtle text-secondary ms-1 fw-normal">{{ row.childCount }}</span>
														</div>
														<div v-if="row.parentName" class="small stbl-subtext text-truncate">
															<i class="ti ti-corner-down-right"></i> {{ row.parentName }}
														</div>
														<div v-else class="small stbl-subtext font-monospace text-truncate">{{ row.c.name }}</div>
													</div>
												</div>
											</td>
											<td class="text-end font-monospace stbl-amount align-middle">
												<div
													:class="{
														'text-green': rowBalanceValue(row) > 0,
														'text-red': rowBalanceValue(row) < 0,
														'text-secondary': !rowBalanceValue(row),
														'fw-medium': row.isParent,
													}"
													:title="rowCumulativeTooltip(row)"
												>
													{{ formatMoney(rowBalanceValue(row), rowBalanceCurrency(row), user.language) }}
												</div>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
						<div v-if="visibleRows.length" class="cust-list-footer p-3 border-top bg-light">
							<div class="d-flex align-items-center justify-content-between gap-2 mb-1">
								<span class="text-secondary small fw-semibold">
									{{ t("Visible") }} · {{ filteredCustomers.length }}
								</span>
								<span v-if="listTruncated" class="badge bg-orange-lt text-orange" :title="t('The server returned a capped page; this total covers the rows loaded, not the whole book.')">
									<i class="ti ti-alert-triangle me-1"></i>{{ customers.length }} / {{ totalCount }}
								</span>
							</div>
							<div
								v-for="b in visibleTotals"
								:key="b.currency"
								class="d-flex align-items-center justify-content-between gap-2"
							>
								<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
								<span class="font-monospace stbl-amount fw-bold text-body">
									{{ formatMoney(b.amount, b.currency, user.language) }}
								</span>
							</div>
							<div v-if="!visibleTotals.length" class="text-secondary small">
								{{ t("No outstanding balance.") }}
							</div>
							<div v-if="showGrandTotals" class="mt-2 pt-2 border-top">
								<div class="text-secondary small fw-semibold mb-1">
									{{ t("All customers") }} · {{ totalCount }}
								</div>
								<div
									v-for="b in grandTotals"
									:key="'gt-' + b.currency"
									class="d-flex align-items-center justify-content-between gap-2"
								>
									<span class="badge bg-secondary-lt text-secondary">{{ b.currency }}</span>
									<span class="font-monospace stbl-amount fw-bold text-body">
										{{ formatMoney(b.amount, b.currency, user.language) }}
									</span>
								</div>
							</div>
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
												<!-- Names the scope so this can never be read as the same number
												     the list footer shows: that one is the filtered page, this is
												     every customer in the ledger. -->
												<div class="stbl-subtext small">{{ t("All customers") }}</div>
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
									<!-- Grafik alani kadar yer tutuyor; yuklenince sayfa zipl -->
									<div v-if="cockpitLoading" class="placeholder-glow">
										<span class="placeholder col-12 rounded-2 d-block" style="height: 120px"></span>
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
									<button
										v-if="selectedDetail?.parent_customer"
										type="button"
										class="btn btn-sm btn-ghost-secondary px-2 py-0 mb-1"
										:title="t('Parent Customer')"
										@click="goToCustomerByName(selectedDetail.parent_customer)"
									>
										<i class="ti ti-arrow-up me-1"></i>{{ selectedDetail.parent_customer_name || selectedDetail.parent_customer }}
									</button>
									<h2 class="m-0 text-truncate text-body fw-bold">
										{{ selected.customer_name }}
										<span v-if="selectedIsParent" class="badge bg-blue-lt text-blue align-middle ms-1">{{ t("Parent") }}</span>
									</h2>
									<div class="small stbl-subtext font-monospace">{{ selected.name }}</div>
								</div>
								<div class="d-flex gap-2">
									<button type="button" class="btn btn-sm btn-outline-secondary" @click="openEdit(selected)">
										<i class="ti ti-pencil me-1"></i>{{ t("Edit") }}
									</button>
									<button
										v-if="canReallocate"
										type="button"
										class="btn btn-sm btn-outline-secondary"
										:title="t('Reallocate a legacy advance to child locations')"
										@click="reallocateOpen = true"
									>
										<i class="ti ti-arrows-shuffle me-1"></i>{{ t("Reallocate") }}
									</button>
									<!-- Paying the wrong customer is the expensive mistake on this
									     screen, and the button used to say only "Payment". It now
									     echoes the target and its balance in the tooltip, and the
									     amount inline. Parent still opens the bulk-split dialog. -->
									<button
										type="button"
										class="btn btn-sm btn-outline-secondary"
										:title="paymentButtonTitle"
										@click="selectedIsParent ? (bulkPayOpen = true) : (partyPayOpen = true)"
									>
										<i class="ti ti-cash me-1"></i>{{ t("Payment") }}
										<span class="font-monospace stbl-amount ms-1 text-secondary">
											{{ formatMoney(headerBalanceValue, headerBalanceCurrency, user.language) }}
										</span>
									</button>
									<button
										type="button"
										class="btn btn-sm btn-outline-secondary"
										:title="t('Professional Excel export of this ledger')"
										@click="exportLedgerXlsx"
									>
										<i class="ti ti-file-spreadsheet me-1"></i>{{ t("Statement") }}
									</button>
									<button
										v-if="directInvoiceEnabled"
										type="button"
										class="btn btn-sm btn-primary"
										:disabled="selectedIsParent"
										:title="selectedIsParent ? t('Transactions are recorded on child locations') : ''"
										@click="router.push({ path: '/sales/invoices/new', query: { new_for: selected.name } })"
									>
										<i class="ti ti-file-plus me-1"></i>{{ t("New Invoice") }}
									</button>
									<router-link
										v-else
										:to="{ path: '/sales/orders/new', query: { new_for: selected.name } }"
										class="btn btn-sm btn-primary"
										:class="{ disabled: selectedIsParent }"
										:title="selectedIsParent ? t('Transactions are recorded on child locations') : ''"
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
											<div class="text-secondary small text-uppercase fw-semibold mb-1">
												{{ selectedIsParent ? t("Balance") + " (" + t("Cumulative") + ")" : t("Balance") }}
											</div>
											<BalanceChip
												:value="headerBalanceValue"
												:currency="headerBalanceCurrency"
												:language="user.language"
												party-type="Customer"
												size="md"
												class="w-100 justify-content-center"
											/>
											<div v-if="selectedIsParent" class="small text-secondary mt-1">
												{{ t("Own") }}: {{ formatMoney(selectedDetail?.own_balance_acc || 0, headerBalanceCurrency, user.language) }}
											</div>
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

							<!-- Parent Child Filter Toggle -->
							<div v-if="selectedIsParent" class="px-3 py-2 bg-light-subtle border-bottom d-flex align-items-center justify-content-between">
								<label class="form-check form-switch m-0 cursor-pointer d-flex align-items-center gap-2">
									<input v-model="includeChildren" type="checkbox" class="form-check-input mt-0" />
									<span class="fw-semibold text-body small">
										<i class="ti ti-sitemap me-1 text-primary"></i>{{ t("Include Child Customer Transactions") }}
									</span>
								</label>
								<span v-if="includeChildren" class="badge bg-primary-lt text-primary small">
									<i class="ti ti-check me-1"></i>{{ t("Consolidated View") }} ({{ selectedDetail?.children?.length || 0 }} {{ t("children") }})
								</span>
								<span v-else class="badge bg-secondary-lt text-secondary small">
									{{ t("Parent Only View") }}
								</span>
							</div>

							<!-- Tabs Header -->
							<div class="bg-white border-bottom">
								<ul class="nav nav-tabs border-0 px-3">
									<li v-if="selectedIsParent" class="nav-item">
										<a
											href="#"
											class="nav-link border-0 border-bottom-2 py-3"
											:class="{ active: currentTab === 'children', 'border-primary': currentTab === 'children' }"
											@click.prevent="currentTab = 'children'"
										>
											{{ t("Children") }}
											<span class="badge bg-secondary-subtle text-secondary ms-1">{{ selectedDetail?.children?.length || 0 }}</span>
										</a>
									</li>
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
								<!-- CHILDREN TAB (parent only) -->
								<div v-if="currentTab === 'children' && selectedIsParent" class="p-3">
									<div class="table-responsive">
										<table class="table table-vcenter table-hover card-table">
											<thead>
												<tr>
													<th>{{ t("Name") }}</th>
													<th>{{ t("Job Status") }}</th>
													<th class="text-end">{{ t("Balance") }}</th>
												</tr>
											</thead>
											<tbody>
												<tr
													v-for="ch in selectedDetail?.children || []"
													:key="ch.name"
													class="cursor-pointer"
													@click="goToCustomerByName(ch.name)"
												>
													<td>
														<div class="d-flex align-items-center gap-2">
															<PartyAvatar :name="ch.customer_name || ch.name" size="sm" class="flex-shrink-0" />
															<div class="text-truncate min-w-0">
																<div class="fw-semibold text-truncate text-body">{{ ch.customer_name }}</div>
																<div class="small stbl-subtext font-monospace text-truncate">{{ ch.name }}</div>
															</div>
														</div>
													</td>
													<td>
														<span v-if="ch.job_status" class="badge" :class="getStatusBadgeClass('Customer', ch.job_status)">
															{{ t(ch.job_status) }}
														</span>
														<span v-else class="text-secondary">—</span>
													</td>
													<td class="text-end font-monospace stbl-amount">
														<span
															:class="{
																'text-green': Number(ch.balance_acc ?? ch.balance_base) > 0,
																'text-red': Number(ch.balance_acc ?? ch.balance_base) < 0,
																'text-secondary': !Number(ch.balance_acc ?? ch.balance_base),
															}"
														>
															{{ formatMoney(
																ch.balance_acc ?? ch.balance_base,
																Number(ch.balance_acc ?? ch.balance_base) ? (ch.account_currency || currency) : currency,
																user.language,
															) }}
														</span>
													</td>
												</tr>
											</tbody>
										</table>
									</div>
								</div>

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
										<div v-if="ledgerLoading" class="table-responsive">
											<table class="table table-vcenter table-sm card-table m-0 placeholder-glow">
												<tbody>
													<tr v-for="n in 8" :key="n">
														<td><span class="placeholder col-9 py-2 rounded-1"></span></td>
														<td><span class="placeholder col-7 py-2 rounded-1"></span></td>
														<td class="text-end"><span class="placeholder col-6 py-2 rounded-1"></span></td>
														<td class="text-end"><span class="placeholder col-6 py-2 rounded-1"></span></td>
														<td class="text-end"><span class="placeholder col-8 py-2 rounded-1"></span></td>
													</tr>
												</tbody>
											</table>
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
													<tr v-if="ledger" class="text-secondary bg-transparent">
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
															<div class="d-flex align-items-center gap-1">
																<span class="small text-secondary fw-semibold">{{ e.voucher_type }}</span>
																<span
																	v-if="e.party && e.party !== selected.name"
																	class="badge bg-secondary-lt text-dark ms-1"
																	style="font-size: 0.72rem;"
																	:title="e.party_name || e.party"
																>
																	<i class="ti ti-building-store me-1 text-primary"></i>{{ e.party_name || e.party }}
																</span>
															</div>
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
											</table>
										</template>
									</div>
								</div>

								<!-- ORDERS TAB -->
								<div v-if="currentTab === 'orders'" class="p-3">
									<div v-if="custOrdersLoading" class="table-responsive">
										<table class="table table-vcenter card-table m-0 placeholder-glow">
											<tbody>
												<tr v-for="n in 5" :key="n">
													<td><span class="placeholder col-8 py-2 rounded-1"></span></td>
													<td><span class="placeholder col-6 py-2 rounded-1"></span></td>
													<td class="text-end"><span class="placeholder col-7 py-2 rounded-1"></span></td>
													<td><span class="placeholder col-5 py-2 rounded-1"></span></td>
												</tr>
											</tbody>
										</table>
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
													<td>
														<div class="d-flex align-items-center gap-1">
															<span class="font-monospace text-primary fw-semibold">{{ o.name }}</span>
															<span
																v-if="o.customer && o.customer !== selected.name"
																class="badge bg-secondary-lt text-dark font-body ms-1"
																style="font-size: 0.72rem;"
																:title="o.customer_name || o.customer"
															>
																<i class="ti ti-building-store me-1 text-primary"></i>{{ o.customer_name || o.customer }}
															</span>
														</div>
													</td>
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
													<td>
														<div class="d-flex align-items-center gap-1">
															<span class="font-monospace text-primary fw-semibold">{{ inv.name }}</span>
															<span
																v-if="inv.customer && inv.customer !== selected.name"
																class="badge bg-secondary-lt text-dark font-body ms-1"
																style="font-size: 0.72rem;"
																:title="inv.customer_name || inv.customer"
															>
																<i class="ti ti-building-store me-1 text-primary"></i>{{ inv.customer_name || inv.customer }}
															</span>
														</div>
													</td>
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

	<!-- Voucher Drawer removed: voucher links now navigate to full-form routes -->

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
							<div class="col-md-6">
								<label class="form-label">{{ t("Parent Customer") }}</label>
								<Select
									v-model="form.parent_customer"
									:options="parentPickerOptions"
									value-key="name"
									label-key="label"
									:placeholder="t('— none —')"
								/>
							</div>
							<div v-if="form.parent_customer" class="col-md-6">
								<label class="form-label">{{ t("Job Status") }}</label>
								<Select v-model="form.job_status" :options="jobStatusOptions" />
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
		:party-name="selected.customer_name"
		:company="activeCompany"
		@close="partyPayOpen = false"
		@paid="partyPayOpen = false; loadLedger(selected); loadCustOrders(selected); loadCustomers(); selectCustomer(selected);"
	/>

	<!-- Parent bulk payment — split one payment across child locations -->
	<ParentBulkPaymentDialog
		v-if="selected && selectedIsParent"
		:open="bulkPayOpen"
		:company="activeCompany"
		:parent="selected.name"
		:parent-name="selected.customer_name"
		@close="bulkPayOpen = false"
		@done="bulkPayOpen = false; loadLedger(selected); loadCustomers(); selectCustomer(selected);"
	/>

	<!-- Legacy parent-PE reallocation (finance only) -->
	<ParentReallocateDialog
		v-if="selected && canReallocate"
		:open="reallocateOpen"
		:company="activeCompany"
		:parent="selected.name"
		:parent-name="selected.customer_name"
		@close="reallocateOpen = false"
		@done="reallocateOpen = false; loadLedger(selected); loadCustomers(); selectCustomer(selected);"
	/>

	<!-- Direct Sales Invoice Modal -->
	<NewDirectInvoiceModal
		:open="directInvoiceOpen"
		:initial-customer="selected?.name"
		:initial-customer-name="selected?.customer_name"
		@close="directInvoiceOpen = false"
		@created="if (selected) selectCustomer(selected);"
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

/* Hierarchy tree rows */
.cust-child-row {
	background-color: #fcfcfd;
}
.cust-chevron {
	width: 1.25rem;
	height: 1.25rem;
	line-height: 1;
}
.cust-tree-line {
	display: inline-block;
	width: 1.25rem;
	border-left: 2px solid var(--cust-border);
	border-bottom: 2px solid var(--cust-border);
	height: 0.9rem;
	margin-right: 0.15rem;
	border-bottom-left-radius: 0.25rem;
	opacity: 0.7;
}
</style>
