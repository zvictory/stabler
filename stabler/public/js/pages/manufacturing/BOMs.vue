<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import { t } from "../../composables/i18n.js";
import MoneyInput from "../../components/MoneyInput.vue";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);
const money = (v, ccy) => formatMoney(v, ccy || currency.value, user.value.language);
const formatQty = (n, uom) => {
	const v = Number(n || 0);
	return `${v.toLocaleString(user.value.language || "en", { maximumFractionDigits: 3 })} ${uom || ""}`.trim();
};

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.manufacturing.list_boms", {
			company: activeCompany.value,
			search: search.value,
			limit: 100,
		});
	} catch (err) {
		error.value = err?.message || "Failed to load BOMs.";
	} finally {
		loading.value = false;
	}
}

let searchTimer = null;
function onSearchInput() {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 250);
}

onMounted(load);
watch(activeCompany, load);

// ----- Detail drawer -----
const detailOpen = ref(false);
const detailLoading = ref(false);
const detail = ref(null);

async function openDetail(name) {
	detailOpen.value = true;
	detailLoading.value = true;
	detail.value = null;
	try {
		detail.value = await call("stabler.api.manufacturing.bom_detail", { name });
	} catch (err) {
		detail.value = { error: err?.message || "Failed to load." };
	} finally {
		detailLoading.value = false;
	}
}
function closeDetail() {
	detailOpen.value = false;
	detail.value = null;
}

async function submitBom(name) {
	if (!confirm(t("Submit this BOM? You won't be able to edit it after."))) return;
	try {
		await call("stabler.api.manufacturing.submit_bom", { name });
		await openDetail(name);
		await load();
	} catch (err) {
		alert(err?.message || "Submit failed.");
	}
}

async function cancelBom(name) {
	if (!confirm(t("Cancel this submitted BOM?"))) return;
	try {
		await call("stabler.api.manufacturing.cancel_bom", { name });
		await openDetail(name);
		await load();
	} catch (err) {
		alert(err?.message || "Cancel failed.");
	}
}

// ----- Create modal -----
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const itemOptions = ref([]);
const optionsLoaded = ref(false);

function blankBom() {
	return {
		item: "",
		quantity: 1,
		uom: "",
		is_default: false,
		items: [{ item_code: "", qty: 1, uom: "", rate: null }],
	};
}
const form = ref(blankBom());

async function loadOptions() {
	if (optionsLoaded.value) return;
	try {
		itemOptions.value = await call("stabler.api.inventory.list_items", { limit: 500 });
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load items.";
	}
}

function openCreate() {
	form.value = blankBom();
	submitError.value = "";
	createOpen.value = true;
	loadOptions();
}
function closeCreate() {
	createOpen.value = false;
}
function addLine() {
	form.value.items.push({ item_code: "", qty: 1, uom: "", rate: null });
}
function removeLine(i) {
	form.value.items.splice(i, 1);
	if (!form.value.items.length) addLine();
}

function onFgItemChange() {
	const it = itemOptions.value.find((o) => o.name === form.value.item);
	if (it) form.value.uom = it.stock_uom || form.value.uom;
}

function onLineItemChange(line) {
	const it = itemOptions.value.find((o) => o.name === line.item_code);
	if (it && !line.uom) line.uom = it.stock_uom || "";
}

async function saveBom(submitAfter) {
	submitError.value = "";
	if (!form.value.item) {
		submitError.value = t("Pick a finished-good item.");
		return;
	}
	const cleanLines = form.value.items.filter((l) => l.item_code && Number(l.qty) > 0);
	if (!cleanLines.length) {
		submitError.value = t("Add at least one raw material line.");
		return;
	}
	submitting.value = true;
	try {
		const res = await call("stabler.api.manufacturing.create_bom", {
			company: activeCompany.value,
			item: form.value.item,
			quantity: form.value.quantity,
			uom: form.value.uom || undefined,
			is_default: form.value.is_default ? 1 : 0,
			items: cleanLines,
			submit: submitAfter ? 1 : 0,
		});
		closeCreate();
		await load();
		if (res?.name) openDetail(res.name);
	} catch (err) {
		submitError.value = err?.message || "Save failed.";
	} finally {
		submitting.value = false;
	}
}
</script>

