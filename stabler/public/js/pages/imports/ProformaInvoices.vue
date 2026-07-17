<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import { itemSearcher } from "../../composables/items.js";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const toast = useToast();

const rows = ref([]);
const loading = ref(false);
const search = ref("");
const statusFilter = ref("");

const STATUSES = [
	{ value: "", label: t("All statuses") },
	{ value: "DRAFT", label: "DRAFT" },
	{ value: "CONFIRMED", label: "CONFIRMED" },
	{ value: "SUPERSEDED_BY_CI", label: "SUPERSEDED_BY_CI" },
	{ value: "CANCELLED", label: "CANCELLED" },
];

const INCOTERMS = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		rows.value = await call("stabler.api.imports.list_proformas", {
			company: activeCompany.value,
			status: statusFilter.value || undefined,
			search: search.value || undefined,
			limit: 200,
		});
	} catch (err) {
		toast.error(err?.message || t("Failed to load proformas."));
		rows.value = [];
	} finally {
		loading.value = false;
	}
}
onMounted(load);

const fm = (v, ccy) => formatMoney(v, ccy || "", user.value.language);
const round2 = (n) => Math.round((Number(n) || 0) * 100) / 100;

// ---- Create / edit modal ----
const modalOpen = ref(false);
const saving = ref(false);
const form = ref(null);
const activeTab = ref("details");
const searchItems = itemSearcher("purchase", { limit: 30 });

