<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { useEscapeBack } from "../../composables/useEscapeBack.js";
import { buildItemGroupTree, flattenItemGroupTree, itemGroupOptions } from "../../composables/itemGroupTree.js";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import EmptyState from "../../components/EmptyState.vue";
import Select from "../../components/Select.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();

const loading = ref(false);
const rows = ref([]);
const root = ref("");
const canManage = ref(false);
const expanded = ref(new Set());
const search = ref("");

const tree = computed(() => buildItemGroupTree(rows.value));
const flattened = computed(() => flattenItemGroupTree(tree.value, expanded.value, search.value));

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		const data = await call("stabler.api.inventory.list_item_group_tree", {
			company: activeCompany.value,
		});
		rows.value = data?.rows || [];
		root.value = data?.root || "";
		canManage.value = !!data?.can_manage;
		// Groups default open — the user wants the full category tree visible
		// without clicking, same as the Chart of Accounts.
		expanded.value = new Set(rows.value.filter((r) => r.is_group).map((r) => r.name));
	} catch (err) {
		toast.error(err?.message || t("Could not load categories."));
		rows.value = [];
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, load);

function toggle(name) {
	const next = new Set(expanded.value);
	if (next.has(name)) next.delete(name);
	else next.add(name);
	expanded.value = next;
}

function expandAll() {
	expanded.value = new Set(rows.value.filter((r) => r.is_group).map((r) => r.name));
}
function collapseAll() {
	expanded.value = new Set();
}

// ---- Create ----
const createOpen = ref(false);
const submitting = ref(false);
const submitError = ref("");

function blankForm(parentName) {
	return { item_group_name: "", parent_item_group: parentName || root.value, is_group: false };
}
const form = ref(blankForm());

const createParentOptions = computed(() => itemGroupOptions(rows.value, { groupsOnly: true }));

function openCreate(parentName = "") {
	form.value = blankForm(parentName);
	submitError.value = "";
	createOpen.value = true;
}
function closeCreate() {
	if (submitting.value) return;
	createOpen.value = false;
}
async function submitCreate() {
	submitError.value = "";
	const name = form.value.item_group_name.trim();
	if (!name) {
		submitError.value = t("Category name is required.");
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.inventory.create_item_group", {
			item_group_name: name,
			company: activeCompany.value,
			parent_item_group: form.value.parent_item_group || undefined,
			is_group: form.value.is_group ? 1 : 0,
		});
		createOpen.value = false;
		toast.success(t("Category created."));
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Could not save category.");
	} finally {
		submitting.value = false;
	}
}

// ---- Edit ----
const editOpen = ref(false);
const editForm = ref(null);

const editIsRoot = computed(() => !!editForm.value && !editForm.value.parent_item_group);
const editParentOptions = computed(() =>
	editForm.value ? itemGroupOptions(rows.value, { excludeSubtreeOf: editForm.value.name, groupsOnly: true }) : []
);

function openEdit(node) {
	if (!canManage.value) return;
	editForm.value = {
		name: node.name,
		item_group_name: node.item_group_name || node.name,
		parent_item_group: node.parent_item_group || "",
		is_group: !!node.is_group || (node.children || []).length > 0,
		hasChildren: (node.children || []).length > 0,
		modified: node.modified,
	};
	submitError.value = "";
	editOpen.value = true;
}
function closeEdit() {
	if (submitting.value) return;
	editOpen.value = false;
}
async function submitEdit() {
	if (!editForm.value) return;
	submitError.value = "";
	const name = editForm.value.item_group_name.trim();
	if (!name) {
		submitError.value = t("Category name is required.");
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.inventory.update_item_group", {
			name: editForm.value.name,
			company: activeCompany.value,
			item_group_name: name,
			parent_item_group: editForm.value.parent_item_group || undefined,
			is_group: editForm.value.is_group ? 1 : 0,
			modified: editForm.value.modified,
		});
		editOpen.value = false;
		toast.success(t("Category updated."));
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Could not save category.");
	} finally {
		submitting.value = false;
	}
}

