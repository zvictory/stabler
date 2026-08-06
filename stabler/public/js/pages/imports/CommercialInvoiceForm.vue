<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { blockerText, cascadeRows, recordRoute } from "../../composables/deleteImpact.js";
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

const containerTransportMap = computed(() => {
	const map = {};
	if (transportData.value?.by_container) {
		for (const item of transportData.value.by_container) {
			map[item.container] = item.amount;
		}
	}
	return map;
});

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
// Selecting a proforma copies its group down, but a CI raised without one had
// no way to be grouped at all — hence the explicit selector.
const piGroups = ref([]);
const groupOptions = computed(() => [
	{ value: "", label: t("No PI group") },
	...piGroups.value.map((g) => ({ value: g.name, label: g.title || g.name })),
]);
const companyPOs = ref([]);
const poOptions = computed(() => [
	{ value: "", label: t("Select purchase order…") },
	...companyPOs.value.map((p) => ({
		value: p.name,
		label: `${p.name} · ${p.supplier_name || p.supplier}`,
	})),
]);

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

// Fill from category modal state
const fillModalOpen = ref(false);
const fillCategories = ref([]);
const fillCategory = ref("");
const fillContainers = ref(1);
const fillBoxWeight = ref(20);
const fillAgreedPrice = ref(0);
const fillDocsPrice = ref(0);
const fillCategoriesLoading = ref(false);
const fillApplying = ref(false);

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
		customs_declarations: [],
		packing_summary: {
			status: "Incomplete",
			container_count: 0,
			containers_with_items: 0,
			expected_items: [],
			reconciliation: [],
		},
		grn: null,
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
const QTY_TOLERANCE_KG = 0.5;
// Half a cent — mirrors `_imports_rules.PRICE_TOLERANCE`. The PI books prices at
// 3 decimals and the CI at 2, so exact equality flags the stored precision as a
// pricing error. A real one is at least a whole cent.
const PRICE_TOLERANCE = 0.005;
const priceEq = (a, b) => round4(Math.abs(round4(a) - round4(b))) <= PRICE_TOLERANCE;

function getTrackingRow(row) {
	if (!form.value.pi_tracking) return null;
	const pi = row.custom_proforma_invoice || form.value.custom_proforma_invoice || "";
	if (!pi) return null;
	const cat = normKey(row.category);
	// Match on (PI, category) and never on `item`: a PI line such as
	// BUFFALO COMPENSATED is a bundle the CI breaks into sub-cuts, so the item
	// codes legitimately differ. The old `tr.item === item` fallback ignored the
	// PI entirely and bound the row to another proforma's balance.
	// An empty category is a hole, not a key — matching it would bind the row to
	// whichever other category-less line sits on the same PI.
	const exact = cat
		? form.value.pi_tracking.find(
				(tr) => tr.proforma_invoice === pi && normKey(tr.category) === cat
			)
		: null;
	if (exact) return exact;
	// A category-less match is only safe on a single-line contract; otherwise
	// "first line of that PI" would display a foreign remaining balance.
	const ofPi = form.value.pi_tracking.filter((tr) => tr.proforma_invoice === pi);
	return ofPi.length === 1 ? ofPi[0] : null;
}

// Mirrors `_imports_rules.diff_ci_line` — same codes, same half-cent price
// tolerance, same 0.5 kg tolerance. Client-side so the badge is live while editing,
// before anything is saved; the server-side report is the authoritative one.
function rowDiffs(row) {
	const pi = row.custom_proforma_invoice || form.value.custom_proforma_invoice || "";
	if (!pi) {
		return [{ code: "unattributable", level: "error", label: t("Not linked to any PI") }];
	}
	const tr = getTrackingRow(row);
	if (!tr) {
		// Same split as `_imports_rules.diff_ci_line`: a blank category is the
		// line's own defect, not a missing PI link.
		return normKey(row.category)
			? [{ code: "unattributable", level: "error", label: t("Not on any PI line") }]
			: [{ code: "missing_category", level: "error", label: t("No category on the line") }];
	}

	const out = [];
	const agreed = (tr.agreed_prices || []).map(round4);
	if (agreed.length && !agreed.some((p) => priceEq(p, row.rate))) {
		out.push({
			code: "price_agreed",
			level: "warn",
			label: t("Agreed price differs from PI ({prices})", { prices: agreed.join(" / ") }),
		});
	}
	const docs = (tr.docs_prices || []).map(round4);
	if (docs.length && !docs.some((p) => priceEq(p, row.docs_price))) {
		out.push({
			code: "price_docs",
			level: "warn",
			label: t("Docs price differs from PI ({prices})", { prices: docs.join(" / ") }),
		});
	}

	const boxes = Number(row.boxes) || 0;
	const bw = Number(row.box_weight_kg) || 0;
	const qty = Number(row.qty) || 0;
	if (boxes && bw && qty && Math.abs(boxes * bw - qty) > QTY_TOLERANCE_KG) {
		out.push({ code: "qty_arithmetic", level: "warn", label: t("Boxes × box weight ≠ quantity") });
	}

	const piItems = (tr.items || []).map(normKey);
	if (row.item && piItems.length && !piItems.includes(normKey(row.item))) {
		out.push({ code: "sub_cut", level: "info", label: t("Sub-cut of the PI line") });
	}
	return out;
}

