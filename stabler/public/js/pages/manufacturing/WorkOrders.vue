<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { workOrderProgress } from "../../composables/workOrderProgress.js";
import { materialReadiness, stockKey } from "../../composables/materialReadiness.js";
import { halfAssigned, roleLabel } from "../../composables/workOrderRoles.js";
import { useOperatorOptions } from "../../composables/workOrderOperators.js";
import { useWorkOrderStatus } from "../../composables/workOrderStatus.js";
import { formatDateTime, todayIso} from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";
import Select from "../../components/Select.vue";
import ManufacturingOperatorBoard from "./ManufacturingOperatorBoard.vue";

const router = useRouter();
const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const { operatorList, operatorSelectOptions, loadOperators } = useOperatorOptions();

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");
const statusFilter = ref("");

// Labels and badge colours are shared with the detail page — the two screens
// had drifted into disagreeing about what colour a Draft order is.
const { statusLabel, statusBadge, statusOptions } = useWorkOrderStatus();

const progress = (r) => workOrderProgress(r);

const formatQty = (n, uom) => {
	const v = Number(n || 0);
	return `${v.toLocaleString(user.value.language || "en", { maximumFractionDigits: 3 })} ${uom || ""}`.trim();
};


async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.manufacturing.list_work_orders", {
			company: activeCompany.value,
			search: search.value,
			status: statusFilter.value || undefined,
			limit: 100,
		});
		await loadStock();
	} catch (err) {
		error.value = err?.message || "Failed to load work orders.";
	} finally {
		loading.value = false;
	}
}

// Shelf stock for every source warehouse the page's materials draw from, keyed
// by `stockKey()`. One call per distinct warehouse rather than per row: a
// hundred orders on an ice-cream floor draw from a handful of stores, so this
// is two or three requests, not a hundred.
const stock = ref({});

async function loadStock() {
	const byWarehouse = new Map();
	for (const row of rows.value) {
		for (const line of row.required_items || []) {
			if (!line.source_warehouse || !line.item_code) continue;
			if (!byWarehouse.has(line.source_warehouse)) byWarehouse.set(line.source_warehouse, new Set());
			byWarehouse.get(line.source_warehouse).add(line.item_code);
		}
	}
	const next = {};
	await Promise.all(
		[...byWarehouse].map(async ([warehouse, codes]) => {
			try {
				const levels = await call("stabler.api.inventory.get_items_stock", {
					warehouse,
					item_codes: JSON.stringify([...codes]),
				});
				for (const [item, qty] of Object.entries(levels || {})) {
					next[stockKey(warehouse, item)] = qty;
				}
			} catch {
				// A warehouse that would not answer leaves its items absent, and
				// `materialReadiness` reports "unknown" for them rather than
				// inventing a level. Failing the whole list over one store would
				// hide the nineteen rows that are fine.
			}
		}),
	);
	stock.value = next;
}

const readiness = (r) => materialReadiness(r, stock.value);

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}

onMounted(load);
watch(activeCompany, load);
watch(statusFilter, load);

// ----- Assign operators to a whole selection (manager only) -----
// A shift lead sets one pouring/packing pair per line per shift, so the gesture
// that matches the floor is "these fifteen orders, these two people". Two things
// separate it from the single-order panel above:
//
//   * a role left empty here is left alone, not cleared — silence about packing
//     must not strip fifteen packers;
//   * the response has two halves and both are shown. `skipped` is why a finished
//     order, a foreign id or a name that would hold both roles did not change,
//     and hiding it makes "14 of 15" look exactly like "15 of 15".
const actionError = ref("");

const selected = ref(new Set());
const bulkOpen = ref(false);
const bulkBusy = ref(false);
const bulkOperator = ref("");
const bulkPackagingOperator = ref("");
const bulkSkipped = ref([]);

const allSelected = computed(() => rows.value.length > 0 && selected.value.size === rows.value.length);

