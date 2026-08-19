<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { accountLabel } from "../../composables/accounts.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { blockerText, cascadeRows, recordRoute } from "../../composables/deleteImpact.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import PiAdvanceLedger from "../../components/PiAdvanceLedger.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/proformas");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const form = ref(blankForm());

const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];

// PI group assignment lives in PiGroups.vue (multi-select modal), not here — the
// input is gone but `import_pi_group` stays in the form state below so an edit
// round-trips the stored value instead of clearing it.

function blankForm() {
	return {
		name: null,
		company: null,
		supplier: "",
		supplier_name: "",
		pi_date: todayIso(),
		supplier_pi_ref: "",
		import_pi_group: "",
		commercial_invoice: "",
		currency: "USD",
		incoterm: "CIF",
		incoterm_location: "",
		port_of_loading: "",
		port_of_discharge: "",
		prepayment_type: "AGREED_TOTAL",
		agreed_total: 0,
		advance_pct: 30,
		expected_payment_date: "",
		bank_agreed: 0,
		cash_agreed: 0,
		docs_total: null,
		cash_difference: null,
		status: "DRAFT",
		remarks: "",
		items: [],
		linked_cis: [],
		advance_payments: [],
		advance_ledger: null,
	};
}

function blankItemRow() {
	return {
		item: "",
		category: "",
		description: "",
		fcl: 0,
		boxes: 0,
		box_weight_kg: 0,
		qty: 0,
		uom: "",
		rate: 0,
		docs_price: 0,
		_qtyManual: false,
	};
}

const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100;
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

const bankTouched = ref(false);
const cashTouched = ref(false);

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 20,
		supplier_group_scope: "imports",
	});
}

function pickSupplier(s) {
	form.value.supplier = s.name;
	form.value.supplier_name = s.supplier_name || s.name;
	loadLineCategories();
}

function clearSupplier() {
	form.value.supplier = "";
	form.value.supplier_name = "";
	lineCategories.value = [];
}

async function resolveSupplierName(code) {
	if (!code) return "";
	try {
		const rows = await call("stabler.api.purchasing.list_suppliers", {
			company: activeCompany.value,
			search: code,
			limit: 5,
		});
		const match = (rows || []).find((s) => s.name === code);
		return match ? match.supplier_name || match.name : code;
	} catch (_err) {
		return code;
	}
}

// Vendor categories for the per-line category dropdown (vendor-scoped).
const lineCategories = ref([]);
const categoryOptions = computed(() =>
	lineCategories.value.map((c) => c.display_name || c.category_name).filter(Boolean)
);

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
	} catch (err) {
		lineCategories.value = [];
	}
}

async function loadDoc() {
	if (isCreate.value) {
		form.value = blankForm();
		bankTouched.value = false;
		cashTouched.value = false;
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		const detail = await call("stabler.api.imports.proforma_detail", { name: docName.value });
		form.value = {
			...blankForm(),
			...detail,
			supplier_name: await resolveSupplierName(detail.supplier),
			// null from the backend would trip DateInput's String prop; "" is its blank value.
			expected_payment_date: detail.expected_payment_date || "",
			items: (detail.items || []).map((it) => ({
				item: it.item,
				category: it.category || "",
				description: it.description || "",
				fcl: it.fcl || 0,
				boxes: it.boxes || 0,
				box_weight_kg: it.box_weight_kg || 0,
				qty: it.qty || 0,
				uom: it.uom || "",
				rate: it.rate || 0,
				docs_price: it.docs_price || 0,
				_qtyManual: true,
			})),
			linked_cis: detail.linked_cis || [],
			advance_payments: detail.advance_payments || [],
		};
		bankTouched.value = true;
		cashTouched.value = true;
		loadLineCategories();
	} catch (err) {
		error.value = err?.message || t("Failed to load the proforma.");
	} finally {
		loading.value = false;
	}
}

// ---- Items grid ----
function addItemRow() {
	form.value.items.push(blankItemRow());
}
function removeItemRow(idx) {
	form.value.items.splice(idx, 1);
}
function onBoxesOrWeightInput(row) {
	if (!row._qtyManual) {
		row.qty = round2((Number(row.boxes) || 0) * (Number(row.box_weight_kg) || 0));
	}
}
function onQtyInput(row) {
	row._qtyManual = true;
}
function rowAmount(row) {
	return (Number(row.qty) || 0) * (Number(row.rate) || 0);
}
function rowDocsAmount(row) {
	return (Number(row.qty) || 0) * (Number(row.docs_price) || 0);
}

function getSummaryRow(row) {
	if (!form.value.invoiced_summary || !form.value.invoiced_summary.items) return null;
	const cat = row.category || "";
	const item = row.item || "";
	return (
		form.value.invoiced_summary.items.find((s) => s.item === item && (s.category || "") === cat) ||
		form.value.invoiced_summary.items.find((s) => s.item === item) ||
		null
	);
}

const hasItems = computed(() => (form.value.items || []).some((r) => r.item));
const itemsAgreedTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowAmount(r), 0));
const itemsDocsTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowDocsAmount(r), 0));
const itemsCashDiff = computed(() => itemsAgreedTotal.value - itemsDocsTotal.value);
const itemsTotalBoxes = computed(() => (form.value.items || []).reduce((s, r) => s + (Number(r.boxes) || 0), 0));
const itemsTotalQty = computed(() => (form.value.items || []).reduce((s, r) => s + (Number(r.qty) || 0), 0));
const itemsTotalInvoiced = computed(() => (form.value.items || []).reduce((s, r) => s + (Number(getSummaryRow(r)?.invoiced_qty || 0)), 0));
const itemsTotalRemaining = computed(() => (form.value.items || []).reduce((s, r) => s + (Number(r.qty) || 0) - (Number(getSummaryRow(r)?.invoiced_qty || 0)), 0));
const itemCategories = computed(() => [
	...new Set((form.value.items || []).map((r) => r.category).filter(Boolean)),
]);

watch([itemsAgreedTotal, itemsDocsTotal, itemsCashDiff, hasItems], () => {
	if (!hasItems.value) return;
	form.value.agreed_total = itemsAgreedTotal.value;
	if (!bankTouched.value) form.value.bank_agreed = itemsDocsTotal.value;
	if (!cashTouched.value) form.value.cash_agreed = itemsCashDiff.value;
});

function onBankInput() {
	bankTouched.value = true;
}
function onCashInput() {
	cashTouched.value = true;
}

const earmarkOk = computed(() => {
	const f = form.value;
	const a = Number(f.agreed_total) || 0;
	const b = Number(f.bank_agreed) || 0;
	const c = Number(f.cash_agreed) || 0;
	if (a === 0 && b === 0 && c === 0) return true;
	return Math.abs(b + c - a) <= 0.5;
});

function syncEarmark() {
	const total = itemsAgreedTotal.value || Number(form.value.agreed_total) || 0;
	const docs = itemsDocsTotal.value || round2(total * ((Number(form.value.advance_pct) || 30) / 100));
	form.value.agreed_total = total;
	form.value.bank_agreed = docs;
	form.value.cash_agreed = round2(total - docs);
	bankTouched.value = false;
	cashTouched.value = false;
	toast.success(t("Prepayment bank & cash totals synced to items total."));
}

// ---- Smart Advance Payment Modal ----
const advOpen = ref(false);
const advSaving = ref(false);
const advAccountsLoading = ref(false);
const companyBankAccounts = ref([]);
const companyCashAccounts = ref([]);
const advSelectedBank = ref("");
const advSelectedCash = ref("");

