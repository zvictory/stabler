<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate, todayIso } from "../../composables/date.js";
import { formatMoney } from "../../composables/money.js";


import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import Typeahead from "../../components/Typeahead.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/orders");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);
const isDraft = computed(() => isCreate.value || form.value.docstatus === 0);

const loading = ref(false);
const saving = ref(false);
const submitting = ref(false);
const error = ref("");
const form = ref(blankForm());


function round2(v) {
	return Math.round((Number(v) || 0) * 100) / 100;
}



const currencies = ref([]);
const currencyOptions = computed(() => currencies.value.map((c) => ({ value: c.name, label: c.name })));
const piGroups = ref([]);
const piGroupOptions = computed(() => [
	{ value: "", label: t("No group") },
	...piGroups.value.map((g) => ({ value: g.name, label: g.title || g.name })),
]);
const PREPAYMENT_OPTIONS = computed(() => [
	{ value: "Agreed Total", label: t("Agreed Total") },
	{ value: "Docs Total", label: t("Docs Total") },
]);

// Cost visibility: server masks docs figures to null for an existing doc; on
// create the boot flag is authoritative (backend re-checks on write).
const costVisible = computed(() => {
	if (!isCreate.value) return form.value.cost_visible === true;
	return session.costVisible === true;
});

// Advance dialog state.
const advOpen = ref(false);
const advBank = ref(0);
const advCash = ref(0);
const advDate = ref("");
const advRef = ref("");
const advSaving = ref(false);

function blankForm() {
	return {
		name: null,
		modified: null,
		docstatus: 0,
		supplier: "",
		supplier_name: "",
		transaction_date: "",
		schedule_date: "",
		currency: "USD",
		status: "",
		lifecycle: "DRAFT",
		pi_group: "",
		advance_percentage: 0,
		prepayment_type: "Agreed Total",
		docs_total: null,
		cash_difference: null,
		stage: "",
		agreed_total: 0,
		total_kg: 0,
		total_boxes: 0,
		invoiced_pct: 0,
		per_received: 0,
		advance_paid: 0,
		cost_visible: session.costVisible === true,
		items: [],
		commercial_invoices: [],
		advances: [],
		advance_summary: null,
	};
}

// Qty (kg) is derived from boxes × box weight (Django LineItem.save override).
function rowQty(row) {
	return Number(row.boxes || 0) * Number(row.box_weight_kg || 0);
}
const agreedTotal = computed(() =>
	form.value.items.reduce((s, r) => s + rowQty(r) * Number(r.rate || 0), 0)
);
const docsTotal = computed(() =>
	form.value.items.reduce((s, r) => s + rowQty(r) * Number(r.docs_rate || 0), 0)
);
const totalKg = computed(() => form.value.items.reduce((s, r) => s + rowQty(r), 0));
const totalBoxes = computed(() => form.value.items.reduce((s, r) => s + Number(r.boxes || 0), 0));
const cashDifference = computed(() => agreedTotal.value - docsTotal.value);

// Live advance split preview (mirrors rules.advance_summary expected split).
const advanceBase = computed(() =>
	form.value.prepayment_type === "Docs Total" ? docsTotal.value : agreedTotal.value
);
const advanceExpected = computed(() =>
	Math.round(advanceBase.value * Number(form.value.advance_percentage || 0)) / 100
);

function money(v, currency) {
	if (v === null || v === undefined) return "•••";
	return formatMoney(v, currency || form.value.currency || "USD", user.value.language);
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
	const found = itemsList.value.find((i) => (i.item_code || i.name) === row.item_code);
	if (found) {
		row.item_name = found.item_name || found.name;
	}
}
function addItem() {
	form.value.items.push({
		item_code: "",
		item_name: "",
		boxes: 0,
		box_weight_kg: 20,
		rate: 0,
		docs_rate: 0,
	});
}
function removeItem(i) {
	form.value.items.splice(i, 1);
}

async function quickCreateGroup() {

	const title = window.prompt(t("New PI group title:"));
	if (!title || !title.trim()) return;
	try {
		const res = await importsApi.createPiGroup({ company: activeCompany.value, title: title.trim() });
		piGroups.value = await importsApi.listPiGroups(activeCompany.value);
		form.value.pi_group = res.name;
		toast.success(t("PI group created."));
	} catch (err) {
		toast.error(err?.message || t("Could not create the PI group."));
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
		const d = await importsApi.getImportOrder(docName.value);
		form.value = {
			...blankForm(),
			...d,
			items: (d.items || []).map((it) => ({
				item_code: it.item_code,
				item_name: it.item_name || it.item_code,
				boxes: it.boxes,
				box_weight_kg: it.box_weight_kg,
				rate: it.rate,
				docs_rate: it.docs_rate,
			})),
		};
	} catch (err) {
		error.value = err?.message || t("Failed to load the import order.");
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
		piGroups.value = await importsApi.listPiGroups(activeCompany.value);
	} catch (_) {
		piGroups.value = [];
	}
}

