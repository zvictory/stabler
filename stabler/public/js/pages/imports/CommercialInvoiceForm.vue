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
useEscapeBack(null, "/imports/commercial-invoices");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const form = ref(blankForm());

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

const customsFee = ref(null);
const computingFee = ref(false);

function blankForm() {
	return {
		name: null,
		modified: null,
		company: null,
		supplier: "",
		supplier_name: "",
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
	};
}

const agreedTotal = computed(() =>
	form.value.items.reduce((sum, r) => sum + Number(r.qty || 0) * Number(r.rate || 0), 0)
);
const totalKg = computed(() =>
	form.value.items.reduce((sum, r) => sum + Number(r.qty || 0), 0)
);

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

async function searchItems(q) {
	return call("stabler.api.inventory.list_items", {
		search: q || "",
		limit: 20,
	});
}

function addItem() {
	form.value.items.push({
		item: "",
		item_name: "",
		description: "",
		hs_code: "",
		qty: 0,
		uom: "Kg",
		rate: 0,
	});
}
function removeItem(i) {
	form.value.items.splice(i, 1);
}
function pickItem(row, item) {
	row.item = item.name;
	row.item_name = item.item_name || item.name;
	if (!row.description) row.description = item.item_name || "";
}

function addPoLink() {
	form.value.po_links.push({ purchase_order: "" });
}
function removePoLink(i) {
	form.value.po_links.splice(i, 1);
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
				item: it.item,
				item_name: it.item,
				description: it.description || "",
				hs_code: it.hs_code || "",
				qty: it.qty,
				uom: it.uom || "Kg",
				rate: it.rate,
			})),
			po_links: (d.po_links || []).map((p) => ({ purchase_order: p.purchase_order })),
			containers: d.containers || [],
			customs_declarations: d.customs_declarations || [],
		};
		customsFee.value = d.customs_fee_breakdown || null;
	} catch (err) {
		error.value = err?.message || t("Failed to load the commercial invoice.");
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
		if (form.value.docs_total !== null && form.value.docs_total !== "") v.docs_total = form.value.docs_total;
		if (form.value.cash_difference !== null && form.value.cash_difference !== "")
			v.cash_difference = form.value.cash_difference;
	}
	return v;
}