const advStrategy = ref("DOCS_ONLY"); // 'DOCS_ONLY' | 'SPLIT' | 'ALL_BANK' | 'ALL_CASH' | 'CUSTOM'
const advBasis = ref("DOCS"); // 'AGREED' | 'DOCS'
const advPct = ref(30);
const customPct = ref("");
const advBank = ref(0);
const advCash = ref(0);
const advDate = ref(todayIso());
const advRef = ref("");

const targetAgreedTotal = computed(() => itemsAgreedTotal.value || Number(form.value.agreed_total) || 0);
const targetDocsTotal = computed(() => itemsDocsTotal.value || Number(form.value.docs_total) || Number(form.value.bank_agreed) || 0);
const targetCashDiff = computed(() => Math.max(0, targetAgreedTotal.value - targetDocsTotal.value));

const calcDocsOnlyBank = computed(() => round2(targetDocsTotal.value * ((Number(advPct.value) || 0) / 100)));
const calcFullAdvance = computed(() => round2(targetAgreedTotal.value * ((Number(advPct.value) || 0) / 100)));
const calcSplitBank = computed(() => round2(calcFullAdvance.value * (targetDocsTotal.value / (targetAgreedTotal.value || 1))));
const calcSplitCash = computed(() => round2(calcFullAdvance.value - calcSplitBank.value));

const currentPaidBank = computed(() => form.value.advance_summary?.paid_bank || 0);
const currentPaidCash = computed(() => form.value.advance_summary?.paid_cash || 0);
const currentPaidTotal = computed(() => form.value.advance_summary?.paid_total || 0);

function applyStrategy(strat) {
	advStrategy.value = strat;
	if (strat === "DOCS_ONLY") {
		advBasis.value = "DOCS";
		advBank.value = calcDocsOnlyBank.value;
		advCash.value = 0;
	} else if (strat === "SPLIT") {
		advBasis.value = "AGREED";
		advBank.value = calcSplitBank.value;
		advCash.value = calcSplitCash.value;
	} else if (strat === "ALL_BANK") {
		advBasis.value = "AGREED";
		advBank.value = calcFullAdvance.value;
		advCash.value = 0;
	} else if (strat === "ALL_CASH") {
		advBasis.value = "AGREED";
		advBank.value = 0;
		advCash.value = calcFullAdvance.value;
	}
}

function setPercentage(pct) {
	advPct.value = pct;
	customPct.value = "";
	if (advStrategy.value !== "CUSTOM") {
		applyStrategy(advStrategy.value);
	} else {
		applyStrategy("DOCS_ONLY");
	}
}

function onCustomPctInput() {
	const val = Number(customPct.value);
	if (!isNaN(val) && val >= 0 && val <= 100) {
		advPct.value = val;
		if (advStrategy.value !== "CUSTOM") {
			applyStrategy(advStrategy.value);
		} else {
			applyStrategy("DOCS_ONLY");
		}
	}
}

function onManualAmountChange() {
	advStrategy.value = "CUSTOM";
}

async function loadCompanyAccounts() {
	if (!activeCompany.value) return;
	advAccountsLoading.value = true;
	try {
		const accounts = await call("stabler.api.money.list_cash_bank_accounts", {
			company: activeCompany.value,
			limit: 100,
		});
		const cur = form.value.currency;
		const bank = accounts.filter((a) => a.account_type === "Bank");
		const cash = accounts.filter((a) => a.account_type === "Cash");
		companyBankAccounts.value = bank;
		companyCashAccounts.value = cash;

		const defBank = bank.find((a) => a.account_currency === cur) || bank[0];
		const defCash = cash.find((a) => a.account_currency === cur) || cash[0];
		if (!advSelectedBank.value && defBank) advSelectedBank.value = defBank.name;
		if (!advSelectedCash.value && defCash) advSelectedCash.value = defCash.name;
	} catch {
		companyBankAccounts.value = [];
		companyCashAccounts.value = [];
	} finally {
		advAccountsLoading.value = false;
	}
}

async function openAdvanceModal() {
	advPct.value = Number(form.value.advance_pct) || 30;
	customPct.value = "";
	advDate.value = todayIso();
	advRef.value = `ADV-${form.value.name || form.value.supplier_pi_ref || "PI"}`;
	const defaultStrat = form.value.prepayment_type === "DOCS_TOTAL" ? "DOCS_ONLY" : "SPLIT";
	applyStrategy(defaultStrat);
	loadCompanyAccounts();
	advOpen.value = true;
}

async function submitAdvancePayment() {
	if (Number(advBank.value || 0) <= 0 && Number(advCash.value || 0) <= 0) {
		toast.error(t("Enter a bank and/or cash amount."));
		return;
	}
	advSaving.value = true;
	try {
		const res = await call("stabler.api.imports.create_advance_payment", {
			purchase_order: docName.value,
			bank_amount: Number(advBank.value || 0),
			cash_amount: Number(advCash.value || 0),
			payment_date: advDate.value || undefined,
			reference_no: advRef.value || undefined,
			prepayment_basis: advBasis.value,
			bank_account: advSelectedBank.value || undefined,
			cash_account: advSelectedCash.value || undefined,
		});
		if (res.warning) toast.info(res.warning);
		toast.success(t("Advance recorded and posted."));
		advOpen.value = false;
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Could not record advance payment."));
	} finally {
		advSaving.value = false;
	}
}

// ---- Fill items from a vendor category ----
const fillModalOpen = ref(false);

const fillCategoriesLoading = ref(false);
const fillCategories = ref([]);
const fillCategory = ref("");
const fillContainers = ref(1);
const fillBoxWeight = ref(20);
const fillAgreedPrice = ref(0);
const fillDocsPrice = ref(0);
const fillApplying = ref(false);

async function openFillModal() {
	if (!form.value.supplier) {
		toast.error(t("Select a supplier first."));
		return;
	}
	fillCategory.value = "";
	fillContainers.value = 1;
	fillBoxWeight.value = 20;
	fillAgreedPrice.value = 0;
	fillDocsPrice.value = 0;
	fillModalOpen.value = true;
	fillCategoriesLoading.value = true;
	try {
		fillCategories.value = await call("stabler.api.imports.list_vendor_categories", {
			company: activeCompany.value,
			vendor: form.value.supplier,
		});
	} catch (err) {
		toast.error(err?.message || t("Failed to load vendor categories."));
		fillCategories.value = [];
	} finally {
		fillCategoriesLoading.value = false;
	}
}
function closeFillModal() {
	if (!fillApplying.value) fillModalOpen.value = false;
}

async function applyFillCategory() {
	if (!fillCategory.value) return;
	fillApplying.value = true;
	try {
		const detail = await call("stabler.api.imports.vendor_category_detail", {
			name: fillCategory.value,
		});
		const items = detail.items || [];
		const totalBoxes = items.reduce((s, it) => s + (Number(it.boxes_per_container) || 0), 0);
		const containers = Number(fillContainers.value) || 0;
		const boxWeight = Number(fillBoxWeight.value) || 0;
		const categoryLabel = detail.display_name || detail.category_name || "";
		for (const it of items) {
			const perContainer = Number(it.boxes_per_container) || 0;
			const boxes = perContainer * containers;
			const fcl = totalBoxes ? round2((perContainer / totalBoxes) * containers) : 0;
			// Kutular eşit değil (18 kg, 20 kg …). Kategori satırı kendi kilosunu
			// taşıyorsa o kazanır; taşımıyorsa yukarıdaki tek kutu değeri yedektir.
			const rowWeight = Number(it.box_kg) || boxWeight;
			form.value.items.push({
				item: it.item_code,
				category: categoryLabel,
				description: it.item_name || "",
				fcl,
				boxes,
				box_weight_kg: rowWeight,
				qty: round2(boxes * rowWeight),
				uom: it.stock_uom || "",
				rate: Number(fillAgreedPrice.value) || 0,
				docs_price: Number(fillDocsPrice.value) || 0,
				_qtyManual: false,
			});
		}
		toast.success(t("Items added from category"));
		fillModalOpen.value = false;
	} catch (err) {
		toast.error(err?.message || t("Could not apply the category."));
	} finally {
		fillApplying.value = false;
	}
}