function buildValues() {
	const v = {
		transaction_date: form.value.transaction_date || undefined,
		schedule_date: form.value.schedule_date || undefined,
		currency: form.value.currency,
		custom_import_pi_group: form.value.pi_group || undefined,
		custom_advance_percentage: Number(form.value.advance_percentage || 0),
		custom_prepayment_type: form.value.prepayment_type || undefined,
		custom_stage: form.value.stage || undefined,
	};
	if (costVisible.value) {
		v.custom_docs_total = docsTotal.value;
		v.custom_cash_difference = cashDifference.value;
	}
	return v;
}

function itemsPayload() {
	return form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			boxes: Number(r.boxes || 0),
			box_weight_kg: Number(r.box_weight_kg || 0),
			qty: rowQty(r),
			rate: Number(r.rate || 0),
			docs_rate: Number(r.docs_rate || 0),
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
		if (isCreate.value) {
			const res = await importsApi.createImportOrder({
				company: activeCompany.value,
				supplier: form.value.supplier,
				values: buildValues(),
				items: itemsPayload(),
			});
			toast.success(t("Import order created."));
			router.replace("/imports/orders/" + res.name);
		} else {
			await importsApi.updateImportOrder({
				name: docName.value,
				supplier: form.value.supplier,
				values: buildValues(),
				items: itemsPayload(),
				modified: form.value.modified,
			});
			toast.success(t("Import order saved."));
			await loadDoc();
		}
	} catch (err) {
		toast.error(err?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

async function submitOrder() {
	const ok = await confirm({
		title: t("Confirm import order"),
		body: t("Confirm (submit) this import order? It can no longer be edited here afterwards."),
		confirmLabel: t("Confirm"),
	});
	if (!ok) return;
	submitting.value = true;
	try {
		await importsApi.submitImportOrder(docName.value);
		toast.success(t("Import order confirmed."));
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Could not confirm the import order."));
	} finally {
		submitting.value = false;
	}
}

function openAdvance() {
	const remaining = form.value.advance_summary ? form.value.advance_summary.remaining : 0;
	advBank.value = remaining || 0;
	advCash.value = 0;
	advDate.value = todayIso();
	advRef.value = `ADV-${docName.value || "PO"}`;
	fillSplit();
	advOpen.value = true;
}

function fillDocsOnly() {
	const docsExp = form.value.advance_summary?.expected_bank || round2((docsTotal.value || 0) * ((Number(form.value.advance_pct) || 30) / 100));
	advBank.value = docsExp;
	advCash.value = 0;
}

function fillAllBank() {
	const totalExp = form.value.advance_summary?.expected_advance || round2((agreedTotal.value || 0) * ((Number(form.value.advance_pct) || 30) / 100));
	advBank.value = totalExp;
	advCash.value = 0;
}

function fillAllCash() {
	const totalExp = form.value.advance_summary?.expected_advance || round2((agreedTotal.value || 0) * ((Number(form.value.advance_pct) || 30) / 100));
	advBank.value = 0;
	advCash.value = totalExp;
}

function fillSplit() {
	const totalExp = form.value.advance_summary?.expected_advance || round2((agreedTotal.value || 0) * ((Number(form.value.advance_pct) || 30) / 100));
	const total = agreedTotal.value || 1;
	const docsShare = (docsTotal.value || 0) / total;
	advBank.value = round2(totalExp * docsShare);
	advCash.value = round2(totalExp - advBank.value);
}

async function recordAdvance() {

	if (Number(advBank.value || 0) <= 0 && Number(advCash.value || 0) <= 0) {
		toast.error(t("Enter a bank and/or cash amount."));
		return;
	}
	advSaving.value = true;
	try {
		const res = await importsApi.createAdvancePayment({
			purchase_order: docName.value,
			bank_amount: Number(advBank.value || 0),
			cash_amount: Number(advCash.value || 0),
			payment_date: advDate.value || undefined,
			reference_no: advRef.value || undefined,
		});
		if (res.warning) toast.info(res.warning);
		toast.success(t("Advance recorded (draft)."));
		advOpen.value = false;
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Could not record the advance."));
	} finally {
		advSaving.value = false;
	}
}

onMounted(() => {
	loadItemsList();
	loadRefData();
	loadDoc();
});
watch(docName, loadDoc);
watch(activeCompany, loadRefData);
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push('/imports/orders')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">
					{{ isCreate ? t("New import order") : (form.name) }}
				</h2>
				<div v-if="!isCreate" class="text-secondary small d-flex align-items-center gap-2 mt-1">
					<StatusBadge doctype="Import Order" :status="form.lifecycle" />
					<StatusBadge v-if="form.advance_summary" doctype="Import Order Payment" :status="form.advance_summary.badge" />
					<span v-if="form.supplier_name">{{ form.supplier_name }}</span>
				</div>
			</div>
			<div class="ms-auto d-flex gap-2">
				<button v-if="isDraft" type="button" class="btn btn-outline-secondary" :disabled="saving" @click="save">
					<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
				</button>
				<button
					v-if="!isCreate && isDraft"
					type="button"
					class="btn btn-primary"
					:disabled="submitting"
					@click="submitOrder"
				>
					<i class="ti ti-check me-1"></i>{{ t("Confirm") }}
				</button>
				<button
					v-if="!isCreate && !isDraft && form.docstatus === 1"
					type="button"
					class="btn btn-primary"
					@click="openAdvance"
				>
					<i class="ti ti-cash me-1"></i>{{ t("Record advance") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- Header -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Header") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-5">
						<label class="form-label required">{{ t("Supplier") }}</label>
						<Typeahead
							v-if="isDraft"
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
						<div v-else class="form-control-plaintext">{{ form.supplier_name || form.supplier }}</div>
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Date") }}</label>
						<DateInput v-if="isDraft" v-model="form.transaction_date" />
						<div v-else class="form-control-plaintext">{{ formatDate(form.transaction_date) }}</div>
					</div>
					<div class="col-md-2">
						<label class="form-label">{{ t("Currency") }}</label>
						<Select v-if="isDraft" v-model="form.currency" :options="currencyOptions" :placeholder="t('Currency')" />
						<div v-else class="form-control-plaintext">{{ form.currency }}</div>
					</div>
					<div class="col-md-2">
						<label class="form-label">{{ t("PI group") }}</label>
						<div class="d-flex gap-1">
							<Select v-model="form.pi_group" :options="piGroupOptions" :disabled="!isDraft" style="flex: 1" />
							<button v-if="isDraft" type="button" class="btn btn-outline-secondary btn-icon" :title="t('New PI group')" @click="quickCreateGroup">
								<i class="ti ti-plus"></i>
							</button>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Payment terms -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Payment terms") }}</h3></div>
			<div class="card-body">
				<div class="row g-3 align-items-end">
					<div class="col-md-4">
						<label class="form-label">{{ t("Advance base") }}</label>
						<Select v-if="isDraft" v-model="form.prepayment_type" :options="PREPAYMENT_OPTIONS" />
						<div v-else class="form-control-plaintext">{{ t(form.prepayment_type || "Agreed Total") }}</div>
					</div>
					<div class="col-md-4">
						<label class="form-label">{{ t("Advance %") }}</label>
						<input
							v-if="isDraft"
							v-model.number="form.advance_percentage"
							type="number"
							min="0"
							max="100"
							class="form-control"
						/>
						<div v-else class="form-control-plaintext font-monospace">{{ Number(form.advance_percentage || 0).toFixed(0) }}%</div>
					</div>
					<div class="col-md-4">
						<div class="text-secondary small">{{ t("Expected advance") }}</div>
						<div class="h3 mb-0 font-monospace">{{ costVisible ? money(advanceExpected) : "•••" }}</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Items -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Items") }}</h3>
				<div v-if="isDraft" class="card-actions">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="addItem">
						<i class="ti ti-plus me-1"></i>{{ t("Add item") }}
					</button>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th style="width: 26%">{{ t("Item") }}</th>
							<th class="text-end" style="width: 90px">{{ t("Boxes") }}</th>
							<th class="text-end" style="width: 110px">{{ t("Box (kg)") }}</th>
							<th class="text-end" style="width: 110px">{{ t("Qty (kg)") }}</th>
							<th class="text-end" style="width: 120px">{{ t("Agreed rate") }}</th>
							<th v-if="costVisible" class="text-end" style="width: 120px">{{ t("Docs rate") }}</th>
							<th class="text-end" style="width: 120px">{{ t("Agreed total") }}</th>
							<th v-if="isDraft" style="width: 40px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, i) in form.items" :key="i">
							<td>
								<select v-if="isDraft" v-model="row.item_code" class="form-select form-select-sm fw-semibold" @change="onItemSelect(row)">
									<option value="">— {{ t("Select product") }} —</option>
									<option v-for="it in itemsList" :key="it.item_code || it.name" :value="it.item_code || it.name">
										{{ it.item_code || it.name }} — {{ it.item_name }}
									</option>
								</select>
								<div v-else>
									<div class="fw-semibold">{{ row.item_name || row.item_code }}</div>
									<div class="small text-secondary font-monospace">{{ row.item_code }}</div>
								</div>
							</td>
							<td>
								<input v-if="isDraft" v-model.number="row.boxes" type="number" min="0" class="form-control form-control-sm text-end" />
								<span v-else class="font-monospace">{{ row.boxes || 0 }}</span>
							</td>
							<td>
								<MoneyInput v-if="isDraft" v-model="row.box_weight_kg" :language="user.language" size="sm" />
								<span v-else class="font-monospace">{{ Number(row.box_weight_kg || 0).toFixed(1) }}</span>
							</td>
							<td class="text-end font-monospace align-middle">{{ rowQty(row).toFixed(0) }}</td>
							<td>
								<MoneyInput v-if="isDraft" v-model="row.rate" :currency="form.currency" :language="user.language" size="sm" />
								<span v-else class="font-monospace">{{ money(row.rate) }}</span>
							</td>
							<td v-if="costVisible">
								<MoneyInput v-if="isDraft" v-model="row.docs_rate" :currency="form.currency" :language="user.language" size="sm" />
								<span v-else class="font-monospace">{{ money(row.docs_rate) }}</span>
							</td>
							<td class="text-end font-monospace align-middle">{{ money(rowQty(row) * Number(row.rate || 0)) }}</td>
							<td v-if="isDraft" class="text-center align-middle">
								<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeItem(i)">
									<i class="ti ti-trash"></i>
								</button>
							</td>
						</tr>
						<tr v-if="!form.items.length">
							<td :colspan="costVisible ? 8 : 7" class="text-secondary text-center py-3">{{ t("No items yet.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<div class="row">
			<!-- Totals -->
			<div class="col-lg-5">
				<div class="card mb-3">
					<div class="card-header"><h3 class="card-title">{{ t("Totals") }}</h3></div>
					<div class="card-body">
						<div class="d-flex justify-content-between mb-1">
							<span class="text-secondary">{{ t("Boxes") }}</span>
							<strong class="font-monospace">{{ totalBoxes.toLocaleString() }}</strong>
						</div>
						<div class="d-flex justify-content-between mb-1">
							<span class="text-secondary">{{ t("Total weight (kg)") }}</span>
							<strong class="font-monospace">{{ totalKg.toFixed(0) }}</strong>
						</div>
						<div class="d-flex justify-content-between mb-1">
							<span class="text-secondary">{{ t("Agreed total") }}</span>
							<strong class="font-monospace">{{ money(agreedTotal) }}</strong>
						</div>
						<template v-if="costVisible">
							<div class="d-flex justify-content-between mb-1">
								<span class="text-secondary">{{ t("Docs total") }}</span>
								<strong class="font-monospace">{{ money(docsTotal) }}</strong>
							</div>
							<div class="d-flex justify-content-between">
								<span class="text-secondary">{{ t("Cash difference") }}</span>
								<strong class="font-monospace text-warning">{{ money(cashDifference) }}</strong>
							</div>
						</template>
					</div>
				</div>
			</div>

			<!-- Advance summary (submitted only) -->
			<div v-if="!isCreate && form.advance_summary" class="col-lg-7">
				<div class="card mb-3">
					<div class="card-header">
						<h3 class="card-title">{{ t("Advance summary") }}</h3>
						<div class="card-actions">
							<StatusBadge doctype="Import Order Payment" :status="form.advance_summary.badge" />
						</div>
					</div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-4">
								<div class="text-secondary small">{{ t("Expected") }}</div>
								<div class="h4 mb-0 font-monospace">{{ money(form.advance_summary.expected) }}</div>
							</div>
							<div class="col-4">
								<div class="text-secondary small">{{ t("Paid") }}</div>
								<div class="h4 mb-0 font-monospace">{{ money(form.advance_summary.paid) }}</div>
							</div>
							<div class="col-4">
								<div class="text-secondary small">{{ t("Remaining") }}</div>
								<div class="h4 mb-0 font-monospace text-warning">{{ money(form.advance_summary.remaining) }}</div>
							</div>
						</div>
						<div v-if="costVisible" class="d-flex justify-content-between small mt-3">
							<span class="text-secondary">{{ t("Bank") }}</span>
							<span class="font-monospace">{{ money(form.advance_summary.paid_bank) }} / {{ money(form.advance_summary.expected_bank) }}</span>
						</div>
						<div v-if="costVisible" class="d-flex justify-content-between small mt-1">
							<span class="text-secondary">{{ t("Cash") }}</span>
							<span class="font-monospace">{{ money(form.advance_summary.paid_cash) }} / {{ money(form.advance_summary.expected_cash) }}</span>
						</div>

						<!-- Record-advance panel -->
						<div v-if="advOpen" class="mt-3 p-3 border rounded bg-light">
							<!-- Quick action buttons -->
							<div class="mb-2 d-flex gap-1 flex-wrap">
								<button type="button" class="btn btn-xs btn-outline-info" @click="fillDocsOnly">
									<i class="ti ti-bolt me-1"></i>{{ t("Docs Only") }}
								</button>
								<button type="button" class="btn btn-xs btn-outline-primary" @click="fillAllBank">
									<i class="ti ti-building-bank me-1"></i>{{ t("100% Bank") }}
								</button>
								<button type="button" class="btn btn-xs btn-outline-warning" @click="fillAllCash">
									<i class="ti ti-cash me-1"></i>{{ t("100% Cash") }}
								</button>
								<button type="button" class="btn btn-xs btn-outline-success" @click="fillSplit">
									<i class="ti ti-scale me-1"></i>{{ t("Proportional Split") }}
								</button>
							</div>

							<div class="row g-2">
								<div class="col-md-6">
									<label class="form-label small fw-bold text-primary">{{ t("Bank amount") }}</label>
									<MoneyInput v-model="advBank" :currency="form.currency" :language="user.language" size="sm" />
								</div>
								<div class="col-md-6">
									<label class="form-label small fw-bold text-orange">{{ t("Cash amount") }}</label>
									<MoneyInput v-model="advCash" :currency="form.currency" :language="user.language" size="sm" />
								</div>
								<div class="col-md-6">
									<label class="form-label small">{{ t("Payment date") }}</label>
									<DateInput v-model="advDate" />
								</div>
								<div class="col-md-6">
									<label class="form-label small">{{ t("Reference no") }}</label>
									<input v-model="advRef" type="text" class="form-control form-control-sm" />
								</div>
							</div>
							<div class="d-flex gap-2 mt-2">
								<button type="button" class="btn btn-primary btn-sm" :disabled="advSaving" @click="recordAdvance">
									{{ t("Save advance") }}
								</button>
								<button type="button" class="btn btn-ghost-secondary btn-sm" @click="advOpen = false">
									{{ t("Cancel") }}
								</button>
							</div>
						</div>


						<div v-if="form.advances.length" class="table-responsive mt-3">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("Payment Entry") }}</th>
										<th>{{ t("Stream") }}</th>
										<th class="text-nowrap">{{ t("Date") }}</th>
										<th class="text-end">{{ t("Amount") }}</th>
										<th>{{ t("Status") }}</th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="pe in form.advances" :key="pe.name">
										<td class="font-monospace">{{ pe.name }}</td>
										<td>{{ t(pe.payment_stream) }}</td>
										<td class="text-nowrap">{{ formatDate(pe.posting_date) }}</td>
										<td class="text-end font-monospace">{{ money(pe.paid_amount) }}</td>
										<td><StatusBadge doctype="Payment Entry" :docstatus="pe.docstatus" /></td>
									</tr>
								</tbody>
							</table>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Linked commercial invoices (submitted view) -->
		<div v-if="!isCreate && form.commercial_invoices.length" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Commercial Invoices") }}</h3>
				<div class="card-subtitle">
					{{ Number(form.invoiced_pct || 0).toFixed(0) }}% {{ t("invoiced") }}
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th>{{ t("Commercial Invoice") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Allocated (kg)") }}</th>
							<th class="text-end">{{ t("Allocated amount") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr
							v-for="ci in form.commercial_invoices"
							:key="ci.name"
							style="cursor: pointer"
							@click="router.push('/imports/commercial-invoices/' + ci.name)"
						>
							<td class="font-monospace text-primary">{{ ci.ci_number || ci.name }}</td>
							<td><StatusBadge doctype="Commercial Invoice" :status="ci.status" /></td>
							<td class="text-end font-monospace">{{ Number(ci.allocated_kg || 0).toFixed(0) }}</td>
							<td class="text-end font-monospace">{{ money(ci.allocated_amount) }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>
	</div>
</template>