function rowDiffLevel(row) {
	const diffs = rowDiffs(row);
	for (const level of ["error", "warn", "info"]) {
		if (diffs.some((d) => d.level === level)) return level;
	}
	return null;
}
function rowDiffTitle(row) {
	return rowDiffs(row)
		.map((d) => d.label)
		.join("\n");
}
function rowPiTitle(row) {
	const pi = row.custom_proforma_invoice || form.value.custom_proforma_invoice || "";
	if (!pi) return t("Not linked to any PI");
	return row.custom_proforma_invoice ? pi : `${pi} — ${t("Inherited from the invoice header")}`;
}
const nonCompliantCount = computed(
	() => (form.value.items || []).filter((r) => ["error", "warn"].includes(rowDiffLevel(r))).length
);

const itemsAgreedTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowAmount(r), 0));
const itemsDocsTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowDocsAmount(r), 0));
const itemsCashDiff = computed(() => itemsAgreedTotal.value - itemsDocsTotal.value);
const itemCategories = computed(() => [
	...new Set((form.value.items || []).map((r) => r.category).filter(Boolean)),
]);

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

function addPoLink() {
	form.value.po_links.push({ purchase_order: "" });
}
function removePoLink(i) {
	form.value.po_links.splice(i, 1);
}

// Fill from category modal actions
async function openFillModal() {
	fillModalOpen.value = true;
	fillCategoriesLoading.value = true;
	try {
		fillCategories.value = await call("stabler.api.imports.list_vendor_categories", {
			company: activeCompany.value,
			vendor: form.value.supplier || undefined,
		});
	} catch (_) {
		fillCategories.value = [];
	} finally {
		fillCategoriesLoading.value = false;
	}
}
function closeFillModal() {
	fillModalOpen.value = false;
}
async function applyFillCategory() {
	if (!fillCategory.value) return;
	fillApplying.value = true;
	try {
		// `vendor_category_detail` already returns the category's item rows with
		// boxes-per-container — the old call named an endpoint that never existed,
		// so Apply threw every time.
		const detail = await call("stabler.api.imports.vendor_category_detail", {
			name: fillCategory.value,
		});
		const catItems = detail?.items || [];
		const cnts = Number(fillContainers.value) || 1;
		const bw = Number(fillBoxWeight.value) || 0;
		const ap = Number(fillAgreedPrice.value) || 0;
		const dp = Number(fillDocsPrice.value) || 0;
		for (const ci of catItems) {
			const boxes = (Number(ci.boxes_per_container) || 0) * cnts;
			const qty = round2(boxes * bw);
			form.value.items.push({
				category: detail.display_name || detail.category_name || fillCategory.value,
				item: ci.item_code,
				description: ci.item_name || "",
				boxes,
				box_weight_kg: bw,
				qty,
				uom: ci.stock_uom || "Kg",
				rate: ap,
				docs_price: dp,
			});
		}
		fillModalOpen.value = false;
		toast.success(t("Added {count} items from category.", { count: catItems.length }));
	} catch (err) {
		// Leave the modal open — the user's picks survive a retry.
		toast.error(err?.message || t("Could not load category items."));
	} finally {
		fillApplying.value = false;
	}
}

// ---- Multi-PI Smart Fill Modal State ----
const multiPiModalOpen = ref(false);
const multiPiLoading = ref(false);
const multiPiProformas = ref([]);
const multiPiLines = ref([]);
const multiPiAllocations = ref({});
// Which sub-cut to book a bundle line against, keyed like the allocations.
const multiPiItems = ref({});

// The allocation key mirrors the backend match key: (proforma, category). It
// used to include `item`, which is now empty on every compensated bundle — the
// whole modal would have collapsed onto one colliding key.
const multiPiKey = (line) => `${line.pi_name}::${normKey(line.category)}`;

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

async function openMultiPiSmartFill() {
	if (!form.value.supplier) {
		toast.error(t("Please select a supplier first."));
		return;
	}
	multiPiModalOpen.value = true;
	multiPiLoading.value = true;
	multiPiAllocations.value = {};
	multiPiItems.value = {};
	try {
		const res = await call("stabler.api.imports.get_vendor_available_pi_lines", {
			company: activeCompany.value,
			supplier: form.value.supplier,
			exclude_ci: form.value.name || undefined,
		});
		multiPiProformas.value = res.proformas || [];
		multiPiLines.value = res.lines || [];

		for (const line of multiPiLines.value) {
			const key = multiPiKey(line);
			// Over-shipped keys default to 0 — the contract is already exceeded,
			// so pre-filling more boxes would only deepen the breach.
			multiPiAllocations.value[key] = line.remaining_boxes > 0 ? line.remaining_boxes : 0;
			multiPiItems.value[key] = multiPiItemOptions(line)[0] || "";
		}
	} catch (err) {
		toast.error(err?.message || t("Could not fetch available PI lines."));
	} finally {
		multiPiLoading.value = false;
	}
}