async function saveProforma() {
	if (!form.value.supplier) {
		toast.error(t("Supplier is required."));
		return;
	}
	if (isCreate.value && !(form.value.supplier_pi_ref || "").trim()) {
		toast.error(t("PI number (supplier ref) is required — it becomes the document identity."));
		return;
	}
	if (!earmarkOk.value) {
		toast.error(t("Bank Agreed + Cash Agreed must equal Agreed Total."));
		return;
	}
	saving.value = true;
	try {
		const payload = {
			...form.value,
			company: activeCompany.value,
			items: (form.value.items || [])
				.filter((r) => r.item)
				.map((r) => ({
					item: r.item,
					category: r.category || undefined,
					description: r.description,
					fcl: r.fcl,
					boxes: r.boxes,
					box_weight_kg: r.box_weight_kg,
					qty: r.qty,
					uom: r.uom,
					rate: r.rate,
					docs_price: r.docs_price,
				})),
		};
		const res = await call("stabler.api.imports.save_proforma", { payload });
		toast.success(t("Proforma saved"));
		if (isCreate.value) {
			router.replace({ name: "imports-proforma", params: { name: res.name } });
		} else {
			await loadDoc();
		}
	} catch (err) {
		toast.error(err?.message || t("Could not save the proforma."));
	} finally {
		saving.value = false;
	}
}

const statusColor = computed(() => {
	const cls = getStatusBadgeClass("Proforma Invoice", form.value.status);
	const m = /^bg-([a-z]+)-lt$/.exec(cls);
	return m ? m[1] : "secondary";
});

// Deleting a proforma must not take the shipment with it: the commercial
// invoice keeps its rows and only loses the agreement link. The button never
// deletes directly — it asks the endpoint what would happen (dry run, writes
// nothing), shows that report, and only a red confirmation acts on it.
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
		deletePlan.value = await call("stabler.api.imports.delete_proforma_invoice", {
			company: activeCompany.value,
			name: docName.value,
			dry_run: 1,
		});
		deleteModalOpen.value = true;
	} catch (err) {
		toast.error(err?.message || t("Could not check what depends on this proforma."));
	} finally {
		deletePlanning.value = false;
	}
}