<template>
	<div class="card mb-3">
		<div class="card-body">
			<div class="row g-2 align-items-center">
				<div class="col-md-6">
					<div class="input-icon">
						<span class="input-icon-addon"><i class="ti ti-search"></i></span>
						<input
							v-model="search"
							@input="onSearchInput"
							type="search"
							class="form-control"
							:placeholder="t('Search BOMs or finished goods…')"
						/>
					</div>
				</div>
				<div class="col-md-6 d-flex justify-content-md-end gap-2">
					<button type="button" class="btn btn-ghost-secondary" @click="load">
						<i class="ti ti-refresh me-1"></i>{{ t("Refresh") }}
					</button>
					<button type="button" class="btn btn-primary" @click="openCreate">
						<i class="ti ti-plus me-1"></i>{{ t("New BOM") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<div v-if="error" class="alert alert-danger">{{ error }}</div>

	<EmptyState
		v-if="!loading && !error && !rows.length"
		icon="ti-list-tree"
		accentIcon="ti-plus"
		tone="primary"
		:title="t('No BOMs yet')"
		:subtitle="t('Create a Bill of Materials to define what raw materials go into a finished good.')"
	/>

	<div v-else-if="loading" class="card-body text-center py-5">
		<div class="spinner-border text-primary"></div>
	</div>

	<div v-else class="card">
		<div class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("BOM") }}</th>
						<th>{{ t("Finished good") }}</th>
						<th class="text-end">{{ t("Quantity") }}</th>
						<th class="text-end">{{ t("Total cost") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name" class="cursor-pointer" @click="openDetail(r.name)">
						<td>
							<div class="font-monospace small">{{ r.name }}</div>
							<span v-if="r.is_default" class="badge bg-blue-lt mt-1">{{ t("Default") }}</span>
						</td>
						<td>
							<div class="fw-semibold">{{ r.item_name || r.item }}</div>
							<div class="small text-secondary font-monospace">{{ r.item }}</div>
						</td>
						<td class="text-end font-monospace">{{ formatQty(r.quantity, r.uom) }}</td>
						<td class="text-end font-monospace">{{ money(r.total_cost, r.currency) }}</td>
						<td>
							<span class="badge" :class="r.docstatus === 1 ? 'bg-success-lt' : r.docstatus === 2 ? 'bg-secondary-lt' : 'bg-yellow-lt'">
								{{ r.docstatus === 1 ? t("Submitted") : r.docstatus === 2 ? t("Cancelled") : t("Draft") }}
							</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<!-- Detail drawer -->
	<div v-if="detailOpen" class="offcanvas-backdrop fade show" @click="closeDetail"></div>
	<div v-if="detailOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="visibility: visible; width: 640px">
		<div class="offcanvas-header">
			<h5 class="offcanvas-title">
				<span v-if="detail?.name" class="font-monospace small">{{ detail.name }}</span>
				<span v-else>{{ t("BOM") }}</span>
			</h5>
			<button type="button" class="btn-close" @click="closeDetail"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="detailLoading" class="text-center py-5">
				<div class="spinner-border text-primary"></div>
			</div>
			<div v-else-if="detail?.error" class="alert alert-danger">{{ detail.error }}</div>
			<template v-else-if="detail">
				<div class="mb-3">
					<div class="text-secondary small">{{ t("Finished good") }}</div>
					<div class="fw-semibold">{{ detail.item_name || detail.item }}</div>
					<div class="small text-secondary">{{ formatQty(detail.quantity, detail.uom) }}</div>
				</div>

				<div class="row g-2 mb-3">
					<div class="col-6">
						<div class="text-secondary small">{{ t("Raw material cost") }}</div>
						<div class="font-monospace">{{ money(detail.raw_material_cost, detail.currency) }}</div>
					</div>
					<div class="col-6">
						<div class="text-secondary small">{{ t("Total cost") }}</div>
						<div class="font-monospace fw-semibold">{{ money(detail.total_cost, detail.currency) }}</div>
					</div>
				</div>

				<h6 class="text-uppercase small text-secondary mt-3 mb-2">{{ t("Components") }}</h6>
				<div class="table-responsive">
					<table class="table table-sm table-vcenter">
						<thead>
							<tr>
								<th>{{ t("Item") }}</th>
								<th class="text-end">{{ t("Qty") }}</th>
								<th class="text-end">{{ t("Rate") }}</th>
								<th class="text-end">{{ t("Amount") }}</th>
							</tr>
						</thead>
						<tbody>
							<tr v-for="(it, i) in detail.items" :key="i">
								<td>
									<div class="fw-semibold">{{ it.item_name || it.item_code }}</div>
									<div class="small text-secondary font-monospace">{{ it.item_code }}</div>
								</td>
								<td class="text-end font-monospace">{{ formatQty(it.qty, it.uom) }}</td>
								<td class="text-end font-monospace">{{ money(it.rate, detail.currency) }}</td>
								<td class="text-end font-monospace">{{ money(it.amount, detail.currency) }}</td>
							</tr>
						</tbody>
					</table>
				</div>

				<div class="mt-3 d-flex gap-2">
					<button
						v-if="detail.docstatus === 0"
						type="button"
						class="btn btn-success"
						@click="submitBom(detail.name)"
					>
						<i class="ti ti-check me-1"></i>{{ t("Submit") }}
					</button>
					<button
						v-if="detail.docstatus === 1"
						type="button"
						class="btn btn-outline-danger"
						@click="cancelBom(detail.name)"
					>
						<i class="ti ti-x me-1"></i>{{ t("Cancel") }}
					</button>
				</div>
			</template>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" style="background: transparent">
		<div class="modal-dialog modal-lg">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New BOM") }}</h5>
					<button type="button" class="btn-close" @click="closeCreate"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>

					<div class="row g-2 mb-3">
						<div class="col-md-7">
							<label class="form-label">{{ t("Finished good") }}</label>
							<select v-model="form.item" class="form-select" @change="onFgItemChange">
								<option value="">—</option>
								<option v-for="it in itemOptions" :key="it.name" :value="it.name">
									{{ it.item_name }} ({{ it.item_code }})
								</option>
							</select>
						</div>
						<div class="col-md-3">
							<label class="form-label">{{ t("Quantity") }}</label>
							<input v-model.number="form.quantity" type="number" min="0.001" step="0.001" inputmode="decimal" class="form-control" />
						</div>
						<div class="col-md-2">
							<label class="form-label">{{ t("UOM") }}</label>
							<input v-model="form.uom" type="text" class="form-control" :placeholder="t('Nos')" />
						</div>
					</div>

					<div class="form-check form-switch mb-3">
						<input v-model="form.is_default" id="bom-default" class="form-check-input" type="checkbox" />
						<label class="form-check-label" for="bom-default">{{ t("Make default BOM for this item") }}</label>
					</div>

					<h6 class="text-uppercase small text-secondary mb-2">{{ t("Raw materials") }}</h6>
					<div class="table-responsive">
						<table class="table table-sm">
							<thead>
								<tr>
									<th style="width: 55%">{{ t("Item") }}</th>
									<th style="width: 15%">{{ t("Qty") }}</th>
									<th style="width: 15%">{{ t("UOM") }}</th>
									<th style="width: 12%">{{ t("Rate") }}</th>
									<th style="width: 3%"></th>
								</tr>
							</thead>
							<tbody>
								<tr v-for="(line, i) in form.items" :key="i">
									<td>
										<select v-model="line.item_code" class="form-select form-select-sm" @change="onLineItemChange(line)">
											<option value="">—</option>
											<option v-for="it in itemOptions" :key="it.name" :value="it.name">
												{{ it.item_name }} ({{ it.item_code }})
											</option>
										</select>
									</td>
									<td>
										<input v-model.number="line.qty" type="number" min="0" step="0.001" inputmode="decimal" class="form-control form-control-sm" />
									</td>
									<td>
										<input v-model="line.uom" type="text" class="form-control form-control-sm" />
									</td>
									<td>
										<MoneyInput v-model="line.rate" :currency="currency" :language="user.language || 'en'" size="sm" />
									</td>
									<td class="text-end">
										<button type="button" class="btn btn-sm btn-ghost-danger" @click="removeLine(i)">
											<i class="ti ti-trash"></i>
										</button>
									</td>
								</tr>
							</tbody>
						</table>
					</div>
					<button type="button" class="btn btn-sm btn-outline-secondary" @click="addLine">
						<i class="ti ti-plus me-1"></i>{{ t("Add line") }}
					</button>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-outline-primary" :disabled="submitting" @click="saveBom(false)">
						<i class="ti ti-device-floppy me-1"></i>{{ t("Save as draft") }}
					</button>
					<button type="button" class="btn btn-primary" :disabled="submitting" @click="saveBom(true)">
						<i class="ti ti-check me-1"></i>{{ t("Save and submit") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.cursor-pointer {
	cursor: pointer;
}
</style>