function applyMultiPiAllocation() {
	let addedCount = 0;
	for (const line of multiPiLines.value) {
		const key = multiPiKey(line);
		const boxes = Math.max(0, parseInt(multiPiAllocations.value[key] || 0));
		if (boxes > 0) {
			const bw = line.box_weight_kg || DEFAULT_BOX_WEIGHT_KG;
			const qty = round2(boxes * bw);
			form.value.items.push({
				custom_proforma_invoice: line.pi_name,
				category: line.category,
				item: multiPiItems.value[key] || line.item || "",
				description: line.description || "",
				hs_code: line.hs_code || "",
				boxes: boxes,
				box_weight_kg: bw,
				qty: qty,
				uom: "Kg",
				rate: line.agreed_rate,
				docs_price: line.docs_price,
				_qtyManual: true,
			});
			addedCount++;
		}
	}

	if (!form.value.custom_proforma_invoice && multiPiProformas.value.length > 0) {
		form.value.custom_proforma_invoice = multiPiProformas.value[0].name;
	}

	multiPiModalOpen.value = false;
	toast.success(t("Added {count} item lines from selected PIs.", { count: addedCount }));
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
				custom_proforma_invoice: it.custom_proforma_invoice || d.custom_proforma_invoice || "",
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
			customs_declarations: d.customs_declarations || [],
		};
		loadLineCategories();
		await refreshPiTracking();
		await fetchTransportCosts();
	} catch (err) {
		error.value = err?.message || t("Failed to load the commercial invoice.");
	} finally {
		loading.value = false;
	}
}