// ---- Delete ----
async function deleteCategory(node) {
	let impact;
	try {
		impact = await call("stabler.api.inventory.item_group_delete_impact", {
			name: node.name,
			company: activeCompany.value,
		});
	} catch (err) {
		toast.error(err?.message || t("Could not delete category."));
		return;
	}
	if (impact?.blockers?.length) {
		toast.error(impact.blockers[0]);
		return;
	}
	const ok = await confirm({
		title: t("Delete category?"),
		body: t("{0} will be permanently deleted. This cannot be undone.").replace(
			"{0}",
			node.item_group_name || node.name
		),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	try {
		await call("stabler.api.inventory.delete_item_group", { name: node.name, company: activeCompany.value });
		toast.success(t("Category deleted."));
		await load();
	} catch (err) {
		toast.error(err?.message || t("Could not delete category."));
	}
}

useEscapeBack(() => {
	if (createOpen.value) {
		closeCreate();
		return true;
	}
	if (editOpen.value) {
		closeEdit();
		return true;
	}
	return false;
}, "/inventory");
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2 flex-wrap">
			<div class="card-title m-0">{{ t("Item categories") }}</div>
			<button
				type="button"
				class="btn btn-sm btn-ghost-secondary"
				@click="expandAll"
				:title="t('Expand all groups')"
			>
				<i class="ti ti-fold-down me-1"></i>{{ t("Expand all") }}
			</button>
			<button
				type="button"
				class="btn btn-sm btn-ghost-secondary"
				@click="collapseAll"
				:title="t('Collapse all groups')"
			>
				<i class="ti ti-fold me-1"></i>{{ t("Collapse all") }}
			</button>
			<button
				v-if="canManage"
				type="button"
				class="btn btn-primary btn-sm ms-auto"
				@click="openCreate()"
			>
				<i class="ti ti-plus me-1"></i>{{ t("New category") }}
			</button>
		</div>

		<ListToolbar v-model="search" :placeholder="t('Category or parent')" :count="flattened.length" />

		<div class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Category") }}</th>
						<th class="w-1">{{ t("Type") }}</th>
						<th class="w-1 text-end">{{ t("Items") }}</th>
						<th class="w-1 text-end">{{ t("Total items") }}</th>
						<th class="w-1"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :cols="5" :rows="6" />
				<tbody v-else>
					<tr v-for="n in flattened" :key="n.name">
						<td>
							<div
								class="d-flex align-items-center gap-1 ig-row"
								:style="{ paddingLeft: `${n.depth * 1.25}rem` }"
							>
								<button
									v-if="n.is_group"
									type="button"
									class="btn btn-icon btn-sm btn-ghost-secondary"
									@click="toggle(n.name)"
									:aria-label="expanded.has(n.name) ? t('Collapse') : t('Expand')"
								>
									<i class="ti" :class="expanded.has(n.name) ? 'ti-chevron-down' : 'ti-chevron-right'"></i>
								</button>
								<span v-else class="d-inline-block" style="width: 1.75rem"></span>
								<i class="ti me-1 text-secondary" :class="n.is_group ? 'ti-folder' : 'ti-box'"></i>
								<span :class="{ 'fw-semibold': n.is_group }">{{ n.item_group_name || n.name }}</span>
								<button
									v-if="canManage && n.is_group"
									type="button"
									class="btn btn-icon btn-sm btn-ghost-primary ig-add ms-1"
									:title="t('Add subcategory')"
									@click.stop="openCreate(n.name)"
								>
									<i class="ti ti-plus"></i>
								</button>
							</div>
						</td>
						<td>
							<span class="badge" :class="n.is_group ? 'bg-blue-lt' : 'bg-secondary-lt'">
								{{ n.is_group ? t("Group") : t("Leaf") }}
							</span>
						</td>
						<td class="text-end font-monospace">{{ n.item_count || 0 }}</td>
						<td class="text-end font-monospace">
							<span v-if="n.is_group">{{ n.totalItemCount || 0 }}</span>
							<span v-else class="text-secondary">—</span>
						</td>
						<td class="text-end" @click.stop>
							<template v-if="canManage">
								<button
									type="button"
									class="btn btn-icon btn-sm btn-ghost-secondary"
									:title="t('Edit')"
									@click="openEdit(n)"
								>
									<i class="ti ti-edit"></i>
								</button>
								<button
									type="button"
									class="btn btn-icon btn-sm btn-ghost-secondary"
									:title="t('Delete')"
									@click="deleteCategory(n)"
								>
									<i class="ti ti-trash"></i>
								</button>
							</template>
						</td>
					</tr>
				</tbody>
			</table>
			<EmptyState
				v-if="!loading && !flattened.length"
				icon="ti-category-2"
				:title="t('No categories found')"
				:subtitle="t('Categories group your items the way QuickBooks categories do.')"
			>
				<template v-if="canManage" #actions>
					<button type="button" class="btn btn-primary" @click="openCreate()">
						<i class="ti ti-plus me-1"></i>{{ t("New category") }}
					</button>
				</template>
			</EmptyState>
		</div>
	</div>

	<!-- Create modal -->
	<div v-if="createOpen" class="modal-backdrop fade show" @click="closeCreate"></div>
	<div v-if="createOpen" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeCreate">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("New category") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeCreate" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-3">
						<div class="col-12">
							<label class="form-label required">{{ t("Category name") }}</label>
							<input v-model="form.item_group_name" type="text" class="form-control" autofocus />
						</div>
						<div class="col-12">
							<label class="form-label">{{ t("Parent category") }}</label>
							<Select
								v-model="form.parent_item_group"
								:options="createParentOptions"
								:placeholder="t('— top level —')"
							>
								<template #option="{ option }">
									<span :style="{ paddingLeft: `${option.depth * 0.75}rem` }">{{ option.label }}</span>
								</template>
								<template #selected="{ option }">{{ option.label }}</template>
							</Select>
						</div>
						<div class="col-12">
							<div class="form-check">
								<input v-model="form.is_group" class="form-check-input" type="checkbox" id="ig_is_group" />
								<label class="form-check-label" for="ig_is_group">
									{{ t("Can contain subcategories") }}
								</label>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeCreate">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitCreate">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>

	<!-- Edit modal -->
	<div v-if="editOpen" class="modal-backdrop fade show" @click="closeEdit"></div>
	<div v-if="editOpen && editForm" class="modal fade show d-block" tabindex="-1" role="dialog" @click.self="closeEdit">
		<div class="modal-dialog modal-dialog-centered" role="document">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ t("Edit category") }}</h5>
					<button type="button" class="btn-close" aria-label="Close" @click="closeEdit" :disabled="submitting"></button>
				</div>
				<div class="modal-body">
					<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
					<div class="row g-3">
						<div class="col-12">
							<label class="form-label required">{{ t("Category name") }}</label>
							<input v-model="editForm.item_group_name" type="text" class="form-control" autofocus />
							<div class="form-hint">{{ t("Renaming a category updates it on every item that uses it.") }}</div>
						</div>
						<div v-if="!editIsRoot" class="col-12">
							<label class="form-label">{{ t("Parent category") }}</label>
							<Select
								v-model="editForm.parent_item_group"
								:options="editParentOptions"
								:placeholder="t('— top level —')"
							>
								<template #option="{ option }">
									<span :style="{ paddingLeft: `${option.depth * 0.75}rem` }">{{ option.label }}</span>
								</template>
								<template #selected="{ option }">{{ option.label }}</template>
							</Select>
						</div>
						<div class="col-12">
							<div class="form-check">
								<input
									v-model="editForm.is_group"
									class="form-check-input"
									type="checkbox"
									id="ig_edit_is_group"
									:disabled="editForm.hasChildren"
								/>
								<label class="form-check-label" for="ig_edit_is_group">
									{{ t("Can contain subcategories") }}
								</label>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-link link-secondary" :disabled="submitting" @click="closeEdit">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary ms-auto" :disabled="submitting" @click="submitEdit">
						<span v-if="submitting" class="spinner-border spinner-border-sm me-1"></span>
						{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>

<style scoped>
.ig-add {
	opacity: 0;
	transition: opacity 0.15s ease;
}
.ig-row:hover .ig-add {
	opacity: 1;
}
</style>