async function confirmDelete() {
	if (deleting.value || !canDelete.value) return;
	const label = form.value.supplier_pi_ref || docName.value;
	const ok = await confirm({
		title: t("Delete this proforma?"),
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
		await call("stabler.api.imports.delete_proforma_invoice", {
			company: activeCompany.value,
			name: docName.value,
			cascade: deleteCascade.value ? 1 : 0,
			dry_run: 0,
		});
		deleteModalOpen.value = false;
		toast.success(t("Proforma {name} deleted.", { name: label }));
		router.push("/imports/proformas");
	} catch (err) {
		toast.error(err?.message || t("Could not delete the proforma."));
	} finally {
		deleting.value = false;
	}
}

onMounted(() => {
	loadItemsList();
	loadDoc();
});
watch(docName, loadDoc);

// ---- PI <-> CI match panel (sandbox port) ---------------------------------
// One source of truth: get_ci_pi_discrepancies(pi=...) — the same rules module
// as the whole-book report, scoped to this PI. Includes info-level sub_cut
// rows, which ARE the sub-cut breakdown.
const matchData = ref(null);
const matchLoading = ref(false);

async function loadMatch() {
	if (!docName.value || !activeCompany.value) {
		matchData.value = null;
		return;
	}
	matchLoading.value = true;
	try {
		matchData.value = await call("stabler.api.imports.get_ci_pi_discrepancies", {
			company: activeCompany.value,
			pi: docName.value,
		});
	} catch {
		matchData.value = null; // panel degrades to hidden; the form still works
	} finally {
		matchLoading.value = false;
	}
}
onMounted(loadMatch);
watch(docName, loadMatch);

const matchSummary = computed(() => matchData.value?.summary || null);
const flaggedRows = computed(() =>
	(matchData.value?.rows || []).filter((r) => r.level === "error" || r.level === "warn")
);
const subCuts = computed(() => {
	const groups = new Map();
	for (const r of matchData.value?.rows || []) {
		if (r.level !== "info") continue;
		const key = r.category || "—";
		let g = groups.get(key);
		if (!g) {
			g = { category: key, lines: [], boxes: 0, qty: 0 };
			groups.set(key, g);
		}
		g.lines.push(r);
		g.boxes += r.boxes || 0;
		g.qty += r.qty || 0;
	}
	return [...groups.values()];
});
</script>

<template>
	<div>
		<!-- Page header: status-coloured left border with Supplier PI Ref on top -->
		<div class="card mb-3" :style="{ borderLeft: `4px solid var(--tblr-${statusColor})` }">
			<div class="card-body d-flex align-items-center flex-wrap gap-3">
				<button type="button" class="btn btn-outline-secondary btn-icon" @click="router.push('/imports/proformas')">
					<i class="ti ti-arrow-left"></i>
				</button>
				<div class="flex-grow-1">
					<div class="d-flex align-items-center gap-2 flex-wrap">
						<!-- Main Title is Supplier PI No (e.g. HMA/PI/2677/202425) -->
						<h2 class="page-title mb-0 font-monospace">
							{{ isCreate ? t("New Proforma") : (form.supplier_pi_ref || form.name) }}
						</h2>
						<!-- Secondary System Reference Badge -->
						<span
							v-if="!isCreate && form.supplier_pi_ref && form.supplier_pi_ref !== form.name"
							class="badge bg-secondary-lt font-monospace text-secondary"
							:title="t('ERPNext System Reference ID')"
						>
							Ref: {{ form.name }}
						</span>
						<span v-if="!isCreate" class="badge" :class="getStatusBadgeClass('Proforma Invoice', form.status)">
							{{ form.status }}
						</span>
						<span v-if="form.commercial_invoice" class="badge bg-green-lt font-monospace" :title="t('Commercial Invoice')">
							{{ form.commercial_invoice }}
						</span>
					</div>
					<div class="text-secondary small mt-1">
						{{ form.supplier_name || form.supplier || t("No supplier selected") }}
						<template v-if="form.incoterm"> · {{ form.incoterm }}</template>
						<template v-if="form.pi_date"> · {{ formatDate(form.pi_date) }}</template>
						· {{ form.advance_pct }}% / {{ 100 - form.advance_pct }}%
					</div>
				</div>
				<button
					v-if="!isCreate && form.name"
					type="button"
					class="btn btn-outline-success"
					:disabled="loading || saving"
					@click="openAdvanceModal"
				>
					<i class="ti ti-cash me-1"></i>{{ t("Record Advance") }}
				</button>
				<button type="button" class="btn btn-primary" :disabled="saving || loading || !earmarkOk" @click="saveProforma">
					<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
				</button>
			</div>
		</div>


		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- Metric strip -->
		<div class="row row-cards mb-3">
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Agreed total") }}</div>
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ fm(itemsAgreedTotal, form.currency) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Docs total") }}</div>
						<div class="h3 mb-0 font-monospace text-azure fw-bold">{{ fm(itemsDocsTotal, form.currency) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Cash Difference") }}</div>
						<div class="h3 mb-0 font-monospace" :class="{ 'text-warning fw-bold': Math.abs(itemsCashDiff) > 0.5 }">{{ fm(itemsCashDiff, form.currency) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Categories") }}</div>
						<div class="mt-1 d-flex flex-wrap gap-1">
							<span v-for="c in itemCategories" :key="c" class="badge bg-blue-lt">{{ c }}</span>
							<span v-if="!itemCategories.length" class="text-secondary">—</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Details -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Details") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-4">
						<label class="form-label required">{{ t("Supplier") }}</label>
						<Typeahead
							v-model="form.supplier"
							:display="form.supplier ? (form.supplier_name || form.supplier) : ''"
							:search="searchSuppliers"
							:placeholder="t('Search supplier…')"
							@pick="pickSupplier"
							@clear="clearSupplier"
						>
							<template #option="{ item }">
								<div class="fw-semibold small">{{ item.supplier_name || item.name }}</div>
								<div class="font-monospace text-secondary" style="font-size: 11px">{{ item.name }}</div>
							</template>
						</Typeahead>
					</div>
					<div class="col-md-2">
						<label class="form-label">{{ t("PI Date") }}</label>
						<DateInput v-model="form.pi_date" />
					</div>
					<div class="col-md-3">
						<label class="form-label required">{{ t("Supplier PI No.") }}</label>
						<input v-model="form.supplier_pi_ref" type="text" class="form-control font-monospace fw-bold text-primary" :readonly="!isCreate" :placeholder="t('e.g. FIR/25-26/29639-29647')" :title="!isCreate ? t('The PI number is the document identity and cannot be changed after creation.') : ''">
					</div>

					<div class="col-md-2">
						<label class="form-label">{{ t("Currency") }}</label>
						<input v-model="form.currency" type="text" maxlength="3" class="form-control text-uppercase">
					</div>
					<div class="col-md-2">
						<label class="form-label">{{ t("Incoterm") }}</label>
						<select v-model="form.incoterm" class="form-select">
							<option value="">—</option>
							<option v-for="ic in INCOTERMS" :key="ic" :value="ic">{{ ic }}</option>
						</select>
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Incoterm Location") }}</label>
						<input v-model="form.incoterm_location" type="text" class="form-control">
					</div>
					<div class="col-md-2">
						<label class="form-label">{{ t("Port of Loading") }}</label>
						<input v-model="form.port_of_loading" type="text" class="form-control">
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Port of Discharge") }}</label>
						<input v-model="form.port_of_discharge" type="text" class="form-control">
					</div>
					<div class="col-md-2">
						<label class="form-label">{{ t("Status") }}</label>
						<select v-model="form.status" class="form-select">
							<option value="DRAFT">DRAFT</option>
							<option value="CONFIRMED">CONFIRMED</option>
							<option value="CANCELLED">CANCELLED</option>
						</select>
					</div>
				</div>

				<hr>
				<h4 class="text-secondary text-uppercase small mb-2">{{ t("Prepayment") }}</h4>
				<div class="row g-3">
					<div class="col-md-6">
						<label class="form-label d-block">{{ t("Prepayment Base") }}</label>
						<div class="form-check form-check-inline">
							<input v-model="form.prepayment_type" class="form-check-input" type="radio" value="AGREED_TOTAL" id="pt-agreed">
							<label class="form-check-label" for="pt-agreed">{{ t("Agreed total") }}</label>
						</div>
						<div class="form-check form-check-inline">
							<input v-model="form.prepayment_type" class="form-check-input" type="radio" value="DOCS_ONLY" id="pt-docs">
							<label class="form-check-label" for="pt-docs">{{ t("Docs only") }}</label>
						</div>
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Advance %") }}</label>
						<input v-model.number="form.advance_pct" type="range" min="0" max="100" class="form-range">
						<div class="small text-secondary">{{ form.advance_pct }}% / {{ 100 - form.advance_pct }}%</div>
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Expected Payment Date") }}</label>
						<DateInput v-model="form.expected_payment_date" />
					</div>
				</div>

				<div class="row g-3 mt-1">
					<div v-if="!hasItems" class="col-md-4">
						<label class="form-label">{{ t("Agreed total") }}</label>
						<MoneyInput v-model="form.agreed_total" :currency="form.currency" :language="user.language" />
					</div>
					<div :class="hasItems ? 'col-md-6' : 'col-md-4'">
						<label class="form-label">{{ t("Bank Agreed") }} <span class="text-secondary small">({{ t("Docs portion") }})</span></label>
						<MoneyInput v-model="form.bank_agreed" :currency="form.currency" :language="user.language" @focus="onBankInput" />
					</div>
					<div :class="hasItems ? 'col-md-6' : 'col-md-4'">
						<label class="form-label">{{ t("Cash Agreed") }} <span class="text-secondary small">({{ t("Cash portion") }})</span></label>
						<MoneyInput v-model="form.cash_agreed" :currency="form.currency" :language="user.language" @focus="onCashInput" />
					</div>
					<div class="col-12">
						<div v-if="!earmarkOk" class="alert alert-warning py-2 px-3 mb-0 small d-flex align-items-center justify-content-between flex-wrap gap-2">
							<span><i class="ti ti-alert-triangle me-1"></i>{{ t("Bank Agreed + Cash Agreed must equal Agreed Total.") }}</span>
							<button type="button" class="btn btn-warning btn-sm font-monospace ms-auto" @click="syncEarmark">
								<i class="ti ti-refresh me-1"></i>{{ t("Sync Prepayment Totals") }}
							</button>
						</div>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Remarks") }}</label>
						<textarea v-model="form.remarks" rows="2" class="form-control"></textarea>
					</div>
				</div>
			</div>
		</div>

		<!-- Items — colour-banded grid with Vendor Category dropdown -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Items") }}</h3>
				<div class="card-actions d-flex gap-2">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="openFillModal">
						<i class="ti ti-wand me-1"></i>{{ t("Fill from category") }}
					</button>
					<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addItemRow">
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
							<th style="min-width: 170px">{{ t("Vendor Category") }}</th>
							<th style="min-width: 200px">{{ t("Product Code/Name") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 90px">{{ t("Boxes") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 100px">{{ t("Box Weight") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 110px">{{ t("Quantity (KG)") }}</th>
							<th class="text-end bg-blue-lt text-blue" style="width: 130px">{{ t("Agreed Price") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end bg-green-lt text-green" style="width: 130px">{{ t("Docs Price") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end bg-blue-lt text-blue" style="width: 140px">{{ t("Agreed Total") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end bg-green-lt text-green" style="width: 140px">{{ t("Docs Total") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end bg-purple-lt text-purple" style="width: 140px">{{ t("Invoiced (KG)") }}</th>
							<th class="text-end bg-warning-lt text-warning" style="width: 140px">{{ t("Remaining Bal (KG)") }}</th>
							<th style="width: 36px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, idx) in form.items" :key="idx">
							<td>
								<!-- Vendor Category Dropdown -->
								<select v-if="categoryOptions.length" v-model="row.category" class="form-select form-select-sm fw-semibold">
									<option value="">— {{ t("N/A") }} —</option>
									<option v-if="row.category && !categoryOptions.includes(row.category)" :value="row.category">{{ row.category }}</option>
									<option v-for="cat in categoryOptions" :key="cat" :value="cat">{{ cat }}</option>
								</select>
								<input v-else v-model="row.category" type="text" class="form-control form-control-sm" :placeholder="t('Vendor Category')">
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
							<td><input v-model.number="row.box_weight_kg" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace" @input="onBoxesOrWeightInput(row)"></td>
							<td><input v-model.number="row.qty" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace text-warning fw-semibold" @input="onQtyInput(row)"></td>
							<td><MoneyInput v-model="row.rate" :currency="form.currency" :language="user.language" :max-fraction-digits="4" hide-currency size="sm" /></td>
							<td><MoneyInput v-model="row.docs_price" :currency="form.currency" :language="user.language" :max-fraction-digits="4" hide-currency size="sm" /></td>
							<td class="text-end font-monospace text-blue bg-blue-lt fw-semibold">{{ fn(rowAmount(row)) }}</td>
							<td class="text-end font-monospace text-green bg-green-lt fw-semibold">{{ fn(rowDocsAmount(row)) }}</td>
							<td class="text-end font-monospace text-nowrap bg-purple-lt">
								<span v-if="getSummaryRow(row)">
									<span class="fw-bold text-purple">{{ fn(getSummaryRow(row).invoiced_qty) }}</span>
									<span class="badge ms-1 font-monospace" :class="getSummaryRow(row).pct >= 100 ? 'bg-success-lt text-success' : 'bg-purple-lt text-purple'" style="font-size: 0.7rem">
										{{ getSummaryRow(row).pct }}%
									</span>
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td class="text-end font-monospace text-nowrap" :class="getSummaryRow(row) && getSummaryRow(row).remaining_qty < 0 ? 'bg-danger-lt' : 'bg-warning-lt'">
								<span v-if="getSummaryRow(row)">
									<span class="fw-bold" :class="getSummaryRow(row).remaining_qty < 0 ? 'text-danger' : 'text-warning'">
										<span v-if="getSummaryRow(row).remaining_qty < 0" class="badge bg-danger-lt text-danger me-1" style="font-size:0.7rem">{{ t("over-shipped") }}</span>
										{{ fn(getSummaryRow(row).remaining_qty) }}
									</span>
								</span>
								<span v-else class="text-secondary">—</span>
							</td>
							<td>
								<button type="button" class="btn btn-icon btn-sm btn-ghost-secondary" :title="t('Remove')" @click="removeItemRow(idx)">
									<i class="ti ti-trash"></i>
								</button>
							</td>
						</tr>
						<tr v-if="!form.items.length">
							<td colspan="13" class="text-secondary text-center py-3">{{ t("No items yet.") }}</td>
						</tr>
					</tbody>
					<tfoot v-if="form.items.length">
						<tr>
							<td colspan="2" class="text-end fw-semibold small bg-light-subtle">{{ t("Totals") }}</td>
							<td class="text-end font-monospace fw-bold text-dark bg-light-subtle">{{ fn(itemsTotalBoxes) }}</td>
							<td class="text-end text-muted small bg-light-subtle">—</td>
							<td class="text-end font-monospace fw-bold text-dark bg-light-subtle">{{ fn(itemsTotalQty) }}</td>
							<td colspan="2" class="text-end text-muted small bg-light-subtle">—</td>
							<td class="text-end font-monospace fw-semibold text-blue bg-blue-lt">{{ fm(itemsAgreedTotal, form.currency) }}</td>
							<td class="text-end font-monospace fw-semibold text-green bg-green-lt">{{ fm(itemsDocsTotal, form.currency) }}</td>
							<td class="text-end font-monospace fw-semibold text-purple bg-purple-lt">{{ fn(itemsTotalInvoiced) }}</td>
							<td class="text-end font-monospace fw-semibold text-warning bg-warning-lt">{{ fn(itemsTotalRemaining) }}</td>
							<td class="bg-light-subtle"></td>
						</tr>
					</tfoot>
				</table>
			</div>
			<div class="card-footer d-flex align-items-center justify-content-between bg-light py-2 px-3 flex-wrap gap-2">
				<div class="text-secondary small font-monospace d-flex align-items-center gap-3">
					<span>{{ t("Agreed Total") }}: <strong class="text-blue">{{ fm(itemsAgreedTotal, form.currency) }}</strong></span>
					<span>{{ t("Docs Total") }}: <strong class="text-green">{{ fm(itemsDocsTotal, form.currency) }}</strong></span>
					<span>{{ t("Cash Difference") }}: <strong class="text-warning">{{ fm(itemsCashDiff, form.currency) }}</strong></span>
				</div>
				<div class="d-flex align-items-center gap-2">
					<button v-if="!earmarkOk" type="button" class="btn btn-outline-warning btn-sm font-monospace" @click="syncEarmark">
						<i class="ti ti-refresh me-1"></i>{{ t("Sync Totals") }}
					</button>
					<button type="button" class="btn btn-primary" :disabled="saving || loading || !earmarkOk" @click="saveProforma">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>
						<i v-else class="ti ti-device-floppy me-1"></i>{{ isCreate ? t("Save Proforma") : t("Update & Save") }}
					</button>
				</div>
			</div>
		</div>

		<!-- Commercial Invoices Fulfillment KPI Card -->
		<div v-if="form.invoiced_summary && form.invoiced_summary.items && form.invoiced_summary.items.length" class="card mb-3">
			<div class="card-header bg-green-lt py-2">
				<h3 class="card-title text-success mb-0">
					<i class="ti ti-chart-bar me-2"></i>{{ t("Commercial Invoices — Fulfillment Summary") }}
				</h3>
			</div>
			<div class="card-body py-2">
				<div class="row align-items-center g-3">
					<div class="col-md-3">
						<div class="small text-secondary">{{ t("Overall Invoiced Progress") }}</div>
						<div class="d-flex align-items-center gap-2 mt-1">
							<div class="progress flex-grow-1" style="height: 8px;">
								<div class="progress-bar bg-success" :style="{ width: Math.min(100, form.invoiced_summary.pct) + '%' }"></div>
							</div>
							<span class="badge bg-success-lt text-success font-monospace fw-bold">{{ form.invoiced_summary.pct }}%</span>
						</div>
					</div>
					<div class="col-md-3">
						<div class="small text-secondary">{{ t("Total Ordered") }}</div>
						<div class="fw-bold font-monospace text-body">{{ fn(form.invoiced_summary.total_ordered_kg) }} kg</div>
					</div>
					<div class="col-md-3">
						<div class="small text-secondary">{{ t("Total Invoiced (drawn to CIs)") }}</div>
						<div class="fw-bold font-monospace text-success">{{ fn(form.invoiced_summary.total_invoiced_kg) }} kg</div>
					</div>
					<div class="col-md-3">
						<div class="small text-secondary">{{ t("Remaining Balance") }}</div>
						<div class="fw-bold font-monospace text-warning">{{ fn(form.invoiced_summary.total_remaining_kg) }} kg</div>
					</div>
				</div>
			</div>
		</div>

		<!-- PI <-> CI match: discrepancies + sub-cut breakdown (sandbox port) -->
		<div v-if="docName && matchSummary" class="card mb-3">
			<div class="card-header d-flex align-items-center flex-wrap gap-2">
				<h3 class="card-title mb-0"><i class="ti ti-scale me-2"></i>{{ t("Shipment match") }}</h3>
				<span class="badge bg-secondary-lt font-monospace">{{ matchSummary.matched_lines || 0 }} {{ t("matched") }}</span>
				<span v-if="matchSummary.orphan_lines" class="badge bg-yellow-lt text-yellow font-monospace">{{ matchSummary.orphan_lines }} {{ t("not on any PI") }}</span>
				<span v-if="matchSummary.over_keys" class="badge bg-red-lt text-red font-monospace">{{ matchSummary.over_keys }} {{ t("over-shipped keys") }} · +{{ matchSummary.over_boxes }}</span>
				<span class="badge bg-azure-lt text-azure font-monospace ms-auto">{{ t("Remaining") }}: {{ matchSummary.remaining_boxes }} {{ t("bx") }}</span>
				<router-link :to="{ path: '/imports/discrepancies', query: { pi: docName } }" class="btn btn-ghost-secondary btn-sm">
					{{ t("Open in report") }}
				</router-link>
			</div>
			<div v-if="matchLoading" class="card-body text-secondary">
				<span class="spinner-border spinner-border-sm me-2"></span>{{ t("Checking shipments…") }}
			</div>
			<template v-else>
				<div v-if="flaggedRows.length" class="table-responsive">
					<table class="table table-vcenter table-sm">
						<thead>
							<tr>
								<th>{{ t("CI Number") }}</th>
								<th>{{ t("Category") }}</th>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Boxes") }}</th>
								<th>{{ t("Issues") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="r in flaggedRows" :key="r.row_name">
								<td class="font-monospace">
									<router-link :to="{ name: 'imports-commercial-invoice', params: { name: r.ci_name } }">{{ r.ci_number }}</router-link>
								</td>
								<td>{{ r.category || "—" }}</td>
								<td class="text-secondary">{{ r.item || "—" }}</td>
								<td class="text-end font-monospace">{{ r.boxes }}</td>
								<td>
									<span v-for="d in r.diffs" :key="d.code" class="badge me-1"
										:class="d.level === 'error' ? 'bg-red-lt text-red' : 'bg-yellow-lt text-yellow'">{{ d.code }}</span>
								</td>
							</tr>
						</tbody>
					</table>
				</div>
				<div v-else class="card-body text-secondary small">
					{{ t("Every shipped line agrees with this proforma.") }}
				</div>
				<div v-if="subCuts.length" class="card-body border-top">
					<div class="text-secondary small text-uppercase fw-bold mb-2">{{ t("Sub-cut breakdown") }}</div>
					<div class="row g-2">
						<div v-for="g in subCuts" :key="g.category" class="col-12 col-md-6 col-xl-4">
							<div class="border rounded p-2">
								<div class="d-flex align-items-baseline">
									<span class="fw-semibold">{{ g.category }}</span>
									<span class="ms-auto font-monospace small">{{ g.boxes }} {{ t("bx") }} · {{ g.qty }} {{ t("kg") }}</span>
								</div>
								<div class="text-secondary small mt-1">
									<span v-for="l in g.lines" :key="l.row_name" class="me-2 font-monospace">{{ l.item || l.description || "—" }}</span>
								</div>
							</div>
						</div>
					</div>
				</div>
			</template>
		</div>

		<!-- Linked Commercial Invoices & Containers -->
		<div v-if="form.linked_cis && form.linked_cis.length" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title"><i class="ti ti-truck-delivery me-2"></i>{{ t("Linked Commercial Invoices & Containers") }}</h3>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("CI Number") }}</th>
							<th>{{ t("CI Date") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("ETD / ETA") }}</th>
							<th>{{ t("Containers") }}</th>
							<th class="text-end">{{ t("Agreed Total") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="ci in form.linked_cis" :key="ci.name">
							<td class="font-monospace fw-bold text-primary">{{ ci.ci_number || ci.name }}</td>
							<td class="text-nowrap">{{ formatDate(ci.ci_date) }}</td>
							<td><span class="badge" :class="getStatusBadgeClass('Commercial Invoice', ci.status)">{{ ci.status }}</span></td>
							<td class="small font-monospace">{{ formatDate(ci.etd) }} / {{ formatDate(ci.eta) }}</td>
							<td>
								<div v-if="ci.containers && ci.containers.length" class="d-flex flex-wrap gap-1">
									<span v-for="cnt in ci.containers" :key="cnt.name" class="badge bg-azure-lt font-monospace py-1 px-2">
										<i class="ti ti-box me-1"></i>{{ cnt.container_number || cnt.name }} ({{ cnt.container_type || 'RF' }}, {{ cnt.status }})
									</span>
								</div>
								<span v-else class="text-secondary small italic">{{ t("No containers") }}</span>
							</td>
							<td class="text-end font-monospace fw-semibold">{{ fm(ci.agreed_total, ci.currency) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
			<PiAdvanceLedger v-if="form.advance_ledger" :ledger="form.advance_ledger" />
		</div>

		<!-- Linked Advance Payments -->
		<div class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between">
				<h3 class="card-title mb-0"><i class="ti ti-cash me-2 text-success"></i>{{ t("Advance Payments & Deposit Tracking") }}</h3>
				<button
					v-if="!isCreate && form.name"
					type="button"
					class="btn btn-sm btn-outline-success"
					@click="openAdvanceModal"
				>
					<i class="ti ti-plus me-1"></i>{{ t("New Advance Payment") }}
				</button>
			</div>
			<div v-if="form.advance_summary" class="card-body border-bottom bg-light-subtle py-2">
				<div class="row g-3 text-center">
					<div class="col-4">
						<div class="text-secondary small">{{ t("Paid via Bank") }}</div>
						<div class="fw-bold font-monospace text-primary">{{ fm(form.advance_summary.paid_bank, form.currency) }}</div>
					</div>
					<div class="col-4">
						<div class="text-secondary small">{{ t("Paid via Cash") }}</div>
						<div class="fw-bold font-monospace text-orange">{{ fm(form.advance_summary.paid_cash, form.currency) }}</div>
					</div>
					<div class="col-4">
						<div class="text-secondary small">{{ t("Total Advance Paid") }}</div>
						<div class="fw-bold font-monospace text-success">{{ fm(form.advance_summary.paid_total, form.currency) }}</div>
					</div>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter table-hover mb-0">
					<thead>
						<tr>
							<th>{{ t("Payment Entry") }}</th>
							<th>{{ t("Date") }}</th>
							<th>{{ t("Stream") }}</th>
							<th>{{ t("Status") }}</th>
							<th>{{ t("Reference") }}</th>
							<th class="text-end">{{ t("Paid Amount") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="pe in (form.advance_payments || [])" :key="pe.name">
							<td class="font-monospace fw-bold text-primary">{{ pe.name }}</td>
							<td>{{ formatDate(pe.posting_date) }}</td>
							<td>
								<span v-if="pe.payment_stream === 'Cash' || (pe.mode_of_payment || '').toLowerCase().includes('cash')" class="badge bg-orange-lt">
									<i class="ti ti-cash me-1"></i>{{ t("Cash") }}
								</span>
								<span v-else class="badge bg-blue-lt">
									<i class="ti ti-building-bank me-1"></i>{{ t("Bank") }}
								</span>
							</td>
							<td>
								<span v-if="pe.docstatus === 1" class="badge bg-success-lt">{{ t("Submitted") }}</span>
								<span v-else-if="pe.docstatus === 0" class="badge bg-warning-lt">{{ t("Draft") }}</span>
								<span v-else class="badge bg-secondary-lt">{{ t("Cancelled") }}</span>
							</td>
							<td class="font-monospace small text-secondary">{{ pe.reference_no || "—" }}</td>
							<td class="text-end font-monospace fw-semibold text-success">{{ fm(pe.paid_amount || pe.allocated_to_po, form.currency) }}</td>
						</tr>
						<tr v-if="!form.advance_payments || !form.advance_payments.length">
							<td colspan="6" class="text-center text-secondary py-3">{{ t("No advance payments recorded yet.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Destructive actions sit at the bottom, away from Save -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-body d-flex flex-wrap align-items-center gap-2">
				<div class="text-secondary small flex-grow-1">
					{{ t("Deleting shows everything that depends on this proforma before anything is removed.") }}
				</div>
				<button type="button" class="btn btn-outline-danger" :disabled="deletePlanning" @click="openDeletePlan">
					<span v-if="deletePlanning" class="spinner-border spinner-border-sm me-1"></span>
					<i v-else class="ti ti-trash me-1"></i>{{ t("Delete") }}
				</button>
			</div>
		</div>

		<!-- What deleting this proforma would touch — shown before anything happens -->
		<div v-if="deleteModalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
			<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Delete proforma") }}</h5>
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
							{{ t("Nothing else points at this proforma.") }}
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

		<!-- Fill items from vendor category -->
		<div v-if="fillModalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
			<div class="modal-dialog modal-dialog-centered">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Fill from category") }}</h5>
						<button type="button" class="btn-close" @click="closeFillModal"></button>
					</div>
					<div class="modal-body">
						<div class="row g-3">
							<div class="col-12">
								<label class="form-label small mb-1">{{ t("Category") }}</label>
								<select v-model="fillCategory" class="form-select form-select-sm" :disabled="fillCategoriesLoading">
									<option value="">—</option>
									<option v-for="c in fillCategories" :key="c.name" :value="c.name">{{ c.display_name || c.category_name }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label small mb-1">{{ t("Containers") }}</label>
								<input v-model.number="fillContainers" type="number" min="1" step="1" class="form-control form-control-sm">
							</div>
							<div class="col-md-6">
								<label class="form-label small mb-1">{{ t("Box weight (kg)") }}</label>
								<input v-model.number="fillBoxWeight" type="number" min="0" step="0.01" class="form-control form-control-sm">
							<div class="form-hint small">{{ t("Used only for rows where the category has no box weight.") }}</div>
							</div>
							<div class="col-md-6">
								<label class="form-label small mb-1">{{ t("Agreed price") }}</label>
								<MoneyInput v-model="fillAgreedPrice" :currency="form.currency" :language="user.language" size="sm" />
							</div>
							<div class="col-md-6">
								<label class="form-label small mb-1">{{ t("Docs price") }}</label>
								<MoneyInput v-model="fillDocsPrice" :currency="form.currency" :language="user.language" size="sm" />
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" @click="closeFillModal">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="fillApplying || !fillCategory" @click="applyFillCategory">
							<span v-if="fillApplying" class="spinner-border spinner-border-sm me-1"></span>{{ t("Apply") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Smart Advance Payment Modal (Dual-Pricing: Agreed vs Docs) -->
		<div v-if="advOpen" class="modal modal-blur fade show d-block" tabindex="-1" style="background: rgba(0, 0, 0, 0.55); z-index: 1055;">
			<div class="modal-dialog modal-dialog-centered modal-lg">
				<div class="modal-content shadow-lg border-0">
					<!-- Header -->
					<div class="modal-header bg-surface py-3 px-4 border-bottom">
						<div>
							<div class="d-flex align-items-center gap-2">
								<span class="avatar avatar-sm bg-green-lt text-green rounded">
									<i class="ti ti-cash-banknote fs-2"></i>
								</span>
								<div>
									<h4 class="modal-title fw-bold mb-0 text-dark">{{ t("Record Advance Payment") }}</h4>
									<div class="text-secondary small font-monospace">
										{{ form.supplier_pi_ref || form.name }} · {{ form.supplier_name || form.supplier }}
									</div>
								</div>
							</div>
						</div>
						<button type="button" class="btn-close" :disabled="advSaving" @click="advOpen = false"></button>
					</div>

					<div class="modal-body p-4 bg-light-subtle">
						<!-- Top Card: PI Context & Totals -->
						<div class="card mb-3 border-0 shadow-sm">
							<div class="card-body py-3 px-4">
								<div class="row g-3 text-center text-sm-start align-items-center">
									<div class="col-sm-4 border-end-sm">
										<div class="text-secondary small text-uppercase fw-semibold">{{ t("Total Agreed PI") }}</div>
										<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ fm(targetAgreedTotal, form.currency) }}</div>
									</div>
									<div class="col-sm-4 border-end-sm">
										<div class="text-secondary small text-uppercase fw-semibold d-flex align-items-center gap-1">
											<i class="ti ti-building-bank text-blue"></i> {{ t("Official Docs Total") }}
										</div>
										<div class="h3 mb-0 font-monospace text-dark fw-semibold">{{ fm(targetDocsTotal, form.currency) }}</div>
									</div>
									<div class="col-sm-4">
										<div class="text-secondary small text-uppercase fw-semibold d-flex align-items-center gap-1">
											<i class="ti ti-cash text-orange"></i> {{ t("Cash Difference") }}
										</div>
										<div class="h3 mb-0 font-monospace text-orange fw-semibold">{{ fm(targetCashDiff, form.currency) }}</div>
									</div>
								</div>
							</div>
						</div>

						<!-- Section 1: Percentage & Strategy Selection -->
						<div class="card mb-3 border-0 shadow-sm">
							<div class="card-body p-3 p-md-4">
								<!-- Percentage Selector -->
								<div class="d-flex flex-wrap align-items-center justify-content-between gap-2 mb-3 pb-3 border-bottom">
									<div>
										<label class="form-label fw-bold text-uppercase small text-secondary mb-1">
											{{ t("Advance Percentage") }}
										</label>
										<div class="text-muted small">
											{{ t("Select percentage or enter custom value") }}
										</div>
									</div>
									<div class="d-flex align-items-center gap-1 flex-wrap">
										<button
											v-for="p in [10, 20, 30, 50, 100]"
											:key="p"
											type="button"
											class="btn btn-sm"
											:class="advPct === p && !customPct ? 'btn-primary shadow-sm' : 'btn-outline-secondary bg-white'"
											@click="setPercentage(p)"
										>
											{{ p }}%
										</button>
										<div class="input-group input-group-sm ms-1" style="width: 95px;">
											<input
												v-model="customPct"
												type="number"
												min="1"
												max="100"
												placeholder="Custom"
												class="form-control text-center font-monospace"
												@input="onCustomPctInput"
											/>
											<span class="input-group-text">%</span>
										</div>
									</div>
								</div>

								<!-- Strategy Preset Cards -->
								<label class="form-label fw-bold text-uppercase small text-secondary mb-2">
									{{ t("Payment Strategy Presets") }}
								</label>
								<div class="row g-2">
									<!-- 1. Official Docs Only -->
									<div class="col-sm-6 col-lg-3">
										<div
											class="card h-100 cursor-pointer p-3 border"
											:class="advStrategy === 'DOCS_ONLY' ? 'border-primary bg-primary-lt shadow-sm' : 'border-light bg-white'"
											@click="applyStrategy('DOCS_ONLY')"
										>
											<div class="d-flex align-items-center justify-content-between mb-1">
												<span class="badge bg-blue-lt text-blue small fw-bold">
													<i class="ti ti-building-bank me-1"></i>{{ t("Docs Only") }}
												</span>
												<i v-if="advStrategy === 'DOCS_ONLY'" class="ti ti-circle-check text-primary fs-3"></i>
											</div>
											<div class="h3 mb-1 font-monospace text-dark">{{ fm(calcDocsOnlyBank, form.currency) }}</div>
											<div class="text-secondary small lh-sm">
												{{ advPct }}% {{ t("of Docs Total to Bank") }} ($0 {{ t("Cash") }})
											</div>
										</div>
									</div>

									<!-- 2. Proportional Split -->
									<div class="col-sm-6 col-lg-3">
										<div
											class="card h-100 cursor-pointer p-3 border"
											:class="advStrategy === 'SPLIT' ? 'border-success bg-success-lt shadow-sm' : 'border-light bg-white'"
											@click="applyStrategy('SPLIT')"
										>
											<div class="d-flex align-items-center justify-content-between mb-1">
												<span class="badge bg-green-lt text-green small fw-bold">
													<i class="ti ti-scale me-1"></i>{{ t("Split Bank + Cash") }}
												</span>
												<i v-if="advStrategy === 'SPLIT'" class="ti ti-circle-check text-success fs-3"></i>
											</div>
											<div class="h3 mb-1 font-monospace text-dark">{{ fm(calcFullAdvance, form.currency) }}</div>
											<div class="text-secondary small lh-sm">
												{{ fm(calcSplitBank, form.currency) }} 🏦 + {{ fm(calcSplitCash, form.currency) }} 💵
											</div>
										</div>
									</div>

									<!-- 3. 100% Bank -->
									<div class="col-sm-6 col-lg-3">
										<div
											class="card h-100 cursor-pointer p-3 border"
											:class="advStrategy === 'ALL_BANK' ? 'border-primary bg-primary-lt shadow-sm' : 'border-light bg-white'"
											@click="applyStrategy('ALL_BANK')"
										>
											<div class="d-flex align-items-center justify-content-between mb-1">
												<span class="badge bg-indigo-lt text-indigo small fw-bold">
													<i class="ti ti-credit-card me-1"></i>{{ t("100% Bank") }}
												</span>
												<i v-if="advStrategy === 'ALL_BANK'" class="ti ti-circle-check text-indigo fs-3"></i>
											</div>
											<div class="h3 mb-1 font-monospace text-dark">{{ fm(calcFullAdvance, form.currency) }}</div>
											<div class="text-secondary small lh-sm">
												{{ advPct }}% {{ t("of full Agreed Total via Bank") }}
											</div>
										</div>
									</div>

									<!-- 4. 100% Cash -->
									<div class="col-sm-6 col-lg-3">
										<div
											class="card h-100 cursor-pointer p-3 border"
											:class="advStrategy === 'ALL_CASH' ? 'border-warning bg-warning-lt shadow-sm' : 'border-light bg-white'"
											@click="applyStrategy('ALL_CASH')"
										>
											<div class="d-flex align-items-center justify-content-between mb-1">
												<span class="badge bg-orange-lt text-orange small fw-bold">
													<i class="ti ti-cash me-1"></i>{{ t("100% Cash") }}
												</span>
												<i v-if="advStrategy === 'ALL_CASH'" class="ti ti-circle-check text-warning fs-3"></i>
											</div>
											<div class="h3 mb-1 font-monospace text-dark">{{ fm(calcFullAdvance, form.currency) }}</div>
											<div class="text-secondary small lh-sm">
												{{ advPct }}% {{ t("of full Agreed Total via Cash") }}
											</div>
										</div>
									</div>
								</div>
							</div>
						</div>

						<!-- Section 2: Bank & Cash Payment Entry Inputs -->
						<div class="card mb-3 border-0 shadow-sm">
							<div class="card-body p-3 p-md-4">
								<div class="row g-3">
									<!-- Bank Input Card -->
									<div class="col-md-6">
										<div class="p-3 rounded bg-blue-lt border border-blue-subtle h-100">
											<div class="d-flex align-items-center justify-content-between mb-2">
												<label class="form-label fw-bold text-blue mb-0 d-flex align-items-center gap-1">
													<i class="ti ti-building-bank fs-3"></i> {{ t("Official Bank Amount") }}
												</label>
												<span class="badge bg-blue text-white">{{ form.currency }}</span>
											</div>
											<div class="mb-2">
												<label class="form-label small text-secondary mb-1">{{ t("Paid From (Bank Account)") }}</label>
												<select v-model="advSelectedBank" class="form-select form-select-sm font-monospace" :disabled="advSaving">
													<option value="">{{ t("Default Bank Account") }}</option>
													<option v-for="acc in companyBankAccounts" :key="acc.name" :value="acc.name">
														{{ accountLabel(acc) }} ({{ acc.account_currency }})
													</option>
												</select>
											</div>
											<MoneyInput
												v-model="advBank"
												:currency="form.currency"
												:language="user.language"
												@update:model-value="onManualAmountChange"
											/>
											<div class="small text-secondary mt-2 d-flex align-items-center gap-1">
												<i class="ti ti-info-circle"></i>
												{{ t("Creates DRAFT Payment Entry for bank account.") }}
											</div>
										</div>
									</div>

									<!-- Cash Input Card -->
									<div class="col-md-6">
										<div class="p-3 rounded bg-orange-lt border border-orange-subtle h-100">
											<div class="d-flex align-items-center justify-content-between mb-2">
												<label class="form-label fw-bold text-orange mb-0 d-flex align-items-center gap-1">
													<i class="ti ti-cash fs-3"></i> {{ t("Cash Safe Amount") }}
												</label>
												<span class="badge bg-orange text-white">{{ form.currency }}</span>
											</div>
											<div class="mb-2">
												<label class="form-label small text-secondary mb-1">{{ t("Paid From (Cash Account)") }}</label>
												<select v-model="advSelectedCash" class="form-select form-select-sm font-monospace" :disabled="advSaving">
													<option value="">{{ t("Default Cash Account") }}</option>
													<option v-for="acc in companyCashAccounts" :key="acc.name" :value="acc.name">
														{{ accountLabel(acc) }} ({{ acc.account_currency }})
													</option>
												</select>
											</div>
											<MoneyInput
												v-model="advCash"
												:currency="form.currency"
												:language="user.language"
												@update:model-value="onManualAmountChange"
											/>
											<div class="small text-secondary mt-2 d-flex align-items-center gap-1">
												<i class="ti ti-info-circle"></i>
												{{ t("Creates DRAFT Payment Entry for cash desk/safe.") }}
											</div>
										</div>
									</div>

									<!-- Payment Date & Reference No -->
									<div class="col-md-6">
										<label class="form-label small fw-semibold text-secondary mb-1">{{ t("Payment Date") }}</label>
										<DateInput v-model="advDate" />
									</div>

									<div class="col-md-6">
										<label class="form-label small fw-semibold text-secondary mb-1">{{ t("Payment Reference / Memo") }}</label>
										<input v-model="advRef" type="text" class="form-control" placeholder="e.g. ADV-REF-001" />
									</div>
								</div>
							</div>
						</div>

						<!-- Section 3: Summary Banner -->
						<div class="card border-0 shadow-sm bg-surface">
							<div class="card-body py-3 px-4">
								<div class="d-flex flex-wrap align-items-center justify-content-between gap-2">
									<div>
										<div class="text-secondary small fw-semibold text-uppercase">{{ t("Total Advance to Record") }}</div>
										<div class="d-flex align-items-baseline gap-2">
											<span class="font-monospace fw-bold fs-2 text-success">
												{{ fm(Number(advBank || 0) + Number(advCash || 0), form.currency) }}
											</span>
											<span v-if="targetAgreedTotal > 0" class="badge bg-success-lt font-monospace">
												{{ ((Number(advBank || 0) + Number(advCash || 0)) / targetAgreedTotal * 100).toFixed(1) }}% {{ t("of PI") }}
											</span>
										</div>
									</div>

									<div v-if="currentPaidTotal > 0" class="text-sm-end small">
										<div class="text-muted">
											{{ t("Previously Recorded:") }}
											<span class="font-monospace fw-semibold">{{ fm(currentPaidTotal, form.currency) }}</span>
											({{ fm(currentPaidBank, form.currency) }} 🏦 + {{ fm(currentPaidCash, form.currency) }} 💵)
										</div>
										<div class="text-secondary mt-1">
											{{ t("Cumulative After Record:") }}
											<strong class="font-monospace text-dark">
												{{ fm(currentPaidTotal + Number(advBank || 0) + Number(advCash || 0), form.currency) }}
											</strong>
										</div>
									</div>
								</div>
							</div>
						</div>
					</div>

					<!-- Footer -->
					<div class="modal-footer bg-surface py-3 px-4 border-top">
						<button type="button" class="btn btn-outline-secondary" :disabled="advSaving" @click="advOpen = false">
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-success px-4"
							:disabled="advSaving || (Number(advBank || 0) <= 0 && Number(advCash || 0) <= 0)"
							@click="submitAdvancePayment"
						>
							<span v-if="advSaving" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-check me-2"></i>
							{{ t("Create Draft Payment Entries") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
