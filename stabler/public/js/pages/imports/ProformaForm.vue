<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { itemSearcher } from "../../composables/items.js";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
useEscapeBack(null, "/imports/proformas");

// Route contract: "/imports/proformas/new" matches the static child route
// (no :name param) so docName is null there; "/imports/proformas/:name"
// carries the real PI name. Branch on the route param, never on doc state —
// a direct load/refresh must populate, not render a blank "New" form.
const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const form = ref(blankForm());

const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];

// ---- PI Groups (for the Details section select) ----
const piGroups = ref([]);
const groupOptions = computed(() => [
	{ value: "", label: t("No PI group") },
	...piGroups.value.map((g) => ({ value: g.name, label: g.title || g.name })),
]);

async function loadPiGroups() {
	if (!activeCompany.value) return;
	try {
		piGroups.value = await call("stabler.api.imports.list_pi_groups", {
			company: activeCompany.value,
		});
	} catch (_err) {
		piGroups.value = [];
	}
}

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
		currency: "",
		incoterm: "CIF",
		incoterm_location: "",
		port_of_loading: "",
		port_of_discharge: "",
		prepayment_type: "AGREED_TOTAL",
		agreed_total: 0,
		advance_pct: 30,
		bank_agreed: 0,
		cash_agreed: 0,
		docs_total: null,
		cash_difference: null,
		status: "DRAFT",
		remarks: "",
		items: [],
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
const fm = (v, ccy) => formatMoney(v, ccy || "", user.value.language);
const searchItems = itemSearcher("purchase", { limit: 30 });

// bank/cash "not yet hand-edited by the user" flags — while true, the split
// auto-follows the items grid (bank = docs_total, cash = cash_difference).
const bankTouched = ref(false);
const cashTouched = ref(false);

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 20,
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
// proforma_detail returns the raw doctype dict — Proforma Invoice has no
// supplier_name field, so resolve it via the same supplier search endpoint
// the Typeahead already uses (no backend change needed).
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
		};
		// Existing saved splits are user intent — don't let the auto-follow
		// watcher below silently overwrite them.
		bankTouched.value = true;
		cashTouched.value = true;
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
function pickItemRow(row, item) {
	row.item = item.item_code || item.name;
	if (!row.description) row.description = item.item_name || "";
	if (!row.uom) row.uom = item.stock_uom || "";
}
function clearItemRow(row) {
	row.item = "";
}
// Qty auto-follows boxes × box weight until the user types into Qty directly
// (mirrors the server's own qty-default rule in proforma_invoice.py).
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

const hasItems = computed(() => (form.value.items || []).some((r) => r.item));
const itemsAgreedTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowAmount(r), 0));
const itemsDocsTotal = computed(() => (form.value.items || []).reduce((s, r) => s + rowDocsAmount(r), 0));
const itemsCashDiff = computed(() => itemsAgreedTotal.value - itemsDocsTotal.value);
const itemCategories = computed(() => [
	...new Set((form.value.items || []).map((r) => r.category).filter(Boolean)),
]);

// Live-sync agreed/bank/cash from the items grid whenever items are present.
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

// Live earmark check mirrors the controller (bank + cash == agreed_total).
const earmarkOk = computed(() => {
	const f = form.value;
	const a = Number(f.agreed_total) || 0;
	const b = Number(f.bank_agreed) || 0;
	const c = Number(f.cash_agreed) || 0;
	if (a === 0 && b === 0 && c === 0) return true;
	return Math.abs(b + c - a) <= 0.5;
});

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

