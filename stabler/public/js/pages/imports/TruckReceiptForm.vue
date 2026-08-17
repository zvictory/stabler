<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { importsApi } from "../../api/imports.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import DateInput from "../../components/DateInput.vue";
import MoneyInput from "../../components/MoneyInput.vue";
import StatusBadge from "../../components/StatusBadge.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);
const route = useRoute();
const router = useRouter();
const toast = useToast();

const docName = computed(() => (route.params.name ? String(route.params.name) : null));
const isCreate = computed(() => !docName.value);

const loading = ref(false);
const saving = ref(false);
const error = ref("");

const grnName = ref(route.query.grn ? String(route.query.grn) : "");
const grn = ref(null);
const trucksPending = ref([]);
const selectedTruck = ref(null);
const receiptDocstatus = ref(0);
const purchaseReceipt = ref(null);
const warnings = ref([]);

const form = ref(blankForm());
const items = ref([]);

const CONDITIONS = ["Good", "Damaged", "Rejected"];

function blankForm() {
	const now = new Date();
	const iso = now.toISOString().slice(0, 10);
	const hhmm = now.toTimeString().slice(0, 5);
	return {
		arrival_date: iso,
		arrival_time: hhmm,
		received_by: "",
		temperature_at_arrival: null,
		seal_intact: true,
		seal_number: "",
		packaging_check_passed: true,
		qc_notes: "",
	};
}

const isEditable = computed(() => receiptDocstatus.value === 0);

// null means "not known", which is not the same as zero: a line whose purchase
// order rate we cannot see must never be reported as unpriced.
function numOrNull(v) {
	return v === null || v === undefined || v === "" ? null : Number(v);
}

// Live temperature-in-range indicator against the selected truck's target band.
const tempStatus = computed(() => {
	const v = form.value.temperature_at_arrival;
	const tr = selectedTruck.value;
	if (v === null || v === "" || !tr) return null;
	const min = Number(tr.target_temp_min);
	const max = Number(tr.target_temp_max);
	if (!min && !max) return null;
	return Number(v) >= min && Number(v) <= max ? "ok" : "out";
});

const totals = computed(() => {
	let boxes = 0;
	let kg = 0;
	let good = 0;
	for (const it of items.value) {
		boxes += Number(it.received_boxes || 0);
		kg += Number(it.received_kg || 0);
		if (it.condition === "Good") good += Number(it.received_kg || 0);
	}
	return { boxes, kg, good };
});

// A line enters the purchase receipt only when its Good-condition weight is
// positive; with neither a purchase order price nor a typed rate it would enter
// valued at zero, which the backend refuses to submit. Mirrors
// `receipt_math.unpriced_lines` / `good_qty` so the two sides agree.
function isUnpriced(it) {
	if (it.condition !== "Good" || !(Number(it.received_kg || 0) > 0)) return false;
	if (Number(it.rate || 0) > 0) return false;
	return it.po_rate !== null && !(Number(it.po_rate || 0) > 0);
}

const unpricedLines = computed(() => items.value.filter(isUnpriced));

function buildItemCards(grnItems) {
	return (grnItems || []).map((g) => ({
		grn_item_code: g.item_code,
		item_name: g.item_name || g.item_code,
		expected_total_kg: Number(g.expected_total_kg || 0),
		expected_boxes: Number(g.expected_boxes || 0),
		received_boxes: 0,
		received_kg: 0,
		condition: "Good",
		rate: null,
		po_rate: numOrNull(g.po_rate),
		damaged_boxes: 0,
		rejected_boxes: 0,
		expiry_date: "",
	}));
}

async function loadCreate() {
	if (!grnName.value) {
		error.value = t("No GRN checklist was provided.");
		return;
	}
	grn.value = await importsApi.getGrnChecklist(grnName.value);
	items.value = buildItemCards(grn.value.items);
	trucksPending.value = await importsApi.trucksPendingReceipt(activeCompany.value, grnName.value);
}