function toggleRow(name) {
	// Reassigning the ref is what makes Vue see the change; mutating a Set in place
	// does not trigger reactivity.
	const next = new Set(selected.value);
	next.has(name) ? next.delete(name) : next.add(name);
	selected.value = next;
}

function toggleAll() {
	selected.value = allSelected.value ? new Set() : new Set(rows.value.map((r) => r.name));
}

async function openBulk() {
	bulkOpen.value = true;
	bulkSkipped.value = [];
	actionError.value = "";
	bulkOperator.value = "";
	bulkPackagingOperator.value = "";
	const err = await loadOperators(activeCompany.value);
	if (err) actionError.value = err;
}

async function confirmBulk() {
	bulkBusy.value = true;
	try {
		const res = await call("stabler.api.manufacturing.assign_work_order_operators_bulk", {
			company: activeCompany.value,
			names: JSON.stringify([...selected.value]),
			operator: bulkOperator.value || "",
			packaging_operator: bulkPackagingOperator.value || "",
		});
		const assigned = res?.assigned || [];
		bulkSkipped.value = res?.skipped || [];
		// Only the written ones leave the selection. The refused ones stay ticked so
		// the manager can act on the reason without re-finding them in the list.
		const next = new Set(selected.value);
		assigned.forEach((name) => next.delete(name));
		selected.value = next;
		if (!bulkSkipped.value.length) bulkOpen.value = false;
		await load();
	} catch (err) {
		actionError.value = err?.message || "Assign failed.";
	} finally {
		bulkBusy.value = false;
	}
}

// ----- Create modal -----
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const itemOptions = ref([]);
const bomOptions = ref([]);
const warehouseOptions = ref([]);
const optionsLoaded = ref(false);

function blankWO() {
	return {
		production_item: "",
		bom_no: "",
		qty: 1,
		planned_start_date: todayIso(),
		fg_warehouse: "",
		wip_warehouse: "",
		source_warehouse: "",
		operator: "",
		packaging_operator: "",
	};
}
const form = ref(blankWO());

// BOM preview: components scaled to the WO qty, shown read-only in the modal.
const bomPreview = ref(null);
const bomPreviewLoading = ref(false);

function fmtQty(v) {
	const n = Number(v) || 0;
	return (Number.isInteger(n) ? n : Number(n.toFixed(3))).toLocaleString("ru-RU");
}

async function loadBomPreview() {
	const bom = form.value.bom_no;
	if (!bom) {
		bomPreview.value = null;
		return;
	}
	bomPreviewLoading.value = true;
	try {
		bomPreview.value = await call("stabler.api.manufacturing.bom_materials", {
			company: activeCompany.value,
			bom_no: bom,
			qty: form.value.qty || 1,
		});
	} catch (err) {
		bomPreview.value = null;
		submitError.value = err?.message || "Failed to load BOM materials.";
	} finally {
		bomPreviewLoading.value = false;
	}
}

watch(
	() => [form.value.bom_no, form.value.qty],
	() => {
		if (createOpen.value) loadBomPreview();
	},
);

const bomSelectOptions = computed(() => [
	{ value: "" },
	...bomOptions.value.map((b) => ({
		value: b.name,
		name: b.name,
		is_default: b.is_default,
		docstatus: b.docstatus,
	})),
]);

async function loadOptions() {
	if (optionsLoaded.value) return;
	try {
		const [items, whs, ops] = await Promise.all([
			call("stabler.api.manufacturing.manufacturable_items", {
				company: activeCompany.value,
				limit: 500,
			}),
			call("stabler.api.inventory.list_warehouses", { company: activeCompany.value }),
			operatorList.value.length
				? Promise.resolve(operatorList.value)
				: call("stabler.api.manufacturing.list_operators", { company: activeCompany.value }),
		]);
		itemOptions.value = items || [];
		warehouseOptions.value = (whs || []).filter((w) => !w.is_group);
		operatorList.value = ops || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load options.";
	}
}