function blankItemRow() {
	return {
		item: "",
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

function blankForm() {
	return {
		name: "",
		supplier: "",
		supplier_name: "",
		pi_date: todayIso(),
		supplier_pi_ref: "",
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
		status: "DRAFT",
		remarks: "",
		items: [],
	};
}

// bank/cash "not yet hand-edited by the user" flags — while true, the split
// auto-follows the items grid (bank = docs_total, cash = cash_difference).
const bankTouched = ref(false);
const cashTouched = ref(false);

function openNew() {
	form.value = blankForm();
	activeTab.value = "details";
	bankTouched.value = false;
	cashTouched.value = false;
	modalOpen.value = true;
}

async function openEdit(row) {
	try {
		const detail = await call("stabler.api.imports.proforma_detail", { name: row.name });
		form.value = {
			...blankForm(),
			...detail,
			supplier_name: row.supplier_name || detail.supplier,
			items: (detail.items || []).map((it) => ({
				item: it.item,
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
		activeTab.value = "details";
		modalOpen.value = true;
	} catch (err) {
		toast.error(err?.message || t("Failed to load the proforma."));
	}
}
function closeModal() {
	if (!saving.value) modalOpen.value = false;
}

function searchSuppliers(q) {
	return call("stabler.api.purchasing.list_suppliers", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
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

const hasItems = computed(() => (form.value?.items || []).some((r) => r.item));
const itemsAgreedTotal = computed(() =>
	(form.value?.items || []).reduce((s, r) => s + rowAmount(r), 0)
);
const itemsDocsTotal = computed(() =>
	(form.value?.items || []).reduce((s, r) => s + rowDocsAmount(r), 0)
);
const itemsCashDiff = computed(() => itemsAgreedTotal.value - itemsDocsTotal.value);

// Live-sync agreed/bank/cash from the items grid whenever items are present.
watch([itemsAgreedTotal, itemsDocsTotal, itemsCashDiff, hasItems], () => {
	if (!form.value || !hasItems.value) return;
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
	if (!form.value?.supplier) {
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
		for (const it of items) {
			const perContainer = Number(it.boxes_per_container) || 0;
			const boxes = perContainer * containers;
			const fcl = totalBoxes ? round2((perContainer / totalBoxes) * containers) : 0;
			form.value.items.push({
				item: it.item_code,
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

// Live earmark check mirrors the controller (bank + cash == agreed_total).
const earmarkOk = computed(() => {
	const f = form.value;
	if (!f) return true;
	const a = Number(f.agreed_total) || 0;
	const b = Number(f.bank_agreed) || 0;
	const c = Number(f.cash_agreed) || 0;
	if (a === 0 && b === 0 && c === 0) return true;
	return Math.abs(b + c - a) <= 0.5;
});

async function saveProforma() {
	if (!form.value.supplier) {
		toast.error(t("Supplier is required."));
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
		await call("stabler.api.imports.save_proforma", { payload });
		toast.success(t("Proforma saved"));
		modalOpen.value = false;
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not save the proforma."));
	} finally {
		saving.value = false;
	}
}

// ---- Supersede with a Commercial Invoice ----
const supersedeFor = ref(null); // row being superseded
const supersedeCi = ref("");
const superseding = ref(false);

function openSupersede(row) {
	supersedeFor.value = row;
	supersedeCi.value = "";
}
function searchCIs(q) {
	return call("stabler.api.imports.list_commercial_invoices", {
		company: activeCompany.value,
		search: q,
		limit: 20,
	});
}
async function doSupersede() {
	if (!supersedeCi.value) return;
	superseding.value = true;
	try {
		await call("stabler.api.imports.link_proforma_to_ci", {
			proforma: supersedeFor.value.name,
			commercial_invoice: supersedeCi.value,
			company: activeCompany.value,
		});
		toast.success(t("Proforma linked to Commercial Invoice"));
		supersedeFor.value = null;
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not link the proforma."));
	} finally {
		superseding.value = false;
	}
}

const canSupersede = (row) => ["DRAFT", "CONFIRMED"].includes(row.status);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Proforma Invoices") }}</div>
			<button type="button" class="btn btn-primary btn-sm ms-auto" @click="openNew">
				<i class="ti ti-plus me-1"></i>{{ t("New Proforma") }}
			</button>
		</div>

		<ListToolbar v-model="search" :placeholder="t('PI no or supplier') + '  ⌘K'" :count="rows.length" @search="load">
			<template #filters>
				<Select v-model="statusFilter" size="sm" style="width: 180px" :options="STATUSES" value-key="value" label-key="label" @change="load" />
			</template>
		</ListToolbar>

		<div class="table-responsive">
			<table class="table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("PI") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th class="text-nowrap">{{ t("PI Date") }}</th>
						<th class="text-end">{{ t("Agreed total") }}</th>
						<th class="text-end">{{ t("Bank Agreed") }}</th>
						<th class="text-end">{{ t("Cash Agreed") }}</th>
						<th class="text-end">{{ t("Docs total") }}</th>
						<th class="text-end">{{ t("Cash Difference") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Commercial Invoice") }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="11" :rows="6" />
					<tr v-for="r in rows" :key="r.name" style="cursor: pointer" @click="openEdit(r)">
						<td class="font-monospace text-primary">{{ r.name }}</td>
						<td>{{ r.supplier_name || r.supplier }}</td>
						<td class="text-nowrap">{{ r.pi_date ? formatDate(r.pi_date) : "—" }}</td>
						<td class="text-end font-monospace">{{ fm(r.agreed_total, r.currency) }}</td>
						<td class="text-end font-monospace">{{ fm(r.bank_agreed, r.currency) }}</td>
						<td class="text-end font-monospace">{{ fm(r.cash_agreed, r.currency) }}</td>
						<td class="text-end font-monospace">{{ fm(r.docs_total, r.currency) }}</td>
						<td class="text-end font-monospace">{{ fm(r.cash_difference, r.currency) }}</td>
						<td><span class="badge" :class="getStatusBadgeClass('Proforma Invoice', r.status)">{{ r.status }}</span></td>
						<td class="font-monospace text-secondary small">{{ r.commercial_invoice || "—" }}</td>
						<td class="text-end" @click.stop>
							<button v-if="canSupersede(r)" type="button" class="btn btn-outline-secondary btn-sm" @click="openSupersede(r)">
								<i class="ti ti-link me-1"></i>{{ t("Link CI") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !rows.length" :title="t('No proformas yet')" :subtitle="t('Create your first proforma invoice.')" />
		</div>
	</div>

	<!-- Create / edit modal -->
	<div v-if="modalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-xl modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ form.name ? t("Edit Proforma") : t("New Proforma") }}</h5>
					<button type="button" class="btn-close" @click="closeModal"></button>
				</div>

				<ul class="nav nav-tabs px-3 pt-2">
					<li class="nav-item">
						<a href="#" class="nav-link" :class="{ active: activeTab === 'details' }" @click.prevent="activeTab = 'details'">
							{{ t("Details") }}
						</a>
					</li>
					<li class="nav-item">
						<a href="#" class="nav-link" :class="{ active: activeTab === 'items' }" @click.prevent="activeTab = 'items'">
							{{ t("Items") }}
							<span class="badge bg-secondary-subtle text-secondary ms-1">{{ form.items.length }}</span>
						</a>
					</li>
				</ul>

				<div class="modal-body">
					<!-- DETAILS TAB -->
					<div v-show="activeTab === 'details'">
						<div class="row g-3">
							<div class="col-md-4">
								<label class="form-label small mb-1">{{ t("Supplier") }} *</label>
								<Typeahead
									v-model="form.supplier"
									:display="form.supplier ? `${form.supplier_name || form.supplier}` : ''"
									:search="searchSuppliers"
									:placeholder="t('Search supplier…')"
									@pick="(s) => { form.supplier = s.name; form.supplier_name = s.supplier_name || s.name; }"
									@clear="() => { form.supplier = ''; form.supplier_name = ''; }"
								/>
							</div>
							<div class="col-md-2"><label class="form-label small mb-1">{{ t("PI Date") }}</label><DateInput v-model="form.pi_date" size="sm" /></div>
							<div class="col-md-3"><label class="form-label small mb-1">{{ t("Supplier PI No.") }}</label><input v-model="form.supplier_pi_ref" type="text" class="form-control form-control-sm"></div>
							<div class="col-md-3"><label class="form-label small mb-1">{{ t("Currency") }}</label><input v-model="form.currency" type="text" maxlength="3" class="form-control form-control-sm text-uppercase"></div>

							<div class="col-md-2"><label class="form-label small mb-1">{{ t("Incoterm") }}</label>
								<select v-model="form.incoterm" class="form-select form-select-sm">
									<option value="">—</option>
									<option v-for="ic in INCOTERMS" :key="ic" :value="ic">{{ ic }}</option>
								</select>
							</div>
							<div class="col-md-3"><label class="form-label small mb-1">{{ t("Incoterm Location") }}</label><input v-model="form.incoterm_location" type="text" class="form-control form-control-sm"></div>
							<div class="col-md-3"><label class="form-label small mb-1">{{ t("Port of Loading") }}</label><input v-model="form.port_of_loading" type="text" class="form-control form-control-sm"></div>
							<div class="col-md-4"><label class="form-label small mb-1">{{ t("Port of Discharge") }}</label><input v-model="form.port_of_discharge" type="text" class="form-control form-control-sm"></div>

							<div class="col-md-3"><label class="form-label small mb-1">{{ t("Status") }}</label>
								<select v-model="form.status" class="form-select form-select-sm">
									<option value="DRAFT">DRAFT</option>
									<option value="CONFIRMED">CONFIRMED</option>
									<option value="CANCELLED">CANCELLED</option>
								</select>
							</div>
						</div>

						<hr>
						<h6 class="text-secondary text-uppercase small mb-2">{{ t("Prepayment") }}</h6>
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label small mb-1 d-block">{{ t("Prepayment Base") }}</label>
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
								<label class="form-label small mb-1">{{ t("Advance %") }}</label>
								<input v-model.number="form.advance_pct" type="range" min="0" max="100" class="form-range">
								<div class="small text-secondary">{{ form.advance_pct }}% / {{ 100 - form.advance_pct }}%</div>
							</div>
						</div>

						<div class="row g-3 mt-1">
							<div class="col-md-4">
								<label class="form-label small mb-1">{{ t("Agreed total") }}</label>
								<MoneyInput v-model="form.agreed_total" :currency="form.currency" :language="user.language" size="sm" :disabled="hasItems" />
								<div v-if="hasItems" class="form-text small">{{ t("Computed from the items grid.") }}</div>
							</div>
							<div class="col-md-4">
								<label class="form-label small mb-1">{{ t("Bank Agreed") }}</label>
								<MoneyInput v-model="form.bank_agreed" :currency="form.currency" :language="user.language" size="sm" @focus="onBankInput" />
							</div>
							<div class="col-md-4">
								<label class="form-label small mb-1">{{ t("Cash Agreed") }}</label>
								<MoneyInput v-model="form.cash_agreed" :currency="form.currency" :language="user.language" size="sm" @focus="onCashInput" />
							</div>
							<div class="col-12">
								<div v-if="!earmarkOk" class="alert alert-warning py-1 px-2 mb-0 small">
									{{ t("Bank Agreed + Cash Agreed must equal Agreed Total.") }}
								</div>
							</div>
							<div class="col-12"><label class="form-label small mb-1">{{ t("Remarks") }}</label><textarea v-model="form.remarks" rows="2" class="form-control form-control-sm"></textarea></div>
						</div>
					</div>

					<!-- ITEMS TAB -->
					<div v-show="activeTab === 'items'">
						<div class="d-flex align-items-center justify-content-between mb-2">
							<label class="form-label small mb-0">{{ t("Items") }}</label>
							<div class="d-flex gap-2">
								<button type="button" class="btn btn-outline-secondary btn-sm" @click="openFillModal">
									<i class="ti ti-wand me-1"></i>{{ t("Fill from category") }}
								</button>
								<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addItemRow">
									<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
								</button>
							</div>
						</div>

						<div class="table-responsive">
							<table class="table table-sm table-bordered align-middle">
								<thead class="table-light">
									<tr>
										<th style="min-width: 200px">{{ t("Item") }}</th>
										<th style="min-width: 150px">{{ t("Description") }}</th>
										<th style="width: 70px">{{ t("FCL") }}</th>
										<th style="width: 80px">{{ t("Boxes") }}</th>
										<th style="width: 90px">{{ t("Box kg") }}</th>
										<th style="width: 90px">{{ t("Qty") }}</th>
										<th style="width: 130px">{{ t("Agreed price") }}</th>
										<th style="width: 130px">{{ t("Docs price") }}</th>
										<th style="width: 110px" class="text-end">{{ t("Amount") }}</th>
										<th style="width: 36px"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(row, idx) in form.items" :key="idx">
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
										<td><input v-model="row.description" type="text" class="form-control form-control-sm"></td>
										<td><input v-model.number="row.fcl" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace"></td>
										<td><input v-model.number="row.boxes" type="number" step="1" class="form-control form-control-sm text-end font-monospace" @input="onBoxesOrWeightInput(row)"></td>
										<td><input v-model.number="row.box_weight_kg" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace" @input="onBoxesOrWeightInput(row)"></td>
										<td><input v-model.number="row.qty" type="number" step="0.01" class="form-control form-control-sm text-end font-monospace" @input="onQtyInput(row)"></td>
										<td><MoneyInput v-model="row.rate" :currency="form.currency" :language="user.language" size="sm" /></td>
										<td><MoneyInput v-model="row.docs_price" :currency="form.currency" :language="user.language" size="sm" /></td>
										<td class="text-end font-monospace">{{ fm(rowAmount(row), form.currency) }}</td>
										<td>
											<button type="button" class="btn btn-icon btn-sm btn-ghost-secondary" :title="t('Remove')" @click="removeItemRow(idx)">
												<i class="ti ti-trash"></i>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
						<EmptyState v-if="!form.items.length" :title="t('No items yet')" :subtitle="t('Add a row or fill from a vendor category.')" />

						<div class="d-flex flex-wrap gap-3 justify-content-end bg-light rounded p-2 mt-2 small">
							<div><span class="text-secondary me-1">{{ t("Agreed total") }}:</span><span class="font-monospace fw-semibold">{{ fm(itemsAgreedTotal, form.currency) }}</span></div>
							<div><span class="text-secondary me-1">{{ t("Docs total") }}:</span><span class="font-monospace fw-semibold">{{ fm(itemsDocsTotal, form.currency) }}</span></div>
							<div><span class="text-secondary me-1">{{ t("Cash Difference") }}:</span><span class="font-monospace fw-semibold">{{ fm(itemsCashDiff, form.currency) }}</span></div>
						</div>
					</div>
				</div>

				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeModal">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving || !earmarkOk" @click="saveProforma">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Fill items from vendor category -->
	<div v-if="fillModalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4); z-index: 1060">
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

	<!-- Supersede modal -->
	<div v-if="supersedeFor" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Link to Commercial Invoice") }}</h5>
					<button type="button" class="btn-close" @click="supersedeFor = null"></button>
				</div>
				<div class="modal-body">
					<p class="text-secondary small">{{ t("Superseding proforma") }} <strong>{{ supersedeFor.name }}</strong>.</p>
					<label class="form-label small mb-1">{{ t("Commercial Invoice") }}</label>
					<Typeahead
						v-model="supersedeCi"
						:search="searchCIs"
						:placeholder="t('Search commercial invoice…')"
						@pick="(ci) => { supersedeCi = ci.name; }"
						@clear="() => { supersedeCi = ''; }"
					>
						<template #option="{ item }">
							<div class="fw-semibold small">{{ item.ci_number || item.name }}</div>
							<div class="text-secondary" style="font-size:0.75rem">{{ item.supplier_name }}</div>
						</template>
					</Typeahead>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="supersedeFor = null">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="superseding || !supersedeCi" @click="doSupersede">
						<span v-if="superseding" class="spinner-border spinner-border-sm me-1"></span>{{ t("Link") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