function itemsPayload() {
	return form.value.items
		.filter((r) => r.item)
		.map((r) => ({
			item: r.item,
			description: r.description || undefined,
			hs_code: r.hs_code || undefined,
			qty: Number(r.qty || 0),
			uom: r.uom || undefined,
			rate: Number(r.rate || 0),
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

async function computeFee(apply) {
	computingFee.value = true;
	try {
		customsFee.value = await importsApi.computeCustomsFee({
			commercial_invoice: docName.value,
			off_hours: form.value.customs_fee_off_hours ? 1 : 0,
			apply: apply ? 1 : 0,
		});
		if (apply) {
			toast.success(t("Customs fee applied."));
			await loadDoc();
		}
	} catch (err) {
		toast.error(err?.message || t("Could not compute the customs fee."));
	} finally {
		computingFee.value = false;
	}
}

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

onMounted(() => {
	loadRefData();
	loadDoc();
});
watch(docName, loadDoc);
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
						<div class="h3 mb-0 font-monospace text-primary fw-bold">{{ fm(agreedTotal, form.currency) }}</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Docs total") }}</div>
						<div class="h3 mb-0 font-monospace text-azure fw-bold">
							{{ form.docs_total != null ? fm(form.docs_total, form.currency) : "—" }}
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Cash Difference") }}</div>
						<div class="h3 mb-0 font-monospace text-warning fw-bold">
							{{ form.cash_difference != null ? fm(form.cash_difference, form.currency) : "—" }}
						</div>
					</div>
				</div>
			</div>
			<div class="col-sm-6 col-lg-3">
				<div class="card card-sm">
					<div class="card-body">
						<div class="font-weight-medium text-secondary small">{{ t("Containers") }}</div>
						<div class="h3 mb-0 font-monospace">
							{{ form.containers ? form.containers.length : 0 }} <span class="text-secondary fs-6">cnt</span>
						</div>
					</div>
				</div>
			</div>
		</div>

		<!-- Header Details -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Header Details") }}</h3></div>
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

		<!-- Items -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Items") }}</h3>
				<div class="card-actions">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="addItem">
						<i class="ti ti-plus me-1"></i>{{ t("Add item") }}
					</button>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th style="width: 24%">{{ t("Item") }}</th>
							<th>{{ t("Description") }}</th>
							<th style="width: 100px">{{ t("HS code") }}</th>
							<th class="text-end" style="width: 120px">{{ t("Qty (kg)") }}</th>
							<th class="text-end" style="width: 130px">{{ t("Rate") }} ({{ form.currency || 'USD' }})</th>
							<th class="text-end" style="width: 140px">{{ t("Amount") }} ({{ form.currency || 'USD' }})</th>
							<th style="width: 40px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, i) in form.items" :key="i">
							<td>
								<Typeahead
									v-slot="{ item }"
									v-model="row.item"
									:search="searchItems"
									:display="row.item_name"
									:placeholder="t('Search item…')"
									@pick="(it) => pickItem(row, it)"
								>
									<div class="fw-semibold">{{ item.item_name || item.name }}</div>
									<div class="small text-secondary font-monospace">{{ item.name }}</div>
								</Typeahead>
							</td>
							<td><input v-model="row.description" type="text" class="form-control form-control-sm" /></td>
							<td><input v-model="row.hs_code" type="text" class="form-control form-control-sm" /></td>
							<td>
								<MoneyInput v-model="row.qty" :language="user.language" hide-currency size="sm" />
							</td>
							<td>
								<MoneyInput v-model="row.rate" :currency="form.currency" :language="user.language" hide-currency size="sm" />
							</td>
							<td class="text-end font-monospace align-middle text-primary fw-semibold">
								{{ fn(Number(row.qty || 0) * Number(row.rate || 0)) }}
							</td>
							<td class="text-center align-middle">
								<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeItem(i)">
									<i class="ti ti-trash"></i>
								</button>
							</td>
						</tr>
						<tr v-if="!form.items.length">
							<td colspan="7" class="text-secondary text-center py-3">{{ t("No items yet.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Linked Containers -->
		<div v-if="form.containers && form.containers.length" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title"><i class="ti ti-box me-2"></i>{{ t("Linked Containers") }}</h3>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter table-hover">
					<thead>
						<tr>
							<th>{{ t("Container Number") }}</th>
							<th>{{ t("Status") }}</th>
							<th class="text-end">{{ t("Boxes") }}</th>
							<th class="text-end">{{ t("Total Weight (kg)") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="cnt in form.containers" :key="cnt.name">
							<td class="font-monospace fw-bold text-primary">{{ cnt.container_number || cnt.name }}</td>
							<td><span class="badge bg-secondary-lt">{{ cnt.status }}</span></td>
							<td class="text-end font-monospace">{{ fn(cnt.total_boxes) }}</td>
							<td class="text-end font-monospace fw-semibold">{{ fn(cnt.total_kg) }} kg</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- PO links -->
		<div class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Linked purchase orders") }}</h3>
				<div class="card-actions">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="addPoLink">
						<i class="ti ti-plus me-1"></i>{{ t("Add PO link") }}
					</button>
				</div>
			</div>
			<div class="card-body">
				<div v-for="(link, i) in form.po_links" :key="i" class="d-flex gap-2 mb-2">
					<Select v-model="link.purchase_order" :options="poOptions" style="flex: 1" :placeholder="t('Select purchase order…')" />
					<button type="button" class="btn btn-ghost-danger btn-icon" @click="removePoLink(i)">
						<i class="ti ti-trash"></i>
					</button>
				</div>
				<div v-if="!form.po_links.length" class="text-secondary small">{{ t("No purchase orders linked.") }}</div>
			</div>
		</div>

		<div class="row">
			<!-- Totals -->
			<div class="col-lg-6">
				<div class="card mb-3">
					<div class="card-header"><h3 class="card-title">{{ t("Totals") }}</h3></div>
					<div class="card-body">
						<div class="d-flex justify-content-between mb-1">
							<span class="text-secondary">{{ t("Total weight (kg)") }}</span>
							<strong class="font-monospace">{{ fn(totalKg) }} kg</strong>
						</div>
						<div class="d-flex justify-content-between mb-1">
							<span class="text-secondary">{{ t("Agreed total") }}</span>
							<strong class="font-monospace text-primary">{{ fm(agreedTotal, form.currency) }}</strong>
						</div>
						<template v-if="costVisible">
							<div class="row g-2 mt-1">
								<div class="col-6">
									<label class="form-label small">{{ t("Docs total") }}</label>
									<MoneyInput v-model="form.docs_total" :currency="form.currency" :language="user.language" size="sm" />
								</div>
								<div class="col-6">
									<label class="form-label small">{{ t("Cash difference") }}</label>
									<MoneyInput v-model="form.cash_difference" :currency="form.currency" :language="user.language" size="sm" />
								</div>
							</div>
						</template>
					</div>
				</div>
			</div>

			<!-- Customs fee -->
			<div class="col-lg-6">
				<div class="card mb-3">
					<div class="card-header"><h3 class="card-title">{{ t("Customs clearance fee") }}</h3></div>
					<div class="card-body">
						<label class="form-check">
							<input v-model="form.customs_fee_off_hours" type="checkbox" class="form-check-input" :true-value="1" :false-value="0" />
							<span class="form-check-label">{{ t("Off-hours clearance (+25% BRV)") }}</span>
						</label>
						<div v-if="customsFee" class="mt-2 small">
							<div class="d-flex justify-content-between"><span class="text-secondary">{{ t("Declared value (USD)") }}</span><span class="font-monospace">{{ formatMoney(customsFee.value_usd, "USD", user.language) }}</span></div>
							<div class="d-flex justify-content-between"><span class="text-secondary">{{ t("BRV used") }}</span><span class="font-monospace">{{ formatMoney(customsFee.brv_value, "UZS", user.language) }}</span></div>
							<div class="d-flex justify-content-between"><span class="text-secondary">{{ t("Multiplier") }}</span><span class="font-monospace">×{{ customsFee.multiplier }}</span></div>
							<div class="d-flex justify-content-between"><span class="text-secondary">{{ t("Off-hours surcharge") }}</span><span class="font-monospace">{{ formatMoney(customsFee.off_hours_surcharge, "UZS", user.language) }}</span></div>
							<div class="d-flex justify-content-between fw-bold"><span>{{ t("Effective fee") }}</span><span class="font-monospace">{{ formatMoney(customsFee.effective_fee_uzs, "UZS", user.language) }}</span></div>
						</div>
						<div v-else class="text-secondary small mt-2">{{ t("Compute the fee to see the BRV breakdown.") }}</div>
						<div v-if="!isCreate" class="d-flex gap-2 mt-2">
							<button type="button" class="btn btn-outline-secondary btn-sm" :disabled="computingFee" @click="computeFee(false)">
								<i class="ti ti-calculator me-1"></i>{{ t("Compute") }}
							</button>
							<button type="button" class="btn btn-ghost-secondary btn-sm" :disabled="computingFee" @click="computeFee(true)">
								{{ t("Apply") }}
							</button>
						</div>
						<div v-else class="text-secondary small mt-2">{{ t("Save the invoice first to compute the customs fee.") }}</div>
					</div>
				</div>
			</div>
		</div>
	</div>
</template>
