<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();
const { confirm } = useConfirm();
useEscapeBack(null, "/imports/containers");

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const error = ref("");
const form = ref(blankForm());

// On create the boot flag decides; on edit the server tells us via cost_visible.
const costVisible = computed(() =>
	isCreate.value ? session.costVisible === true : form.value.cost_visible === true
);
const canRollback = computed(() =>
	(session.roles || []).some((r) => ["Imports Manager", "System Manager", "Stabler Admin"].includes(r))
);

const TYPES = ["DC", "RF", "OT", "FR", "TK"];
const SIZES = ["20", "40", "40HC"];
const BL_TYPES = ["ORIGINAL_BL", "MASTER_BL", "HOUSE_BL", "TELEX_RELEASE", "EXPRESS_BL"];
const COST_COMPONENTS = [
	"Freight", "Iran Customs Duty", "Iran Port & THC", "Iran Storage", "Iran Demurrage",
	"Iran Inspection", "Cross-Border Transport", "Insurance", "Certificate",
	"Uzbekistan Customs Duty", "Uzbekistan Port Handling", "Customs Clearance Fee", "Other",
];

const typeOptions = TYPES.map((v) => ({ value: v, label: v }));
const sizeOptions = [{ value: "", label: t("Not set") }, ...SIZES.map((v) => ({ value: v, label: v }))];
const blOptions = [{ value: "", label: t("Not set") }, ...BL_TYPES.map((v) => ({ value: v, label: t(v) }))];
const componentOptions = COST_COMPONENTS.map((v) => ({ value: v, label: t(v) }));

const currencies = ref([]);
const currencyOptions = computed(() => currencies.value.map((c) => ({ value: c.name, label: c.name })));

const PIPELINE = [
	"BOOKED", "STUFFED", "GATE_IN", "ON_BOARD", "IN_TRANSIT",
	"DISCHARGED", "AVAILABLE", "ARRIVED_AT_IRAN", "DELIVERED_TO_UZBEKISTAN",
];
const rollbackTarget = computed(() => {
	const idx = PIPELINE.indexOf(form.value.status);
	return idx > 0 ? PIPELINE[idx - 1] : null;
});

function blankForm() {
	return {
		name: null,
		modified: null,
		cost_visible: false,
		container_number: "",
		commercial_invoice: "",
		supplier: "",
		currency: "USD",
		container_type: "RF",
		container_size: "",
		bl_type: "",
		seal_number: "",
		gross_weight: 0,
		vgm: 0,
		status: "BOOKED",
		total_boxes: 0,
		total_kg: 0,
		total_amount: null,
		cut_off: "",
		gate_open: "",
		gate_close: "",
		gate_in_date: "",
		customs_clearance_date: "",
		telex_release_date: "",
		payment_70_status: "Pending",
		payment_70_date: "",
		allowed_transitions: [],
		items: [],
		cost_lines: [],
	};
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
	form.value.items.push({ item_code: "", item_name: "", category: "", box_qty: 0, box_kg: 0, total_kg: 0, rate: 0, amount: 0 });
}
function removeItem(i) {
	form.value.items.splice(i, 1);
}
function addCostLine() {
	form.value.cost_lines.push({ cost_component: "Freight", description: "", currency: form.value.currency || "USD", amount: 0, amount_uzs: 0, include_in_landed_cost: 1, lcv_ref: null });
}
function removeCostLine(i) {
	form.value.cost_lines.splice(i, 1);
}

async function loadDoc() {
	if (isCreate.value) {
		form.value = blankForm();
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		const d = await importsApi.getImportContainer(docName.value);
		form.value = {
			...blankForm(),
			...d,
			items: (d.items || []).map((it) => ({ ...it })),
			cost_lines: (d.cost_lines || []).map((cl) => ({ ...cl })),
		};
	} catch (err) {
		error.value = err?.message || t("Failed to load the container.");
	} finally {
		loading.value = false;
	}
}

async function loadRefData() {
	try {
		currencies.value = await call("stabler.api.sales.list_currencies", {});
	} catch (_) {
		currencies.value = [{ name: "USD" }, { name: "EUR" }, { name: "UZS" }];
	}
}

function buildValues() {
	const v = {
		container_number: form.value.container_number,
		commercial_invoice: form.value.commercial_invoice || undefined,
		supplier: form.value.supplier || undefined,
		currency: form.value.currency,
		container_type: form.value.container_type,
		container_size: form.value.container_size,
		bl_type: form.value.bl_type,
		seal_number: form.value.seal_number,
		gross_weight: Number(form.value.gross_weight || 0),
		vgm: Number(form.value.vgm || 0),
		total_boxes: Number(form.value.total_boxes || 0),
		total_kg: Number(form.value.total_kg || 0),
		cut_off: form.value.cut_off || undefined,
		gate_open: form.value.gate_open || undefined,
		gate_close: form.value.gate_close || undefined,
		gate_in_date: form.value.gate_in_date || undefined,
		customs_clearance_date: form.value.customs_clearance_date || undefined,
		telex_release_date: form.value.telex_release_date || undefined,
		payment_70_status: form.value.payment_70_status,
		payment_70_date: form.value.payment_70_date || undefined,
	};
	if (costVisible.value && form.value.total_amount !== null && form.value.total_amount !== "") {
		v.total_amount = Number(form.value.total_amount);
	}
	return v;
}