async function loadEdit() {
	const d = await importsApi.getTruckReceipt(docName.value);
	grnName.value = d.grn_checklist;
	receiptDocstatus.value = d.docstatus;
	purchaseReceipt.value = d.purchase_receipt;
	form.value = {
		arrival_date: d.arrival_date || blankForm().arrival_date,
		arrival_time: d.arrival_time ? String(d.arrival_time).slice(0, 5) : blankForm().arrival_time,
		received_by: d.received_by || "",
		temperature_at_arrival: d.temperature_at_arrival,
		seal_intact: d.seal_intact,
		seal_number: d.seal_number || "",
		packaging_check_passed: d.packaging_check_passed,
		qc_notes: d.qc_notes || "",
	};
	grn.value = await importsApi.getGrnChecklist(d.grn_checklist);
	// Merge saved receipt lines onto the GRN item cards (expected from GRN).
	const cards = buildItemCards(grn.value.items);
	const byCode = new Map(cards.map((c) => [c.grn_item_code, c]));
	for (const line of d.items || []) {
		const card = byCode.get(line.grn_item_code) || {
			grn_item_code: line.grn_item_code,
			item_name: line.grn_item_code,
			expected_total_kg: 0,
			expected_boxes: 0,
			po_rate: null,
		};
		card.received_boxes = line.received_boxes;
		card.received_kg = line.received_kg;
		card.condition = line.condition || "Good";
		card.rate = numOrNull(line.rate);
		card.po_rate = numOrNull(line.po_rate ?? card.po_rate);
		card.damaged_boxes = line.damaged_boxes;
		card.rejected_boxes = line.rejected_boxes;
		card.expiry_date = line.expiry_date || "";
		byCode.set(line.grn_item_code, card);
	}
	items.value = Array.from(byCode.values());
	if (d.truck) {
		selectedTruck.value = await importsApi.getImportTruck(d.truck);
	}
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		if (isCreate.value) await loadCreate();
		else await loadEdit();
	} catch (err) {
		error.value = err?.message || t("Failed to load the truck receipt.");
	} finally {
		loading.value = false;
	}
}

async function pickTruck(truck) {
	// trucks_pending rows carry the target temp band already.
	selectedTruck.value = truck;
}

function itemsPayload() {
	return items.value
		.filter((it) => Number(it.received_boxes || 0) > 0 || Number(it.received_kg || 0) > 0)
		.map((it) => ({
			grn_item_code: it.grn_item_code,
			received_boxes: Number(it.received_boxes || 0),
			received_kg: Number(it.received_kg || 0),
			condition: it.condition,
			// Optional fallback price — omitted when empty so the purchase order
			// rate stays the normal path.
			rate: numOrNull(it.rate) ?? undefined,
			damaged_boxes: Number(it.damaged_boxes || 0),
			rejected_boxes: Number(it.rejected_boxes || 0),
			expiry_date: it.expiry_date || undefined,
		}));
}

function buildValues() {
	return {
		arrival_date: form.value.arrival_date || undefined,
		arrival_time: form.value.arrival_time || undefined,
		received_by: form.value.received_by || undefined,
		temperature_at_arrival:
			form.value.temperature_at_arrival === "" ? null : form.value.temperature_at_arrival,
		seal_intact: form.value.seal_intact ? 1 : 0,
		seal_number: form.value.seal_number || undefined,
		packaging_check_passed: form.value.packaging_check_passed ? 1 : 0,
		qc_notes: form.value.qc_notes || undefined,
	};
}

function validate() {
	if (isCreate.value && !selectedTruck.value) {
		toast.error(t("Pick a truck to receive."));
		return false;
	}
	if (!itemsPayload().length) {
		toast.error(t("Enter at least one received line."));
		return false;
	}
	return true;
}

async function persist() {
	const creating = isCreate.value;
	let res;
	if (creating) {
		res = await importsApi.createTruckReceipt({
			grn_checklist: grnName.value,
			truck: selectedTruck.value.name,
			values: buildValues(),
			items: itemsPayload(),
		});
	} else {
		res = await importsApi.updateTruckReceipt({
			name: docName.value,
			values: buildValues(),
			items: itemsPayload(),
		});
	}
	// Validate-time notes (unpriced lines, cold chain) come back with the save, so
	// the operator reads them without having to reach for Submit first.
	warnings.value = res?.warnings || [];
	return creating ? res.name : docName.value;
}

async function saveDraft() {
	if (!validate()) return;
	saving.value = true;
	try {
		const name = await persist();
		toast.success(t("Truck receipt saved."));
		if (isCreate.value) {
			router.replace("/imports/truck-receipts/" + name);
		} else {
			await load();
		}
	} catch (err) {
		toast.error(err?.message || t("Save failed."));
	} finally {
		saving.value = false;
	}
}

async function submit() {
	if (!validate()) return;
	saving.value = true;
	warnings.value = [];
	try {
		const name = await persist();
		const res = await importsApi.submitTruckReceipt(name);
		warnings.value = res.warnings || [];
		purchaseReceipt.value = res.purchase_receipt;
		receiptDocstatus.value = res.docstatus;
		toast.success(t("Truck receipt submitted."));
		if (isCreate.value) router.replace("/imports/truck-receipts/" + name);
		else await load();
	} catch (err) {
		toast.error(err?.message || t("Submit failed."));
	} finally {
		saving.value = false;
	}
}