function searchProformas(q) {
	return call("stabler.api.imports.list_proformas", {
		company: activeCompany.value,
		search: q || "",
		supplier: form.value.supplier || undefined,
		limit: 20,
	});
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
	try {
		piGroups.value = await call("stabler.api.imports.list_pi_groups", {
			company: activeCompany.value,
		});
	} catch (_) {
		piGroups.value = [];
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
			custom_proforma_invoice: r.custom_proforma_invoice || form.value.custom_proforma_invoice || undefined,
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
				<span class="text-secondary small fw-semibold">{{ t("Status Pipeline") }}:</span>
				<StatusBadge doctype="Commercial Invoice" :status="form.status" />
				<div class="ms-auto d-flex gap-2 flex-wrap">
					<button
						v-for="ns in form.allowed_transitions.filter((s) => s !== 'Cancelled')"
						:key="ns"
						type="button"
						class="btn btn-outline-primary btn-sm"
						@click="advanceStatus(ns)"
					>
						<i class="ti ti-arrow-right me-1"></i>{{ t(ns) }}
					</button>
					<button
						v-if="form.allowed_transitions.includes('Cancelled')"
						type="button"
						class="btn btn-outline-danger btn-sm"
						@click="advanceStatus('Cancelled')"
					>
						{{ t("Cancel") }}
					</button>
					<button
						v-if="canRollback && rollbackTarget"
						type="button"
						class="btn btn-ghost-secondary btn-sm"
						@click="advanceStatus(rollbackTarget)"
					>
						<i class="ti ti-arrow-back-up me-1"></i>{{ t("Roll back") }}
					</button>
				</div>
			</div>
		</div>

		<!-- Top Metric Strip -->
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
						<div class="h3 mb-0 font-monospace text-azure fw-bold">
							{{ fm(itemsDocsTotal, form.currency) }}
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Cash Difference") }}</div>
						<div class="h3 mb-0 font-monospace text-warning fw-bold">
							{{ fm(itemsCashDiff, form.currency) }}
						</div>
					</div>
				</div>
			</div>
			<div v-if="transportData && transportData.totals && transportData.totals.transport > 0" class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Transport expenses") }}</div>
						<div class="h3 mb-0 font-monospace text-purple fw-bold">{{ fm(transportData.totals.transport, transportData.currency) }}</div>
						<div class="text-secondary mt-1" style="font-size:0.75rem">
							{{ fm(transportData.totals.per_container, transportData.currency) }} / {{ t("container") }} · {{ fm(transportData.totals.per_kg, transportData.currency) }} / kg
						</div>
					</div>
				</div>
			</div>
			<div v-else class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Categories") }}</div>
						<div class="mt-1 d-flex flex-wrap gap-1">
							<span v-for="cat in itemCategories" :key="cat" class="badge bg-blue-lt">{{ cat }}</span>
							<span v-if="!itemCategories.length" class="text-secondary">—</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Header Details -->
		<div class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between">
				<h3 class="card-title m-0">{{ t("Header Details") }}</h3>
				<div class="card-actions">
					<button
						type="button"
						class="btn btn-primary shadow-sm fw-bold px-3"
						:disabled="!form.supplier"
						:title="t('Smart Fill items and quantities from supplier Proforma Invoices')"
						@click="openMultiPiSmartFill"
					>
						<i class="ti ti-wand me-1"></i>{{ t("Smart Fill from PIs") }}
					</button>
				</div>
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
					<div class="col-md-6">
						<label class="form-label d-flex align-items-center gap-1">
							<span>{{ t("Reference Proforma Invoice") }}</span>
							<span v-if="form.custom_proforma_invoice" class="badge bg-success-lt ms-auto font-monospace">{{ form.custom_proforma_invoice }}</span>
						</label>
						<Typeahead
							v-slot="{ item }"
							v-model="form.custom_proforma_invoice"
							:search="searchProformas"
							:display="form.custom_proforma_invoice"
							:placeholder="t('Select Proforma Invoice to copy items…')"
							open-on-focus
							@pick="(pi) => loadProformaIntoCi(pi.name)"
							@clear="() => { form.custom_proforma_invoice = ''; }"
						>
							<div class="fw-semibold small">{{ item.supplier_pi_ref || item.name }}</div>
							<div class="text-secondary" style="font-size:0.75rem">{{ item.supplier_name || item.supplier }} · {{ item.agreed_total ? fm(item.agreed_total, item.currency) : "" }}</div>
						</Typeahead>
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("PI Group") }}</label>
						<Select v-model="form.import_pi_group" :options="groupOptions" />
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

		<!-- Items — colour-banded grid with Vendor Category dropdown -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">
					{{ t("Items") }}
					<!-- Silent when every line agrees with its PI; the badge is the
					     summary of the per-row flags below. -->
					<span
						v-if="nonCompliantCount"
						class="badge ms-2"
						:class="getStatusBadgeClass('PI Compliance', 'warn')"
						:title="t('Lines that disagree with the Proforma Invoice')"
					>
						<i class="ti ti-alert-circle me-1"></i>{{ t("{count} line(s) differ from PI", { count: nonCompliantCount }) }}
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
					<button
						v-if="form.custom_proforma_invoice"
						type="button"
						class="btn btn-outline-info btn-sm"
						:title="t('Reload all items from reference Proforma Invoice')"
						@click="loadProformaIntoCi(form.custom_proforma_invoice)"
					>
						<i class="ti ti-refresh me-1"></i>{{ t("Pull from PI") }}
					</button>
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="openFillModal">
						<i class="ti ti-wand me-1"></i>{{ t("Fill from category") }}
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
							<th style="min-width: 150px">{{ t("Vendor Category") }}</th>
							<th style="min-width: 140px">{{ t("Ref PI") }}</th>
							<th style="min-width: 180px">{{ t("Product Code/Name") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 90px">{{ t("Boxes") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 100px">{{ t("Box Weight") }}</th>
							<th class="text-end bg-orange-lt text-orange" style="width: 110px">{{ t("Quantity (KG)") }}</th>
							<th class="text-end bg-blue-lt text-blue" style="width: 130px">{{ t("Agreed Price") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end bg-green-lt text-green" style="width: 130px">{{ t("Docs Price") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end bg-blue-lt text-blue" style="width: 140px">{{ t("Agreed Total") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end bg-green-lt text-green" style="width: 140px">{{ t("Docs Total") }} ({{ form.currency || 'USD' }})</th>
							<th style="width: 36px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, idx) in form.items" :key="idx">
							<td>
								<!-- Vendor Category Dropdown -->
								<select v-if="categoryOptions.length" v-model="row.category" class="form-select form-select-sm fw-semibold">
									<option value="">— {{ t("N/A") }} —</option>
									<option v-for="cat in categoryOptions" :key="cat" :value="cat">{{ cat }}</option>
								</select>
								<input v-else v-model="row.category" type="text" class="form-control form-control-sm" :placeholder="t('Vendor Category')">
							</td>
							<td>
								<span class="badge bg-blue-lt font-monospace text-truncate d-inline-block" style="max-width: 130px; font-size: 0.75rem" :title="rowPiTitle(row)">
									{{ row.custom_proforma_invoice || form.custom_proforma_invoice || "—" }}
								</span>
								<!-- The row carries no PI of its own; it inherits the invoice header's. -->
								<i v-if="!row.custom_proforma_invoice && form.custom_proforma_invoice" class="ti ti-link ms-1 text-secondary" :title="t('Inherited from the invoice header')"></i>
								<span
									v-if="rowDiffLevel(row)"
									class="badge ms-1"
									:class="getStatusBadgeClass('PI Compliance', rowDiffLevel(row))"
									style="font-size: 0.7rem"
									:title="rowDiffTitle(row)"
								>
									<i class="ti" :class="rowDiffLevel(row) === 'error' ? 'ti-alert-triangle' : 'ti-alert-circle'"></i>
									{{ rowDiffLevel(row) === "error" ? t("Off PI") : rowDiffLevel(row) === "warn" ? t("Differs") : t("Sub-cut") }}
								</span>
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
							<td class="text-end font-monospace fw-semibold text-green bg-green-lt">{{ fm(itemsDocsTotal, form.currency) }}</td>
							<td></td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>

		<!-- Linked Containers -->
		<div v-if="form.containers && form.containers.length" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title"><i class="ti ti-box me-2"></i>{{ t("Linked Containers") }}</h3>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter table-hover mb-0">
					<thead>
						<tr>
							<th>{{ t("Container Number") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Boxes") }}</th>
							<th class="text-end">{{ t("Total Weight (kg)") }}</th>
							<th class="text-end">{{ t("Transport by container") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="cnt in form.containers" :key="cnt.name" style="cursor: pointer" @click="router.push('/imports/containers/' + cnt.name)">
							<td class="font-monospace fw-bold text-primary">{{ cnt.container_number || cnt.name }}</td>
							<td><span class="badge bg-secondary-lt">{{ cnt.status }}</span></td>
							<td class="text-end font-monospace">{{ fn(cnt.total_boxes) }}</td>
							<td class="text-end font-monospace fw-semibold">{{ fn(cnt.total_kg) }} kg</td>
							<td class="text-end font-monospace text-azure fw-semibold">
								{{ containerTransportMap[cnt.name] ? fm(containerTransportMap[cnt.name], form.currency) : "—" }}
							</td>
						</tr>
					</tbody>
					<tfoot v-if="transportData && transportData.totals">
						<tr class="fw-bold">
							<td colspan="4" class="text-end">{{ t("Totals") }}</td>
							<td class="text-end font-monospace text-azure">{{ fm(transportData.totals.transport, transportData.currency) }}</td>
						</tr>
					</tfoot>
				</table>
			</div>
		</div>

		<!-- Transport Expenses Card -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-header d-flex align-items-center justify-content-between">
				<h3 class="card-title m-0">
					<i class="ti ti-truck me-2 text-primary"></i>{{ t("Transport expenses") }}
				</h3>
				<div class="card-actions">
					<button
						type="button"
						class="btn btn-outline-primary btn-sm fw-bold"
						@click="router.push('/imports/expenses')"
					>
						<i class="ti ti-plus me-1"></i>{{ t("Add expense") }}
					</button>
				</div>
			</div>

			<!-- Skeleton Loading -->
			<div v-if="loadingTransport" class="card-body">
				<SkeletonRows :rows="3" />
			</div>

			<!-- Empty State -->
			<div v-else-if="!transportData || !transportData.rows || !transportData.rows.length" class="card-body text-center py-4 text-secondary">
				<i class="ti ti-truck-off fs-1 d-block mb-2 text-muted"></i>
				<div>{{ t("No transport expenses yet.") }}</div>
				<button type="button" class="btn btn-outline-primary btn-sm mt-3" @click="router.push('/imports/expenses')">
					<i class="ti ti-plus me-1"></i>{{ t("Add expense") }}
				</button>
			</div>

			<!-- Filled Card -->
			<div v-else class="card-body">
				<!-- Note line -->
				<div class="text-secondary small mb-3">
					<i class="ti ti-info-circle me-1"></i>{{ t("Transport costs belong to third-party carriers. Expenses linked directly to a container are allocated directly; unassigned costs are distributed by weight.") }}
				</div>

				<!-- 3 Summary Metrics -->
				<div class="row row-cards mb-3">
					<div class="col-sm-4">
						<div class="card card-sm bg-light-subtle">
							<div class="card-body">
								<div class="font-weight-medium text-secondary small">{{ t("Total transport") }}</div>
								<div class="h3 mb-0 font-monospace text-primary fw-bold">
									{{ fm(transportData.totals.transport, transportData.currency) }}
								</div>
							</div>
						</div>
					</div>
					<div class="col-sm-4">
						<div class="card card-sm bg-light-subtle">
							<div class="card-body">
								<div class="font-weight-medium text-secondary small">{{ t("Per container") }}</div>
								<div class="h3 mb-0 font-monospace text-azure fw-bold">
									{{ fm(transportData.totals.per_container, transportData.currency) }}
								</div>
							</div>
						</div>
					</div>
					<div class="col-sm-4">
						<div class="card card-sm bg-light-subtle">
							<div class="card-body">
								<div class="font-weight-medium text-secondary small">{{ t("Per kg") }}</div>
								<div class="h3 mb-0 font-monospace text-purple fw-bold">
									{{ fm(transportData.totals.per_kg, transportData.currency) }}
								</div>
							</div>
						</div>
					</div>
				</div>

				<!-- Payment Progress Bar -->
				<div class="mb-4">
					<div class="d-flex justify-content-between align-items-center small text-secondary mb-1">
						<span>{{ t("Payment progress") }}</span>
						<span v-if="transportData.totals.paid === null" class="font-monospace fw-bold">•••</span>
						<span v-else class="font-monospace">
							{{ t("paid {pct}% · {outstanding} to pay", {
								pct: transportData.totals.transport > 0 ? Math.min(100, Math.round(((transportData.totals.paid || 0) / transportData.totals.transport) * 100)) : 0,
								outstanding: fm(transportData.totals.outstanding, transportData.currency)
							}) }}
						</span>
					</div>
					<div class="progress progress-sm">
						<div
							class="progress-bar bg-success"
							:style="{
								width: (transportData.totals.paid !== null && transportData.totals.transport > 0)
									? Math.min(100, Math.round(((transportData.totals.paid || 0) / transportData.totals.transport) * 100)) + '%'
									: '0%'
							}"
						></div>
					</div>
				</div>

				<!-- Mini Table: By Carriers -->
				<div v-if="transportData.by_vendor && transportData.by_vendor.length" class="mb-4">
					<h4 class="card-title mb-2">{{ t("By carriers") }}</h4>
					<div class="table-responsive">
						<table class="table table-sm table-bordered align-middle">
							<thead class="table-light">
								<tr>
									<th>{{ t("Service provider") }}</th>
									<th class="text-center" style="width: 80px">{{ t("Docs") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Agreed Total") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Paid") }}</th>
									<th class="text-end" style="width: 140px">{{ t("Outstanding") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="v in transportData.by_vendor" :key="v.supplier">
									<td class="fw-semibold">{{ v.supplier_name || v.supplier }}</td>
									<td class="text-center font-monospace">{{ v.docs }}</td>
									<td class="text-end font-monospace">{{ fm(v.amount, transportData.currency) }}</td>
									<td class="text-end font-monospace text-success">
										{{ v.paid !== null ? fm(v.paid, transportData.currency) : "•••" }}
									</td>
									<td class="text-end font-monospace" :class="(v.outstanding !== null && v.outstanding > 0) ? 'text-danger fw-bold' : ''">
										{{ v.outstanding !== null ? fm(v.outstanding, transportData.currency) : "•••" }}
									</td>
								</tr>
							</tbody>
							<tfoot>
								<tr class="fw-bold table-light">
									<td>{{ t("Totals") }}</td>
									<td class="text-center font-monospace">{{ transportData.by_vendor.reduce((acc, x) => acc + (x.docs || 0), 0) }}</td>
									<td class="text-end font-monospace">{{ fm(transportData.totals.transport, transportData.currency) }}</td>
									<td class="text-end font-monospace text-success">
										{{ transportData.totals.paid !== null ? fm(transportData.totals.paid, transportData.currency) : "•••" }}
									</td>
									<td class="text-end font-monospace" :class="(transportData.totals.outstanding !== null && transportData.totals.outstanding > 0) ? 'text-danger' : ''">
										{{ transportData.totals.outstanding !== null ? fm(transportData.totals.outstanding, transportData.currency) : "•••" }}
									</td>
								</tr>
							</tfoot>
						</table>
					</div>
				</div>

				<!-- Table: Expense Documents -->
				<div class="mb-3">
					<h4 class="card-title mb-2">{{ t("Expense documents") }}</h4>
					<div class="table-responsive">
						<table class="table table-sm table-hover align-middle">
							<thead>
								<tr>
									<th>{{ t("Vendor Category") }}</th>
									<th>{{ t("Carrier / carrier invoice") }}</th>
									<th>{{ t("System document") }}</th>
									<th>{{ t("Container") }}</th>
									<th class="text-end">{{ t("Agreed Total") }}</th>
									<th class="text-end">{{ t("Paid") }}</th>
									<th>{{ t("Status") }}</th>
									<th style="width: 40px"></th>
								</tr>
							</thead>
							<tbody>
								<tr
									v-for="exp in transportData.rows.filter(r => r.is_transport)"
									:key="exp.name"
									style="cursor: pointer"
									@click="router.push('/imports/expenses')"
								>
									<td><span class="badge bg-blue-lt">{{ exp.category }}</span></td>
									<td>
										<div class="fw-semibold text-dark">{{ exp.supplier_name || exp.supplier }}</div>
										<div class="small text-secondary font-monospace">
											{{ exp.invoice_reference || "—" }} <span v-if="exp.expense_date">· {{ formatDate(exp.expense_date) }}</span>
										</div>
									</td>
									<td>
										<router-link
											v-if="exp.purchase_invoice"
											:to="'/purchasing/invoices/' + exp.purchase_invoice"
											class="font-monospace fw-bold text-primary"
											@click.stop
										>
											{{ exp.purchase_invoice }}
										</router-link>
										<span v-else class="badge bg-warning-lt">{{ t("Not posted") }}</span>
										<div class="small text-secondary font-monospace">{{ exp.name }}</div>
									</td>
									<td>
										<span v-if="exp.allocation === 'direct'">
											<router-link :to="'/imports/containers/' + exp.container" class="font-monospace text-primary fw-bold" @click.stop>{{ exp.container }}</router-link>
											<span class="badge bg-blue-lt ms-1">{{ t("direct link") }}</span>
										</span>
										<span v-else-if="exp.allocation === 'weight'">
											<span class="font-monospace">{{ transportData.totals.containers }} {{ t("cont.") }}</span>
											<span class="badge bg-secondary-lt ms-1">{{ t("by weight") }}</span>
										</span>
										<span v-else-if="exp.allocation === 'equal'">
											<span class="font-monospace">{{ transportData.totals.containers }} {{ t("cont.") }}</span>
											<span class="badge bg-secondary-lt ms-1">{{ t("equal") }}</span>
										</span>
										<span v-else-if="exp.allocation === 'truck'">
											<router-link :to="'/imports/trucks/' + exp.truck" class="font-monospace text-primary fw-bold" @click.stop>{{ exp.truck }}</router-link>
										</span>
										<span v-else>
											— <span class="badge bg-secondary-lt ms-1">{{ t("for whole invoice") }}</span>
										</span>
									</td>
									<td class="text-end font-monospace fw-bold text-primary">{{ fm(exp.amount, transportData.currency) }}</td>
									<td class="text-end font-monospace text-success">
										{{ (exp.bank_payment !== null && exp.cash_payment !== null) ? fm((exp.bank_payment || 0) + (exp.cash_payment || 0), transportData.currency) : "•••" }}
									</td>
									<td><StatusBadge :status="exp.status" /></td>
									<td class="text-end">
										<i class="ti ti-chevron-right text-secondary"></i>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
				</div>

				<!-- Footer Action Strip -->
				<div class="d-flex flex-wrap align-items-center justify-content-between gap-2 border-top pt-3 mt-3">
					<div class="d-flex gap-2">
						<button type="button" class="btn btn-outline-primary btn-sm" @click="router.push('/imports/expenses')">
							<i class="ti ti-plus me-1"></i>{{ t("Add expense") }}
						</button>
						<button type="button" class="btn btn-ghost-secondary btn-sm" @click="router.push('/imports/expenses?commercial_invoice=' + form.name)">
							{{ t("Open all expenses for this invoice →") }}
						</button>
					</div>
					<div class="font-monospace small fw-bold text-secondary bg-light px-3 py-1 rounded">
						{{ t("Landed cost with transport: {landed_per_kg} {currency}/kg ({goods_per_kg} + {per_kg})", {
							landed_per_kg: fn(transportData.totals.landed_per_kg),
							currency: transportData.currency || 'USD',
							goods_per_kg: fn(transportData.totals.goods_per_kg),
							per_kg: fn(transportData.totals.per_kg)
						}) }}
					</div>
				</div>

				<!-- Other Expenses Sub-table (Customs, Documentation, etc.) -->
				<div v-if="transportData.other_rows && transportData.other_rows.length" class="mt-4 border-top pt-3">
					<h4 class="card-title text-secondary mb-2"><i class="ti ti-receipt me-1"></i>{{ t("Other expenses") }}</h4>
					<div class="table-responsive">
						<table class="table table-sm text-secondary">
							<thead>
								<tr>
									<th>{{ t("Vendor Category") }}</th>
									<th>{{ t("Carrier / carrier invoice") }}</th>
									<th>{{ t("System document") }}</th>
									<th class="text-end">{{ t("Agreed Total") }}</th>
									<th>{{ t("Status") }}</th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="exp in transportData.other_rows" :key="exp.name">
									<td><span class="badge bg-secondary-lt">{{ exp.category }}</span></td>
									<td>{{ exp.supplier_name || exp.supplier }} <span v-if="exp.invoice_reference">({{ exp.invoice_reference }})</span></td>
									<td>{{ exp.purchase_invoice || exp.name }}</td>
									<td class="text-end font-monospace fw-semibold">{{ fm(exp.amount, transportData.currency) }}</td>
									<td><StatusBadge :status="exp.status" /></td>
								</tr>
							</tbody>
							<tfoot>
								<tr class="fw-bold">
									<td colspan="3" class="text-end">{{ t("Totals") }}</td>
									<td class="text-end font-monospace">{{ fm(transportData.other_total, transportData.currency) }}</td>
									<td></td>
								</tr>
							</tfoot>
						</table>
					</div>
				</div>
			</div>
		</div>

		<!-- Linked Trucks -->
		<div v-if="form.trucks && form.trucks.length" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title"><i class="ti ti-truck me-2"></i>{{ t("Linked Trucks / Land Transport") }}</h3>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("Truck / Plate") }}</th>
							<th>{{ t("Carrier & Driver") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Boxes") }}</th>
							<th class="text-end">{{ t("Total Weight (kg)") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="trk in form.trucks" :key="trk.name" style="cursor: pointer" @click="router.push('/imports/trucks/' + trk.name)">
							<td class="font-monospace fw-bold text-primary"><i class="ti ti-truck me-1"></i>{{ trk.truck_number || trk.name }}</td>
							<td>
								<div class="fw-semibold text-dark">{{ trk.trucking_company || "—" }}</div>
								<div v-if="trk.driver_name" class="small text-secondary">{{ trk.driver_name }} <span v-if="trk.driver_phone">({{ trk.driver_phone }})</span></div>
							</td>
							<td><span class="badge bg-secondary-lt">{{ trk.status }}</span></td>
							<td class="text-end font-monospace">{{ fn(trk.total_boxes) }}</td>
							<td class="text-end font-monospace fw-semibold">{{ fn(trk.total_kg) }} kg</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Logistics Readiness overview sits at the bottom -->
		<CiLogisticsOverview
			v-if="!isCreate && form.name"
			:commercial-invoice="form.name"
			:packing-summary="form.packing_summary"
			:grn="form.grn"
			:loading="loading"
			@reload="loadDoc"
		/>

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

		<!-- Smart Fill from PIs — allocate boxes across every open proforma of this supplier -->
		<div v-if="multiPiModalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
			<div class="modal-dialog modal-xl modal-dialog-centered modal-dialog-scrollable">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title"><i class="ti ti-wand me-2"></i>{{ t("Smart Fill from PIs") }}</h5>
						<button type="button" class="btn-close" @click="multiPiModalOpen = false"></button>
					</div>
					<div class="modal-body">
						<table class="table table-sm table-vcenter align-middle mb-0">
							<thead>
								<tr>
									<th style="min-width: 130px">{{ t("Ref PI") }}</th>
									<th style="min-width: 180px">{{ t("PI product") }}</th>
									<th style="min-width: 150px">{{ t("Product Code/Name") }}</th>
									<th class="text-end" style="width: 100px">{{ t("Contract") }}</th>
									<th class="text-end" style="width: 100px">{{ t("Shipped") }}</th>
									<th class="text-end" style="width: 110px">{{ t("Remaining") }}</th>
									<th class="text-end" style="width: 130px">{{ t("Allocate boxes") }}</th>
								</tr>
							</thead>
							<SkeletonRows v-if="multiPiLoading" :rows="6" :cols="7" />
							<tbody v-else>
								<tr v-if="!multiPiLines.length">
									<td colspan="7" class="text-secondary text-center py-3">{{ t("No open proforma lines for this supplier.") }}</td>
								</tr>
								<template v-for="line in multiPiLines" :key="multiPiKey(line)">
									<tr>
										<td>
											<span class="badge bg-blue-lt font-monospace" style="font-size: 0.75rem">{{ line.pi_ref || line.pi_name }}</span>
										</td>
										<td>
											<div class="fw-semibold">{{ line.category || "—" }}</div>
											<div v-if="line.description" class="small text-secondary">{{ line.description }}</div>
										</td>
										<td>
											<select v-model="multiPiItems[multiPiKey(line)]" class="form-select form-select-sm">
												<option v-for="code in multiPiItemOptions(line)" :key="code" :value="code">{{ code }}</option>
											</select>
										</td>
										<td class="text-end font-monospace">{{ fn(line.contract_boxes) }}</td>
										<td class="text-end font-monospace">
											{{ fn(line.shipped_boxes) }}
											<span v-if="line.ci_count" class="text-secondary small">/ {{ line.ci_count }} CI</span>
										</td>
										<td class="text-end font-monospace">
											<span v-if="line.over_shipped" class="badge bg-red-lt" :title="t('Shipped more than the contract allows')">
												−{{ fn(line.over_boxes) }} · {{ t("Over-shipped") }}
											</span>
											<span v-else class="fw-semibold">{{ fn(line.remaining_boxes) }}</span>
										</td>
										<td class="text-end">
											<input
												v-model.number="multiPiAllocations[multiPiKey(line)]"
												type="number"
												min="0"
												step="1"
												inputmode="decimal"
												class="form-control form-control-sm text-end font-monospace"
											>
										</td>
									</tr>
									<tr v-if="line.sub_cuts && line.sub_cuts.length">
										<td colspan="7" class="py-1 bg-light">
											<span class="small text-secondary me-2">{{ t("Already shipped as") }}:</span>
											<span v-for="sc in line.sub_cuts" :key="sc.item" class="badge bg-secondary-lt me-1 font-monospace" style="font-size: 0.7rem">
												{{ sc.item || "—" }} · {{ fn(sc.boxes) }}
											</span>
										</td>
									</tr>
								</template>
							</tbody>
						</table>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-outline-secondary" @click="multiPiModalOpen = false">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-primary" :disabled="multiPiLoading || !multiPiLines.length" @click="applyMultiPiAllocation">
							{{ t("Apply") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
