<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { formatMoney } from "../../composables/money.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany, user } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const flat = ref([]);
const expanded = ref(new Set());
const search = ref("");

const currency = computed(
	() =>
		(session.companies.find((c) => c.name === activeCompany.value) || {}).default_currency ||
		"USD"
);

const tree = computed(() => {
	const byParent = new Map();
	for (const w of flat.value) {
		const k = w.parent_warehouse || "__ROOT__";
		if (!byParent.has(k)) byParent.set(k, []);
		byParent.get(k).push(w);
	}
	function build(parentKey, depth) {
		const list = byParent.get(parentKey) || [];
		return list.map((node) => ({
			...node,
			depth,
			children: node.is_group ? build(node.name, depth + 1) : [],
		}));
	}
	return build("__ROOT__", 0);
});

const flattened = computed(() => {
	const out = [];
	const term = search.value.trim().toLowerCase();
	const matches = (n) =>
		!term ||
		(n.warehouse_name || "").toLowerCase().includes(term) ||
		(n.name || "").toLowerCase().includes(term);
	function walk(node) {
		const expandedNow = term ? true : expanded.value.has(node.name);
		if (matches(node) || !term) out.push(node);
		if (expandedNow && node.children?.length) {
			for (const c of node.children) walk(c);
		}
	}
	for (const r of tree.value) walk(r);
	if (!term) return out;
	return out.filter(matches);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		const rows = await call("stabler.api.inventory.list_warehouses", {
			company: activeCompany.value,
		});
		flat.value = rows || [];
		expanded.value = new Set(
			(rows || []).filter((r) => r.is_group && !r.parent_warehouse).map((r) => r.name)
		);
	} catch (err) {
		error.value = err?.message || "Failed to load warehouses.";
	} finally {
		loading.value = false;
	}
}

function toggle(name) {
	const next = new Set(expanded.value);
	if (next.has(name)) next.delete(name);
	else next.add(name);
	expanded.value = next;
}

const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");
const parentOptions = ref([]);
const typeOptions = ref([]);
const optionsLoaded = ref(false);

function blankWarehouse() {
	return { warehouse_name: "", parent_warehouse: "", warehouse_type: "", is_group: false };
}
const form = ref(blankWarehouse());

async function loadCreateOptions() {
	if (optionsLoaded.value) return;
	try {
		const [parents, types] = await Promise.all([
			call("stabler.api.inventory.list_parent_warehouses", { company: activeCompany.value }),
			call("stabler.api.inventory.list_warehouse_types"),
		]);
		parentOptions.value = parents || [];
		typeOptions.value = types || [];
		optionsLoaded.value = true;
	} catch (err) {
		submitError.value = err?.message || "Failed to load form options.";
	}
}

function openCreate(parentName = "") {
	form.value = { ...blankWarehouse(), parent_warehouse: parentName || "" };
	submitError.value = "";
	createOpen.value = true;
	loadCreateOptions();
}

function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}

async function submitCreate() {
	submitError.value = "";
	const name = form.value.warehouse_name.trim();
	if (!name) {
		submitError.value = "Warehouse name is required.";
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.inventory.create_warehouse", {
			warehouse_name: name,
			company: activeCompany.value,
			parent_warehouse: form.value.parent_warehouse || undefined,
			warehouse_type: form.value.warehouse_type || undefined,
			is_group: form.value.is_group ? 1 : 0,
		});
		createOpen.value = false;
		optionsLoaded.value = false;  // refresh parent list
		await load();
	} catch (err) {
		submitError.value = err?.message || "Failed to create warehouse.";
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">Warehouses</div>
			<div class="ms-auto d-flex align-items-center gap-2" style="max-width: 480px; width: 100%">
				<input
					v-model="search"
					type="search"
					class="form-control form-control-sm"
					placeholder="Search warehouse…"
				/>
				<button type="button" class="btn btn-success btn-sm flex-shrink-0" @click="openCreate()">
					<i class="ti ti-plus me-1"></i>New warehouse
				</button>
			</div>
		</div>
		<div v-if="loading" class="card-body text-center py-5">
			<div class="spinner-border text-primary"></div>
		</div>
		<div v-else-if="error" class="card-body">
			<div class="alert alert-danger m-0">{{ error }}</div>
		</div>
		<EmptyState
			v-else-if="!flat.length"
			icon="ti-building-warehouse"
			accentIcon="ti-plus"
			tone="info"
			title="No warehouses for this company"
			subtitle="Add a warehouse to start tracking stock locations."
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate()">
					<i class="ti ti-plus me-1"></i>Add warehouse
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>Warehouse</th>
						<th class="w-1">Type</th>
						<th class="w-1 text-end">Stock value</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="n in flattened" :key="n.name">
						<td>
							<div
								class="d-flex align-items-center gap-1 wh-row"
								:style="{ paddingLeft: `${n.depth * 1.25}rem` }"
							>
								<button
									v-if="n.is_group"
									type="button"
									class="btn btn-icon btn-sm btn-ghost-secondary"
									@click="toggle(n.name)"
									:aria-label="expanded.has(n.name) ? 'Collapse' : 'Expand'"
								>
									<i class="ti" :class="expanded.has(n.name) ? 'ti-chevron-down' : 'ti-chevron-right'"></i>
								</button>
								<span v-else class="d-inline-block" style="width: 1.75rem"></span>
								<i class="ti me-1 text-secondary" :class="n.is_group ? 'ti-folder' : 'ti-building-warehouse'"></i>
								<span :class="{ 'fw-semibold': n.is_group }">
									{{ n.warehouse_name || n.name }}
								</span>
								<span v-if="n.disabled" class="badge bg-secondary-lt ms-2">Disabled</span>
								<button
									v-if="n.is_group"
									type="button"
									class="btn btn-icon btn-sm btn-ghost-primary wh-add ms-1"
									title="Add child warehouse"
									@click="openCreate(n.name)"
								>
									<i class="ti ti-plus"></i>
								</button>
							</div>
						</td>
						<td>
							<span v-if="n.warehouse_type" class="badge bg-blue-lt">{{ n.warehouse_type }}</span>
							<span v-else-if="n.is_group" class="badge bg-secondary-lt">Group</span>
						</td>
						<td class="text-end font-monospace">
							<span v-if="n.is_group" class="text-secondary">—</span>
							<span v-else>{{ formatMoney(n.stock_value, currency, user.language) }}</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">New warehouse</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-3">
						<div class="col-12">
							<label class="form-label required">Warehouse name</label>
							<input v-model="form.warehouse_name" type="text" class="form-control" autofocus />
						</div>
						<div class="col-md-7">
							<label class="form-label">Parent warehouse</label>
							<select v-model="form.parent_warehouse" class="form-select">
								<option value="">— top-level —</option>
								<option v-for="p in parentOptions" :key="p.name" :value="p.name">
									{{ p.warehouse_name || p.name }}
								</option>
							</select>
						</div>
						<div class="col-md-5">
							<label class="form-label">Type</label>
							<select v-model="form.warehouse_type" class="form-select">
								<option value="">—</option>
								<option v-for="t in typeOptions" :key="t.name" :value="t.name">{{ t.name }}</option>
							</select>
						</div>
						<div class="col-12">
							<div class="form-check">
								<input v-model="form.is_group" class="form-check-input" type="checkbox" id="wh_is_group" />
								<label class="form-check-label" for="wh_is_group">
									Group warehouse (can contain children, holds no stock itself)
								</label>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">Cancel</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitCreate">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						Save
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.wh-add { opacity: 0; transition: opacity 0.15s ease; }
.wh-row:hover .wh-add { opacity: 1; }
</style>