onMounted(load);
watch(docName, load);
</script>

<template>
	<div class="tr-form">
		<div class="d-flex align-items-center mb-3">
			<button type="button" class="btn btn-ghost-secondary btn-icon me-2" @click="router.push(grnName ? '/imports/grn-checklists/' + grnName : '/imports/grn-checklists')">
				<i class="ti ti-arrow-left"></i>
			</button>
			<div>
				<h2 class="page-title mb-0">{{ isCreate ? t("Receive truck") : docName }}</h2>
				<div class="text-secondary small">{{ grnName }}</div>
			</div>
			<div v-if="!isEditable" class="ms-auto">
				<StatusBadge doctype="GRN Checklist" :docstatus="receiptDocstatus" />
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>
		<div v-if="loading" class="text-secondary">{{ t("Loading…") }}</div>

		<template v-if="!loading && !error">
			<!-- Submitted banner -->
			<div v-if="!isEditable" class="alert alert-success">
				<div class="d-flex align-items-center">
					<i class="ti ti-check me-2"></i>
					<span>{{ t("This truck receipt is submitted and can no longer be edited.") }}</span>
				</div>
				<div v-if="purchaseReceipt" class="mt-1">
					{{ t("Purchase receipt") }}:
					<span class="badge bg-blue-lt font-monospace ms-1">{{ purchaseReceipt }}</span>
				</div>
			</div>

			<!-- Warnings from submit -->
			<div v-if="warnings.length" class="alert alert-warning">
				<div class="d-flex justify-content-between">
					<strong>{{ t("Receiving notes") }}</strong>
					<button type="button" class="btn-close" @click="warnings = []"></button>
				</div>
				<ul class="mb-0 mt-1 ps-3">
					<li v-for="(w, i) in warnings" :key="i" class="small">{{ w }}</li>
				</ul>
			</div>

			<!-- Step 1: pick truck (create only) -->
			<div v-if="isCreate && !selectedTruck" class="card mb-3">
				<div class="card-header"><h3 class="card-title">{{ t("Pick the truck to receive") }}</h3></div>
				<div class="card-body">
					<div v-if="!trucksPending.length" class="text-secondary">
						{{ t("No arrived trucks are waiting to be received for this shipment.") }}
					</div>
					<div class="row g-3">
						<div v-for="tr in trucksPending" :key="tr.name" class="col-12 col-md-6">
							<button type="button" class="btn btn-outline-secondary w-100 text-start p-3" style="min-height: 96px" @click="pickTruck(tr)">
								<div class="d-flex justify-content-between align-items-start">
									<div>
										<div class="fw-bold font-monospace">{{ tr.truck_number || tr.name }}</div>
										<div class="text-secondary small">{{ tr.driver_name || "—" }} {{ tr.driver_phone }}</div>
										<div class="text-secondary small">{{ t("Expected") }}: {{ Number(tr.total_kg || 0).toFixed(0) }} {{ t("kg") }} · {{ tr.total_boxes || 0 }} {{ t("boxes") }}</div>
									</div>
									<StatusBadge doctype="Import Truck" :status="tr.status" />
								</div>
							</button>
						</div>
					</div>
				</div>
			</div>

			<template v-if="!isCreate || selectedTruck">
				<!-- Selected truck summary -->
				<div v-if="selectedTruck" class="card mb-3">
					<div class="card-body d-flex align-items-center justify-content-between">
						<div>
							<div class="fw-bold font-monospace">{{ selectedTruck.truck_number || selectedTruck.name }}</div>
							<div class="text-secondary small">
								{{ selectedTruck.driver_name || "—" }} ·
								{{ t("Target") }} {{ Number(selectedTruck.target_temp_min).toFixed(0) }}°C … {{ Number(selectedTruck.target_temp_max).toFixed(0) }}°C
							</div>
						</div>
						<button v-if="isCreate && isEditable" type="button" class="btn btn-ghost-secondary btn-sm" @click="selectedTruck = null">
							{{ t("Change") }}
						</button>
					</div>
				</div>

				<!-- Step 2: arrival -->
				<div class="card mb-3">
					<div class="card-header"><h3 class="card-title">{{ t("Arrival") }}</h3></div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-12 col-md-4">
								<label class="form-label">{{ t("Arrival date") }}</label>
								<DateInput v-model="form.arrival_date" size="lg" :disabled="!isEditable" />
							</div>
							<div class="col-6 col-md-4">
								<label class="form-label">{{ t("Arrival time") }}</label>
								<input v-model="form.arrival_time" type="time" class="form-control form-control-lg" :disabled="!isEditable" style="min-height: 48px" />
							</div>
							<div class="col-12 col-md-4">
								<label class="form-label">{{ t("Received by") }}</label>
								<input v-model="form.received_by" type="text" class="form-control form-control-lg" :disabled="!isEditable" style="min-height: 48px" />
							</div>
						</div>
					</div>
				</div>

				<!-- Step 3: QC panel -->
				<div class="card mb-3">
					<div class="card-header"><h3 class="card-title">{{ t("Quality control") }}</h3></div>
					<div class="card-body">
						<div class="row g-3">
							<div class="col-12 col-md-6">
								<label class="form-label">{{ t("Temperature at arrival (°C)") }}</label>
								<div class="input-group input-group-lg">
									<input
										v-model.number="form.temperature_at_arrival"
										type="number"
										inputmode="decimal"
										step="0.1"
										class="form-control"
										:disabled="!isEditable"
										style="min-height: 48px"
									/>
									<span v-if="tempStatus === 'ok'" class="input-group-text bg-green-lt text-green"><i class="ti ti-check"></i></span>
									<span v-else-if="tempStatus === 'out'" class="input-group-text bg-red-lt text-red"><i class="ti ti-alert-triangle"></i></span>
								</div>
								<div v-if="tempStatus === 'out'" class="text-danger small mt-1">
									{{ t("Out of the target range — a QC note is required to save.") }}
								</div>
							</div>
							<div class="col-12 col-md-6">
								<label class="form-label">{{ t("Seal number") }}</label>
								<input v-model="form.seal_number" type="text" class="form-control form-control-lg" :disabled="!isEditable" style="min-height: 48px" />
							</div>
							<div class="col-6">
								<button type="button" class="btn w-100" :class="form.seal_intact ? 'btn-success' : 'btn-outline-danger'" style="min-height: 48px" :disabled="!isEditable" @click="form.seal_intact = !form.seal_intact">
									<i class="ti me-1" :class="form.seal_intact ? 'ti-lock' : 'ti-lock-open'"></i>
									{{ form.seal_intact ? t("Seal intact") : t("Seal broken") }}
								</button>
							</div>
							<div class="col-6">
								<button type="button" class="btn w-100" :class="form.packaging_check_passed ? 'btn-success' : 'btn-outline-danger'" style="min-height: 48px" :disabled="!isEditable" @click="form.packaging_check_passed = !form.packaging_check_passed">
									<i class="ti me-1" :class="form.packaging_check_passed ? 'ti-package' : 'ti-package-off'"></i>
									{{ form.packaging_check_passed ? t("Packaging OK") : t("Packaging damaged") }}
								</button>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("QC notes") }}</label>
								<textarea v-model="form.qc_notes" class="form-control" rows="2" :disabled="!isEditable"></textarea>
							</div>
						</div>
					</div>
				</div>

				<!-- Step 4: items -->
				<div class="card mb-3">
					<div class="card-header"><h3 class="card-title">{{ t("Received items") }}</h3></div>
					<div class="card-body">
						<!-- Unpriced lines, surfaced while editing — submit refuses them. -->
						<div v-if="unpricedLines.length" class="alert alert-warning">
							<div class="d-flex align-items-center">
								<i class="ti ti-alert-triangle me-2"></i>
								<strong>{{ t("Lines with no price") }}</strong>
							</div>
							<div class="small mt-1">
								{{ t("No purchase order prices these items and no rate was entered, so they would enter stock valued at zero. Enter a rate on each line below.") }}
							</div>
							<ul class="mb-0 mt-1 ps-3">
								<li v-for="u in unpricedLines" :key="u.grn_item_code" class="small">{{ u.item_name }}</li>
							</ul>
						</div>
						<div v-for="it in items" :key="it.grn_item_code" class="border rounded p-3 mb-3" :class="{ 'border-danger': isUnpriced(it) }">
							<div class="d-flex justify-content-between align-items-center mb-2">
								<div class="fw-bold">{{ it.item_name }}</div>
								<div class="text-secondary small">{{ t("Expected") }}: {{ Number(it.expected_total_kg || 0).toFixed(0) }} {{ t("kg") }}</div>
							</div>
							<div class="row g-2">
								<div class="col-6">
									<label class="form-label small">{{ t("Received boxes") }}</label>
									<input v-model.number="it.received_boxes" type="number" inputmode="numeric" min="0" class="form-control form-control-lg" :disabled="!isEditable" style="min-height: 48px" />
								</div>
								<div class="col-6">
									<label class="form-label small">{{ t("Received kg") }}</label>
									<input v-model.number="it.received_kg" type="number" inputmode="decimal" step="0.1" min="0" class="form-control form-control-lg" :disabled="!isEditable" style="min-height: 48px" />
								</div>
							</div>
							<div class="btn-group w-100 mt-2" role="group">
								<button
									v-for="c in CONDITIONS"
									:key="c"
									type="button"
									class="btn"
									:class="it.condition === c ? (c === 'Good' ? 'btn-success' : c === 'Damaged' ? 'btn-warning' : 'btn-danger') : 'btn-outline-secondary'"
									style="min-height: 48px"
									:disabled="!isEditable"
									@click="it.condition = c"
								>
									{{ t(c) }}
								</button>
							</div>
							<!-- Only Good weight is priced into the purchase receipt. -->
							<div v-if="it.condition === 'Good'" class="mt-2">
								<label class="form-label small">{{ t("Rate (USD/kg)") }}</label>
								<MoneyInput
										v-model="it.rate"
										:language="user.language"
										:max-fraction-digits="4"
										hide-currency
										size="sm"
										:disabled="!isEditable"
									/>
								<div v-if="isUnpriced(it)" class="text-danger small mt-1">
									{{ t("No purchase order price for this item — enter a rate to submit.") }}
								</div>
								<div v-else-if="Number(it.po_rate) > 0 && !(Number(it.rate) > 0)" class="text-secondary small mt-1">
									{{ t("Purchase order price") }}:
									<span class="font-monospace">{{ Number(it.po_rate).toFixed(4) }}</span>
								</div>
							</div>
							<div v-if="it.condition !== 'Good'" class="row g-2 mt-1">
								<div class="col-6">
									<label class="form-label small">{{ t("Damaged boxes") }}</label>
									<input v-model.number="it.damaged_boxes" type="number" inputmode="numeric" min="0" class="form-control" :disabled="!isEditable" />
								</div>
								<div class="col-6">
									<label class="form-label small">{{ t("Rejected boxes") }}</label>
									<input v-model.number="it.rejected_boxes" type="number" inputmode="numeric" min="0" class="form-control" :disabled="!isEditable" />
								</div>
							</div>
							<div class="mt-2">
								<label class="form-label small">{{ t("Expiry date") }}</label>
								<DateInput v-model="it.expiry_date" :disabled="!isEditable" />
							</div>
						</div>
						<div v-if="!items.length" class="text-secondary text-center py-3">{{ t("This GRN has no item lines.") }}</div>
					</div>
				</div>
			</template>
		</template>

		<!-- Step 5+6: sticky running totals + actions -->
		<div v-if="!loading && !error && (!isCreate || selectedTruck)" class="tr-actionbar card">
			<div class="card-body d-flex align-items-center flex-wrap gap-3">
				<div class="d-flex gap-3">
					<div>
						<div class="text-secondary small">{{ t("Boxes") }}</div>
						<div class="h3 mb-0 font-monospace">{{ totals.boxes }}</div>
					</div>
					<div>
						<div class="text-secondary small">{{ t("Total kg") }}</div>
						<div class="h3 mb-0 font-monospace">{{ totals.kg.toFixed(0) }}</div>
					</div>
					<div>
						<div class="text-secondary small">{{ t("Good kg") }}</div>
						<div class="h3 mb-0 font-monospace text-success">{{ totals.good.toFixed(0) }}</div>
					</div>
				</div>
				<div v-if="isEditable" class="ms-auto d-flex align-items-center gap-2">
					<!-- Mirrors the backend: a draft with unpriced lines saves, never submits. -->
					<div v-if="unpricedLines.length" class="text-danger small">
						<i class="ti ti-alert-triangle me-1"></i>{{ t("Enter a rate on the unpriced lines to submit.") }}
					</div>
					<button type="button" class="btn btn-outline-secondary btn-lg" :disabled="saving" style="min-height: 48px" @click="saveDraft">
						<i class="ti ti-device-floppy me-1"></i>{{ t("Save draft") }}
					</button>
					<button type="button" class="btn btn-primary btn-lg" :disabled="saving || unpricedLines.length > 0" style="min-height: 48px" @click="submit">
						<i class="ti ti-checkbox me-1"></i>{{ t("Submit receipt") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.tr-actionbar {
	position: sticky;
	bottom: 0;
	z-index: 5;
	box-shadow: 0 -2px 12px rgba(0, 0, 0, 0.08);
	margin-bottom: 0;
}
</style>