// Vendor categories for the per-line category dropdown (vendor-scoped).
const lineCategories = ref([]);
const categoryOptions = computed(() =>
	lineCategories.value.map((c) => c.display_name || c.category_name).filter(Boolean),
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
		// The category's own display name tags every row it generates so the
		// items grid + Categories metric can group by it later.
		const categoryLabel = detail.display_name || detail.category_name || "";
		for (const it of items) {
			const perContainer = Number(it.boxes_per_container) || 0;
			const boxes = perContainer * containers;
			const fcl = totalBoxes ? round2((perContainer / totalBoxes) * containers) : 0;
			form.value.items.push({
				item: it.item_code,
				category: categoryLabel,
				description: it.item_name || "",
				fcl,
				boxes,
				box_weight_kg: boxWeight,
				qty: round2(boxes * boxWeight),
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

// Border tint for the page header — derived from the already-centralized
// getStatusBadgeClass() output ("bg-blue-lt" -> "blue"), not a new status map.
const statusColor = computed(() => {
	const cls = getStatusBadgeClass("Proforma Invoice", form.value.status);
	const m = /^bg-([a-z]+)-lt$/.exec(cls);
	return m ? m[1] : "secondary";
});

onMounted(() => {
	loadPiGroups();
	loadDoc();
});
watch(docName, loadDoc);
watch(activeCompany, loadPiGroups);
</script>

<template>
	<div>
		<!-- Page header: status-coloured left border -->
		<div class="card mb-3" :style="{ borderLeft: `4px solid var(--tblr-${statusColor})` }">
			<div class="card-body d-flex align-items-center flex-wrap gap-3">
				<button type="button" class="btn btn-outline-secondary btn-icon" @click="router.push('/imports/proformas')">
					<i class="ti ti-arrow-left"></i>
				</button>
				<div class="flex-grow-1">
					<div class="d-flex align-items-center gap-2 flex-wrap">
						<h2 class="page-title mb-0">{{ isCreate ? t("New Proforma") : form.name }}</h2>
						<span v-if="!isCreate" class="badge" :class="getStatusBadgeClass('Proforma Invoice', form.status)">{{ form.status }}</span>
						<span v-if="form.commercial_invoice" class="badge bg-green-lt font-monospace" :title="t('Commercial Invoice')">{{ form.commercial_invoice }}</span>
					</div>
					<div class="text-secondary small mt-1">
						{{ form.supplier_name || form.supplier || t("No supplier selected") }}
						<template v-if="form.incoterm"> · {{ form.incoterm }}</template>
						<template v-if="form.pi_date"> · {{ formatDate(form.pi_date) }}</template>
						· {{ form.advance_pct }}% / {{ 100 - form.advance_pct }}%
					</div>
				</div>
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
						<div class="h3 mb-0 font-monospace">{{ fm(itemsAgreedTotal, form.currency) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Docs total") }}</div>
						<div class="h3 mb-0 font-monospace">{{ fm(itemsDocsTotal, form.currency) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Cash Difference") }}</div>
						<div class="h3 mb-0 font-monospace" :class="{ 'text-warning': Math.abs(itemsCashDiff) > 0.5 }">{{ fm(itemsCashDiff, form.currency) }}</div>
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
					<div class="col-md-3">
						<label class="form-label">{{ t("PI Group") }}</label>
						<Select v-model="form.import_pi_group" :options="groupOptions" />
					</div>
					<div class="col-md-2">
						<label class="form-label">{{ t("PI Date") }}</label>
						<DateInput v-model="form.pi_date" />
					</div>
					<div class="col-md-3">
						<label class="form-label required">{{ t("Supplier PI No.") }}</label>
						<input v-model="form.supplier_pi_ref" type="text" class="form-control" :readonly="!isCreate" :placeholder="t('e.g. FIR/25-26/29639-29647')" :title="!isCreate ? t('The PI number is the document identity and cannot be changed after creation.') : ''">
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
					<div class="col-md-6">
						<label class="form-label">{{ t("Advance %") }}</label>
						<input v-model.number="form.advance_pct" type="range" min="0" max="100" class="form-range">
						<div class="small text-secondary">{{ form.advance_pct }}% / {{ 100 - form.advance_pct }}%</div>
					</div>
				</div>

				<div class="row g-3 mt-1">
					<div class="col-md-4">
						<label class="form-label">{{ t("Agreed total") }}</label>
						<MoneyInput v-model="form.agreed_total" :currency="form.currency" :language="user.language" :disabled="hasItems" />
						<div v-if="hasItems" class="form-text small">{{ t("Computed from the items grid.") }}</div>
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Bank Agreed") }}</label>
						<MoneyInput v-model="form.bank_agreed" :currency="form.currency" :language="user.language" @focus="onBankInput" />
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Cash Agreed") }}</label>
						<MoneyInput v-model="form.cash_agreed" :currency="form.currency" :language="user.language" @focus="onCashInput" />
					</div>
					<div class="col-12">
						<div v-if="!earmarkOk" class="alert alert-warning py-1 px-2 mb-0 small">
							{{ t("Bank Agreed + Cash Agreed must equal Agreed Total.") }}
						</div>
					</div>
					<div class="col-12">
						<label class="form-label">{{ t("Remarks") }}</label>
						<textarea v-model="form.remarks" rows="2" class="form-control"></textarea>
					</div>
				</div>
			</div>
		</div>

		<!-- Items — colour-banded grid: Physical (orange) · Agreed (blue) · Docs (green) -->
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
								<th style="min-width: 150px">{{ t("Category") }}</th>
								<th style="min-width: 200px">{{ t("Product Code/Name") }}</th>
								<th class="text-end bg-orange-lt text-orange" style="width: 90px">{{ t("Boxes") }}</th>
								<th class="text-end bg-orange-lt text-orange" style="width: 100px">{{ t("Box Weight") }}</th>
								<th class="text-end bg-orange-lt text-orange" style="width: 110px">{{ t("Quantity (KG)") }}</th>
								<th class="text-end bg-blue-lt text-blue" style="width: 120px">{{ t("Agreed Price") }}</th>
								<th class="text-end bg-green-lt text-green" style="width: 120px">{{ t("Docs Price") }}</th>
								<th class="text-end bg-blue-lt text-blue" style="width: 130px">{{ t("Agreed Total") }}</th>
								<th class="text-end bg-green-lt text-green" style="width: 130px">{{ t("Docs Total") }}</th>
								<th style="width: 36px"></th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(row, idx) in form.items" :key="idx">
								<td><input v-model="row.category" type="text" class="form-control form-control-sm" :placeholder="t('Category')"></td>
								<td>
									<Typeahead
										v-model="row.item"
										:display="row.item ? `${row.item}${row.description ? ' — ' + row.description : ''}` : ''"
										:search="searchItems"
										size="sm"
										:placeholder="t('Search item…')"
										@pick="(item) => pickItemRow(row, item)"
										@clear="() => clearItemRow(row)"
									>
										<template #option="{ item }">
											<div class="d-flex justify-content-between align-items-center">
												<div>
													<div class="fw-semibold small">{{ item.item_name }}</div>
													<div class="font-monospace text-secondary" style="font-size: 11px">{{ item.item_code }}</div>
												</div>
												<span class="badge bg-secondary-lt">{{ item.stock_uom }}</span>
											</div>
										</template>
									</Typeahead>
								</td>
								<td><input v-model.number="row.boxes" type="number" step="1" class="form-control form-control-sm text-end font-monospace" @input="onBoxesOrWeightInput(row)"></td>
								<td><input v-model.number="row.box_weight_kg" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace" @input="onBoxesOrWeightInput(row)"></td>
								<td><input v-model.number="row.qty" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace text-warning" @input="onQtyInput(row)"></td>
								<td><MoneyInput v-model="row.rate" :currency="form.currency" :language="user.language" size="sm" /></td>
								<td><MoneyInput v-model="row.docs_price" :currency="form.currency" :language="user.language" size="sm" /></td>
								<td class="text-end font-monospace text-blue bg-blue-lt">{{ fm(rowAmount(row), form.currency) }}</td>
								<td class="text-end font-monospace text-green bg-green-lt">{{ fm(rowDocsAmount(row), form.currency) }}</td>
								<td>
									<button type="button" class="btn btn-icon btn-sm btn-ghost-secondary" :title="t('Remove')" @click="removeItemRow(idx)">
										<i class="ti ti-trash"></i>
									</button>
								</td>
							</tr>
							<tr v-if="!form.items.length">
								<td colspan="10" class="text-secondary text-center py-3">{{ t("No items yet.") }}</td>
							</tr>
						</tbody>
						<tfoot v-if="form.items.length">
							<tr>
								<td colspan="7" class="text-end fw-semibold small">{{ t("Totals") }}</td>
								<td class="text-end font-monospace fw-semibold text-blue bg-blue-lt">{{ fm(itemsAgreedTotal, form.currency) }}</td>
								<td class="text-end font-monospace fw-semibold text-green bg-green-lt">{{ fm(itemsDocsTotal, form.currency) }}</td>
								<td></td>
							</tr>
						</tfoot>
				</table>
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
	</div>
</template>