async function onProductionItemChange() {
	form.value.bom_no = "";
	if (!form.value.production_item) {
		bomOptions.value = [];
		return;
	}
	try {
		bomOptions.value = await call("stabler.api.manufacturing.list_boms", {
			company: activeCompany.value,
			item: form.value.production_item,
			limit: 50,
		});
		const def = bomOptions.value.find((b) => b.is_default && b.docstatus === 1);
		if (def) form.value.bom_no = def.name;
	} catch (err) {
		submitError.value = err?.message || "Failed to load BOMs.";
	}
}

function openCreate() {
	form.value = blankWO();
	bomOptions.value = [];
	bomPreview.value = null;
	submitError.value = "";
	createOpen.value = true;
	loadOptions();
}
function closeCreate() {
	createOpen.value = false;
}

async function saveWO(submitAfter) {
	submitError.value = "";
	if (!form.value.production_item) {
		submitError.value = t("Pick a finished-good item.");
		return;
	}
	if (Number(form.value.qty) <= 0) {
		submitError.value = t("Quantity must be positive.");
		return;
	}
	submitting.value = true;
	try {
		const res = await call("stabler.api.manufacturing.create_work_order", {
			company: activeCompany.value,
			production_item: form.value.production_item,
			bom_no: form.value.bom_no || undefined,
			qty: form.value.qty,
			planned_start_date: form.value.planned_start_date || undefined,
			fg_warehouse: form.value.fg_warehouse || undefined,
			wip_warehouse: form.value.wip_warehouse || undefined,
			source_warehouse: form.value.source_warehouse || undefined,
			operator: form.value.operator || undefined,
			packaging_operator: form.value.packaging_operator || undefined,
			submit: submitAfter ? 1 : 0,
		});
		closeCreate();
		await load();
		if (res?.name) router.push({ name: "manufacturing-work-order", params: { name: res.name } });
	} catch (err) {
		submitError.value = err?.message || "Save failed.";
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<!-- Operator view: simplified board (server already filters to own WOs) -->
	<ManufacturingOperatorBoard v-if="!session.isMfgManager" />

	<!-- Manager view: full table + create. The detail is its own page. -->
	<template v-else>
		<div class="card mb-3">
			<div class="card-body">
				<div class="row g-2 align-items-center">
					<div class="col-md-5">
						<div class="input-icon">
							<span class="input-icon-addon"><i class="ti ti-search"></i></span>
							<input
								v-model="search"
								@input="onSearchInput"
								type="search"
								class="form-control"
								:placeholder="t('Search work orders…')"
							/>
						</div>
					</div>
					<div class="col-md-3">
						<Select v-model="statusFilter" :options="statusOptions" />
					</div>
					<div class="col-md-4 d-flex justify-content-md-end gap-2">
						<button
							type="button"
							class="btn btn-outline-primary"
							:disabled="!selected.size"
							@click="openBulk"
						>
							<i class="ti ti-users me-1"></i>{{ t("Assign operators") }}
							<span v-if="selected.size" class="badge bg-primary ms-1">{{ selected.size }}</span>
						</button>
						<button type="button" class="btn btn-ghost-secondary" @click="load">
							<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
						</button>
						<button type="button" class="btn btn-primary" @click="openCreate">
							<i class="ti ti-plus me-1"></i>{{ t("New Work Order") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<div v-if="error" class="alert alert-danger">{{ error }}</div>

		<EmptyState
			v-if="!loading && !error && !rows.length"
			icon="ti-tool"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No work orders')"
			:subtitle="t('Create a Work Order to plan and track production runs against a BOM.')"
		/>

		<div v-else-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>

		<div v-else class="card">
			<div class="table-responsive">
				<table class="table table-vcenter card-table table-hover">
					<thead>
						<tr>
							<th class="w-1">
								<input
									type="checkbox"
									class="form-check-input m-0"
									:checked="allSelected"
									:aria-label="t('Select all')"
									@change="toggleAll"
								/>
							</th>
							<th>{{ t("Work Order") }}</th>
							<th>{{ t("Finished good") }}</th>
							<th>{{ t("Operators") }}</th>
							<th style="width: 230px">{{ t("Progress") }}</th>
							<th style="width: 180px">{{ t("Materials") }}</th>
							<th>{{ t("Status") }}</th>
						</tr>
					</thead>
					<tbody>
						<tr v-for="r in rows" :key="r.name" class="cursor-pointer" @click="router.push({ name: 'manufacturing-work-order', params: { name: r.name } })">
							<!-- The row opens the detail page, so the checkbox has to stop the
								 click it sits inside: without this, ticking five orders opens
								 five panels and the last one covers the toolbar. -->
							<td class="wo-select w-1" @click.stop>
								<input
									type="checkbox"
									class="form-check-input m-0"
									:checked="selected.has(r.name)"
									:aria-label="t('Select')"
									@change="toggleRow(r.name)"
								/>
							</td>
							<td>
								<div class="font-monospace small">{{ r.name }}</div>
								<div class="small text-secondary">{{ formatDateTime(r.planned_start_date) }}</div>
							</td>
							<td>
								<div class="fw-semibold">{{ r.item_name || r.production_item }}</div>
								<div class="small text-secondary font-monospace">{{ r.production_item }}</div>
							</td>
							<!-- Both roles, labelled. A half-assigned order stops at the transfer,
								 so the empty half is red and says so: a grey "—" reads as "no data
								 here", which is the one thing it is not. -->
							<td class="wo-operators small text-secondary">
								<div class="d-flex align-items-center gap-1">
									<span class="badge bg-azure-lt">{{ roleLabel("Production") }}</span>
									<span v-if="r.operator">{{ r.operator }}</span>
									<span v-else :class="halfAssigned(r) ? 'text-danger fw-bold' : 'text-muted'">
										{{ halfAssigned(r) ? t("not assigned") : "—" }}
									</span>
								</div>
								<div class="d-flex align-items-center gap-1 mt-1">
									<span class="badge bg-lime-lt">{{ roleLabel("Packaging") }}</span>
									<span v-if="r.packaging_operator">{{ r.packaging_operator }}</span>
									<span v-else :class="halfAssigned(r) ? 'text-danger fw-bold' : 'text-muted'">
										{{ halfAssigned(r) ? t("not assigned") : "—" }}
									</span>
								</div>
							</td>
							<td>
								<div class="d-flex align-items-baseline gap-2">
									<span class="font-monospace fw-semibold">{{ formatQty(r.produced_qty) }}</span>
									<span class="text-secondary small font-monospace">/ {{ formatQty(r.qty) }}</span>
									<span
										class="ms-auto small fw-semibold"
										:class="progress(r).donePct > 100 ? 'text-orange' : 'text-blue'"
									>
										{{ progress(r).donePct }}%
									</span>
								</div>
								<div class="progress progress-sm mt-1">
									<div
										class="progress-bar"
										:class="progress(r).donePct > 100 ? 'bg-orange' : 'bg-primary'"
										:style="{ width: progress(r).barPct + '%' }"
									></div>
								</div>
								<div class="text-secondary mt-1" style="font-size: 11px">
									<template v-if="progress(r).nothingTransferred">
										{{ t("materials not transferred") }}
									</template>
									<template v-else>
										{{ t("transferred") }} {{ progress(r).transferredPct }}%
									</template>
								</div>
							</td>
							<td>
								<span
									v-if="readiness(r).state === 'in_place'"
									class="badge bg-green-lt"
									:title="t('All materials are already in WIP.')"
								>
									{{ t("in workshop") }}
								</span>
								<span v-else-if="readiness(r).state === 'ready'" class="badge bg-green-lt">
									<template v-if="readiness(r).unitsCovered !== null">
										{{ t("enough for {0}", [formatQty(readiness(r).unitsCovered)]) }}
									</template>
									<template v-else>{{ t("materials available") }}</template>
								</span>
								<span v-else-if="readiness(r).state === 'short'" class="badge bg-orange-lt">
									{{ t("short {0} item(s)", [readiness(r).shortCount]) }}
								</span>
								<span v-else class="text-secondary small">—</span>
							</td>
							<td><span class="badge" :class="statusBadge(r.status)">{{ statusLabel(r.status) }}</span></td>
						</tr>
					</tbody>
				</table>
			</div>
		</div>

		<!-- Bulk assign modal -->

		<div v-if="bulkOpen" class="modal-backdrop fade show" @click="bulkOpen = false"></div>
		<div v-if="bulkOpen" class="modal fade show d-block" tabindex="-1" style="background: transparent">
			<div class="modal-dialog">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("Assign operators") }}</h5>
						<button type="button" class="btn-close" @click="bulkOpen = false"></button>
					</div>
					<div class="modal-body">
						<p class="text-secondary small">
							{{ t("Selected work orders: {0}", [selected.size]) }}
						</p>
						<!-- Unlike the detail page, where an empty box means "nobody is
							 assigned", an empty box here means "leave this role as it is".
							 That is the whole difference between the two screens, so it is
							 said in the dialog and not only in the code. -->
						<div class="mb-2">
							<label class="form-label small mb-1">{{ roleLabel("Production") }}</label>
							<Select v-model="bulkOperator" :options="operatorSelectOptions" />
						</div>
						<div class="mb-2">
							<label class="form-label small mb-1">{{ roleLabel("Packaging") }}</label>
							<Select v-model="bulkPackagingOperator" :options="operatorSelectOptions" />
						</div>
						<div class="form-hint">{{ t("A role left empty keeps the operator already assigned.") }}</div>

						<!-- The refused-orders list below cannot carry this: a failed call
							 returns no per-order verdict, so it would report nothing at all. -->
						<div v-if="actionError" class="alert alert-danger mt-3 mb-0">{{ actionError }}</div>

						<div v-if="bulkSkipped.length" class="alert alert-warning mt-3 mb-0">
							<div class="fw-bold">{{ t("Not changed:") }}</div>
							<ul class="mb-0 ps-3 small">
								<li v-for="s in bulkSkipped" :key="s.name">
									<span class="font-monospace">{{ s.name }}</span> — {{ s.reason }}
								</li>
							</ul>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-ghost-secondary" @click="bulkOpen = false">
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary"
							:disabled="bulkBusy || !selected.size || (!bulkOperator && !bulkPackagingOperator)"
							@click="confirmBulk"
						>
							{{ t("Assign") }}
						</button>
					</div>
				</div>
			</div>
		</div>

		<!-- Create modal -->
		<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
		<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" style="background: transparent">
			<div class="modal-dialog modal-lg">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">{{ t("New Work Order") }}</h5>
						<button type="button" class="btn-close" @click="closeCreate"></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

						<div class="row g-2 mb-3">
							<div class="col-md-7">
								<label class="form-label">{{ t("Finished good") }}</label>
								<Select
									v-model="form.production_item"
									:options="itemOptions"
									value-key="item_code"
									placeholder="—"
									@change="onProductionItemChange"
								>
									<template #option="{ option }">
										{{ option.item_name }} ({{ option.item_code }})
									</template>
									<template #selected="{ option }">
										{{ option.item_name }} ({{ option.item_code }})
									</template>
								</Select>
								<div v-if="!itemOptions.length && optionsLoaded" class="form-hint text-warning">
									{{ t("No items with submitted active BOMs yet — create one first.") }}
								</div>
							</div>
							<div class="col-md-5">
								<label class="form-label">{{ t("BOM") }}</label>
								<Select
									v-model="form.bom_no"
									:options="bomSelectOptions"
									:disabled="!bomOptions.length"
								>
									<template #option="{ option }">
										<template v-if="option.value === ''">{{ t("Default") }}</template>
										<template v-else>{{ option.name }}{{ option.is_default ? " · default" : "" }}{{ option.docstatus !== 1 ? " (draft)" : "" }}</template>
									</template>
									<template #selected="{ option }">
										<template v-if="option.value === ''">{{ t("Default") }}</template>
										<template v-else>{{ option.name }}{{ option.is_default ? " · default" : "" }}{{ option.docstatus !== 1 ? " (draft)" : "" }}</template>
									</template>
								</Select>
							</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-md-4">
								<label class="form-label">{{ t("Quantity") }}</label>
								<input v-model.number="form.qty" type="number" min="0.001" step="0.001" inputmode="decimal" class="form-control" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Planned start") }}</label>
								<DateInput v-model="form.planned_start_date" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Production operator") }}</label>
								<Select v-model="form.operator" :options="operatorList" value-key="name" placeholder="—">
									<template #option="{ option }">{{ option.full_name || option.name }}</template>
									<template #selected="{ option }">{{ option.full_name || option.name }}</template>
								</Select>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Packaging operator") }}</label>
								<Select v-model="form.packaging_operator" :options="operatorList" value-key="name" placeholder="—">
									<template #option="{ option }">{{ option.full_name || option.name }}</template>
									<template #selected="{ option }">{{ option.full_name || option.name }}</template>
								</Select>
							</div>
						</div>

						<!-- BOM materials preview: scaled to the WO qty, read-only -->
						<div v-if="form.bom_no" class="mb-3">
							<label class="form-label mb-1">
								{{ t("BOM materials") }}
								<span class="text-secondary fw-normal">· {{ fmtQty(form.qty) }} {{ bomPreview && bomPreview.uom ? bomPreview.uom : "" }}</span>
							</label>
							<div v-if="bomPreviewLoading" class="text-secondary small py-2">{{ t("Loading…") }}</div>
							<div v-else-if="bomPreview && bomPreview.items.length" class="table-responsive border rounded">
								<table class="table table-sm align-middle mb-0">
									<thead>
										<tr>
											<th>{{ t("Material") }}</th>
											<th class="text-end">{{ t("Quantity") }}</th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="(it, i) in bomPreview.items" :key="i">
											<td>
												{{ it.item_name || it.item_code }}
												<div class="text-secondary small">{{ it.item_code }}</div>
											</td>
											<td class="text-end font-monospace text-nowrap">{{ fmtQty(it.qty) }} {{ it.uom }}</td>
										</tr>
									</tbody>
								</table>
							</div>
							<div v-else-if="bomPreview" class="text-secondary small py-2">{{ t("This BOM has no materials.") }}</div>
						</div>

						<div class="row g-2 mb-3">
							<div class="col-md-4">
								<label class="form-label">{{ t("Source warehouse") }}</label>
								<Select
									v-model="form.source_warehouse"
									:options="warehouseOptions"
									value-key="name"
									label-key="name"
									placeholder="—"
								/>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("WIP warehouse") }}</label>
								<Select
									v-model="form.wip_warehouse"
									:options="warehouseOptions"
									value-key="name"
									label-key="name"
									placeholder="—"
								/>
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Finished-goods warehouse") }}</label>
								<Select
									v-model="form.fg_warehouse"
									:options="warehouseOptions"
									value-key="name"
									label-key="name"
									placeholder="—"
								/>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button type="button" class="btn btn-link link-secondary" @click="closeCreate">{{ t("Cancel") }}</button>
						<button type="button" class="btn btn-outline-primary" :disabled="submitting" @click="saveWO(false)">
							<i class="ti ti-device-floppy me-1"></i>{{ t("Save as draft") }}
						</button>
						<button type="button" class="btn btn-primary" :disabled="submitting" @click="saveWO(true)">
							<i class="ti ti-check me-1"></i>{{ t("Save and submit") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>

<style scoped>
.cursor-pointer {
	cursor: pointer;
}
</style>