function itemsPayload() {
	return form.value.items
		.filter((r) => r.item_code)
		.map((r) => ({
			item_code: r.item_code,
			item_name: r.item_name || undefined,
			category: r.category || undefined,
			box_qty: Number(r.box_qty || 0),
			box_kg: Number(r.box_kg || 0),
			total_kg: Number(r.total_kg || 0),
			rate: Number(r.rate || 0),
			amount: Number(r.amount || 0),
		}));
}

function costLinesPayload() {
	// Only cost-visible users may write cost lines; otherwise omit entirely so the
	// backend never rejects and existing lines are preserved.
	if (!costVisible.value) return undefined;
	return form.value.cost_lines
		.filter((r) => r.cost_component)
		.map((r) => ({
			cost_component: r.cost_component,
			description: r.description || undefined,
			currency: r.currency || "USD",
			amount: Number(r.amount || 0),
			amount_uzs: Number(r.amount_uzs || 0),
			include_in_landed_cost: r.include_in_landed_cost ? 1 : 0,
		}));
}

async function save() {
	saving.value = true;
	try {
		if (isCreate.value) {
			const res = await importsApi.createImportContainer({
				company: activeCompany.value,
				values: buildValues(),
				items: itemsPayload(),
				cost_lines: costLinesPayload(),
			});
			toast.success(t("Container created."));
			router.replace("/imports/containers/" + res.name);
		} else {
			await importsApi.updateImportContainer({
				name: docName.value,
				values: buildValues(),
				items: itemsPayload(),
				cost_lines: costLinesPayload(),
				modified: form.value.modified,
			});
			toast.success(t("Container saved."));
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
			body: t("Move this container to {status}?", { status: t(nextStatus) }),
			confirmLabel: t("Confirm"),
		});
		if (!ok) return;
	}
	try {
		await importsApi.setContainerStatus(docName.value, nextStatus, reason);
		toast.success(t("Status updated."));
		await loadDoc();
	} catch (err) {
		toast.error(err?.message || t("Status change failed."));
	}
}

onMounted(() => {
	loadItemsList();
	loadRefData();
	loadDoc();
});
watch(docName, loadDoc);
</script>

<template>
	<div>
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push('/imports/containers')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ isCreate ? t("New container") : (form.container_number || form.name) }}</h2>
				<div v-if="!isCreate" class="text-secondary small">
					<StatusBadge doctype="Import Container" :status="form.status" />
				</div>
			</div>
			<div class="ms-auto d-flex gap-2">
				<button v-if="!isCreate" type="button" class="btn btn-outline-secondary" @click="router.push('/imports/containers/' + docName + '/ledger')">
					<i class="ti ti-report-money me-1"></i>{{ t("Cost ledger") }}
				</button>
				<button type="button" class="btn btn-primary" :disabled="saving" @click="save">
					<i class="ti ti-device-floppy me-1"></i>{{ t("Save") }}
				</button>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<!-- Status action bar -->
		<div v-if="!isCreate" class="card mb-3">
			<div class="card-body d-flex align-items-center flex-wrap gap-2">
				<span class="text-secondary small">{{ t("Status") }}:</span>
				<StatusBadge doctype="Import Container" :status="form.status" />
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

		<!-- Header -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Header") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-3">
						<label class="form-label">{{ t("Container number") }}</label>
						<input v-model="form.container_number" type="text" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Commercial Invoice") }}</label>
						<input v-model="form.commercial_invoice" type="text" class="form-control font-monospace" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Currency") }}</label>
						<Select v-model="form.currency" :options="currencyOptions" :placeholder="t('Currency')" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Seal number") }}</label>
						<input v-model="form.seal_number" type="text" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Type") }}</label>
						<Select v-model="form.container_type" :options="typeOptions" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Size") }}</label>
						<Select v-model="form.container_size" :options="sizeOptions" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("B/L type") }}</label>
						<Select v-model="form.bl_type" :options="blOptions" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("70% payment status") }}</label>
						<Select v-model="form.payment_70_status" :options="[{value:'Pending',label:t('Pending')},{value:'Partial',label:t('Partial')},{value:'Paid',label:t('Paid')}]" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Gross weight") }}</label>
						<input v-model.number="form.gross_weight" type="number" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("VGM") }}</label>
						<input v-model.number="form.vgm" type="number" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Total boxes") }}</label>
						<input v-model.number="form.total_boxes" type="number" class="form-control" />
					</div>
					<div class="col-md-3">
						<label class="form-label">{{ t("Total weight (kg)") }}</label>
						<input v-model.number="form.total_kg" type="number" class="form-control" />
					</div>
				</div>
			</div>
		</div>

		<!-- Dates -->
		<div class="card mb-3">
			<div class="card-header"><h3 class="card-title">{{ t("Dates") }}</h3></div>
			<div class="card-body">
				<div class="row g-3">
					<div class="col-md-3"><label class="form-label">{{ t("Cut-off") }}</label><DateInput v-model="form.cut_off" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Gate open") }}</label><DateInput v-model="form.gate_open" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Gate close") }}</label><DateInput v-model="form.gate_close" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Gate-in date") }}</label><DateInput v-model="form.gate_in_date" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Customs clearance") }}</label><DateInput v-model="form.customs_clearance_date" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("Telex release") }}</label><DateInput v-model="form.telex_release_date" /></div>
					<div class="col-md-3"><label class="form-label">{{ t("70% payment date") }}</label><DateInput v-model="form.payment_70_date" /></div>
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
							<th style="width: 26%">{{ t("Item") }}</th>
							<th>{{ t("Category") }}</th>
							<th class="text-end" style="width: 100px">{{ t("Boxes") }}</th>
							<th class="text-end" style="width: 100px">{{ t("Box kg") }}</th>
							<th class="text-end" style="width: 110px">{{ t("Total kg") }}</th>
							<th v-if="costVisible" class="text-end" style="width: 110px">{{ t("Rate") }}</th>
							<th style="width: 40px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, i) in form.items" :key="i">
							<td>
								<select v-model="row.item_code" class="form-select form-select-sm fw-semibold" @change="onItemSelect(row)">
									<option value="">— {{ t("Select product") }} —</option>
									<option v-for="it in itemsList" :key="it.item_code || it.name" :value="it.item_code || it.name">
										{{ it.item_code || it.name }} — {{ it.item_name }}
									</option>
								</select>
							</td>
							<td><input v-model="row.category" type="text" class="form-control form-control-sm" /></td>
							<td><input v-model.number="row.box_qty" type="number" class="form-control form-control-sm text-end" /></td>
							<td><input v-model.number="row.box_kg" type="number" class="form-control form-control-sm text-end" /></td>
							<td><input v-model.number="row.total_kg" type="number" class="form-control form-control-sm text-end" /></td>
							<td v-if="costVisible"><MoneyInput v-model="row.rate" :language="user.language" size="sm" /></td>
							<td class="text-center align-middle">
								<button type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeItem(i)"><i class="ti ti-trash"></i></button>
							</td>
						</tr>
						<tr v-if="!form.items.length">
							<td :colspan="costVisible ? 7 : 6" class="text-secondary text-center py-3">{{ t("No items yet.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Cost lines (cost-visible only) -->
		<div v-if="costVisible" class="card mb-3">
			<div class="card-header">
				<h3 class="card-title">{{ t("Landed-cost lines") }}</h3>
				<div class="card-actions">
					<button type="button" class="btn btn-outline-secondary btn-sm" @click="addCostLine">
						<i class="ti ti-plus me-1"></i>{{ t("Add cost line") }}
					</button>
				</div>
			</div>
			<div class="table-responsive">
				<table class="table table-vcenter card-table">
					<thead>
						<tr>
							<th style="width: 22%">{{ t("Component") }}</th>
							<th>{{ t("Description") }}</th>
							<th style="width: 90px">{{ t("Currency") }}</th>
							<th class="text-end" style="width: 130px">{{ t("Amount") }}</th>
							<th class="text-end" style="width: 130px">{{ t("Amount (UZS)") }}</th>
							<th class="text-center" style="width: 90px">{{ t("Landed") }}</th>
							<th style="width: 40px"></th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="(row, i) in form.cost_lines" :key="i">
							<td><Select v-model="row.cost_component" size="sm" :options="componentOptions" /></td>
							<td><input v-model="row.description" type="text" class="form-control form-control-sm" /></td>
							<td><input v-model="row.currency" type="text" class="form-control form-control-sm" /></td>
							<td><MoneyInput v-model="row.amount" :language="user.language" size="sm" /></td>
							<td><MoneyInput v-model="row.amount_uzs" :language="user.language" size="sm" /></td>
							<td class="text-center align-middle">
								<input v-model="row.include_in_landed_cost" type="checkbox" class="form-check-input" :true-value="1" :false-value="0" :disabled="!!row.lcv_ref" />
							</td>
							<td class="text-center align-middle">
								<span v-if="row.lcv_ref" class="badge bg-blue-lt" :title="row.lcv_ref">{{ t("Vouchered") }}</span>
								<button v-else type="button" class="btn btn-ghost-danger btn-icon btn-sm" @click="removeCostLine(i)"><i class="ti ti-trash"></i></button>
							</td>
						</tr>
						<tr v-if="!form.cost_lines.length">
							<td colspan="7" class="text-secondary text-center py-3">{{ t("No cost lines yet.") }}</td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Cost total (cost-visible only) -->
		<div v-if="costVisible" class="card mb-3">
			<div class="card-body d-flex justify-content-between align-items-center">
				<label class="form-label mb-0">{{ t("Goods value (total amount)") }}</label>
				<div style="width: 200px"><MoneyInput v-model="form.total_amount" :currency="form.currency" :language="user.language" /></div>
			</div>
		</div>
	</div>
</template>
