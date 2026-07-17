<script setup>
import { computed, onMounted, ref } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import { itemSearcher } from "../../composables/items.js";
import Typeahead from "../../components/Typeahead.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import EmptyState from "../../components/EmptyState.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const toast = useToast();
const { confirm } = useConfirm();

const rows = ref([]);
const loading = ref(false);
const search = ref("");

const searchItems = itemSearcher("purchase", { limit: 20 });

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.display_name, r.category_name, r.supplier_name, r.vendor].filter(Boolean).some((v) => String(v).toLowerCase().includes(q)),
	);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		rows.value = await call("stabler.api.imports.list_vendor_categories", {
			company: activeCompany.value,
		});
	} catch (err) {
		toast.error(err?.message || t("Failed to load vendor categories."));
		rows.value = [];
	} finally {
		loading.value = false;
	}
}
onMounted(load);

// ---- Create / edit modal ----
const modalOpen = ref(false);
const saving = ref(false);
const form = ref(null);

function blankLine() {
	return { item_code: "", item_name: "", stock_uom: "", boxes_per_container: 0 };
}

function blankForm() {
	return {
		name: "",
		vendor: "",
		supplier_name: "",
		category_name: "",
		display_name: "",
		description: "",
		is_active: true,
		items: [blankLine()],
	};
}

function openNew() {
	form.value = blankForm();
	modalOpen.value = true;
}

async function openEdit(row) {
	loading.value = true;
	try {
		const detail = await call("stabler.api.imports.vendor_category_detail", { name: row.name });
		form.value = {
			name: detail.name,
			vendor: detail.vendor,
			supplier_name: row.supplier_name || detail.vendor,
			category_name: detail.category_name,
			display_name: detail.display_name,
			description: detail.description || "",
			is_active: !!detail.is_active,
			items: detail.items?.length ? detail.items.map((it) => ({ ...it })) : [blankLine()],
		};
		modalOpen.value = true;
	} catch (err) {
		toast.error(err?.message || t("Failed to load the category."));
	} finally {
		loading.value = false;
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

function pickItem(line, item) {
	line.item_code = item.item_code || item.name;
	line.item_name = item.item_name;
	line.stock_uom = item.stock_uom || "";
}
function clearItem(line) {
	line.item_code = "";
	line.item_name = "";
	line.stock_uom = "";
}
function addLine() {
	form.value.items.push(blankLine());
}
function removeLine(idx) {
	if (form.value.items.length === 1) {
		form.value.items[0] = blankLine();
		return;
	}
	form.value.items.splice(idx, 1);
}

const canSave = computed(() => {
	const f = form.value;
	if (!f) return false;
	if (!f.vendor || !(f.category_name || "").trim()) return false;
	return f.items.some((l) => l.item_code);
});

async function saveCategory() {
	if (!canSave.value) return;
	saving.value = true;
	try {
		await call("stabler.api.imports.save_vendor_category", {
			payload: {
				name: form.value.name || undefined,
				vendor: form.value.vendor,
				category_name: form.value.category_name,
				display_name: form.value.display_name,
				description: form.value.description,
				is_active: form.value.is_active ? 1 : 0,
				items: form.value.items.filter((l) => l.item_code).map((l) => ({
					item_code: l.item_code,
					boxes_per_container: l.boxes_per_container,
				})),
			},
			company: activeCompany.value,
		});
		toast.success(t("Vendor category saved"));
		modalOpen.value = false;
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not save the vendor category."));
	} finally {
		saving.value = false;
	}
}

async function deleteCategory(row) {
	const ok = await confirm({
		title: t("Delete Vendor Category"),
		body: t("Delete category") + " " + (row.display_name || row.category_name) + "? " + t("This cannot be undone."),
		confirmLabel: t("Delete"),
		cancelLabel: t("Cancel"),
		danger: true,
	});
	if (!ok) return;
	try {
		await call("stabler.api.imports.delete_vendor_category", {
			name: row.name,
			company: activeCompany.value,
		});
		toast.success(t("Vendor category deleted."));
		load();
	} catch (err) {
		toast.error(err?.message || t("Could not delete the vendor category."));
	}
}
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<div class="card-title m-0">{{ t("Vendor Categories") }}</div>
			<button type="button" class="btn btn-primary btn-sm ms-auto" @click="openNew">
				<i class="ti ti-plus me-1"></i>{{ t("New Category") }}
			</button>
		</div>

		<ListToolbar v-model="search" :placeholder="t('Category or supplier') + '  ⌘K'" :count="filteredRows.length" />

		<div class="table-responsive">
			<table class="table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Category") }}</th>
						<th>{{ t("Supplier") }}</th>
						<th>{{ t("Description") }}</th>
						<th class="text-end">{{ t("Items") }}</th>
						<th>{{ t("Status") }}</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					<SkeletonRows v-if="loading" :cols="6" :rows="6" />
					<tr v-for="r in filteredRows" :key="r.name" style="cursor: pointer" @click="openEdit(r)">
						<td class="fw-semibold">{{ r.display_name || r.category_name }}</td>
						<td>{{ r.supplier_name || r.vendor }}</td>
						<td class="text-secondary small">{{ r.description || "—" }}</td>
						<td class="text-end font-monospace">{{ r.item_count }}</td>
						<td>
							<span class="badge" :class="r.is_active ? 'bg-green-lt' : 'bg-secondary-lt'">
								{{ r.is_active ? t("Active") : t("Inactive") }}
							</span>
						</td>
						<td class="text-end" @click.stop>
							<button type="button" class="btn btn-outline-secondary btn-sm me-1" @click="openEdit(r)">
								<i class="ti ti-edit me-1"></i>{{ t("Edit") }}
							</button>
							<button type="button" class="btn btn-ghost-secondary btn-sm" @click="deleteCategory(r)">
								<i class="ti ti-trash me-1"></i>{{ t("Delete") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
			<EmptyState v-if="!loading && !filteredRows.length" :title="t('No vendor categories yet')" :subtitle="t('Create your first vendor category.')" />
		</div>
	</div>

	<!-- Create / edit modal -->
	<div v-if="modalOpen" class="modal d-block" tabindex="-1" style="background: rgba(0,0,0,0.4)">
		<div class="modal-dialog modal-lg modal-dialog-centered">
			<div class="modal-content">
				<div class="modal-header">
					<h5 class="modal-title">{{ form.name ? t("Edit Vendor Category") : t("New Vendor Category") }}</h5>
					<button type="button" class="btn-close" @click="closeModal"></button>
				</div>
				<div class="modal-body">
					<div class="row g-3">
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Supplier") }} *</label>
							<Typeahead
								v-model="form.vendor"
								:display="form.vendor ? `${form.supplier_name || form.vendor}` : ''"
								:search="searchSuppliers"
								:placeholder="t('Search supplier…')"
								@pick="(s) => { form.vendor = s.name; form.supplier_name = s.supplier_name || s.name; }"
								@clear="() => { form.vendor = ''; form.supplier_name = ''; }"
							/>
						</div>
						<div class="col-md-6 d-flex align-items-end">
							<div class="form-check">
								<input v-model="form.is_active" class="form-check-input" type="checkbox" id="vc-active" />
								<label class="form-check-label" for="vc-active">{{ t("Active") }}</label>
							</div>
						</div>

						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Category Name") }} *</label>
							<input v-model="form.category_name" type="text" class="form-control form-control-sm" />
						</div>
						<div class="col-md-6">
							<label class="form-label small mb-1">{{ t("Display Name") }}</label>
							<input v-model="form.display_name" type="text" class="form-control form-control-sm" />
						</div>
						<div class="col-12">
							<label class="form-label small mb-1">{{ t("Description") }}</label>
							<textarea v-model="form.description" rows="2" class="form-control form-control-sm"></textarea>
						</div>

						<div class="col-12">
							<div class="d-flex align-items-center justify-content-between mb-1">
								<label class="form-label small mb-0">{{ t("Items") }} *</label>
								<button type="button" class="btn btn-ghost-secondary btn-sm" @click="addLine">
									<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
								</button>
							</div>
							<div class="table-responsive">
								<table class="table table-sm table-bordered align-middle">
									<thead class="table-light">
										<tr>
											<th style="width: 60%">{{ t("Item") }}</th>
											<th style="width: 30%">{{ t("Boxes per container") }}</th>
											<th style="width: 36px"></th>
										</tr>
									</thead>
									<tbody>
										<tr v-for="(line, idx) in form.items" :key="idx">
											<td>
												<Typeahead
													v-model="line.item_code"
													:display="line.item_code ? `${line.item_code} — ${line.item_name || ''}` : ''"
													:search="searchItems"
													size="sm"
													:placeholder="t('Search item…')"
													@pick="(item) => pickItem(line, item)"
													@clear="clearItem(line)"
												>
													<template #option="{ item }">
														<div class="d-flex justify-content-between align-items-center">
															<div>
																<div class="fw-semibold small">{{ item.item_name }}</div>
																<div class="font-monospace text-secondary" style="font-size: 11px">
																	{{ item.item_code }}
																</div>
															</div>
															<span class="badge bg-secondary-lt">{{ item.stock_uom }}</span>
														</div>
													</template>
												</Typeahead>
											</td>
											<td>
												<input
													v-model.number="line.boxes_per_container"
													type="number"
													inputmode="numeric"
													min="0"
													step="1"
													class="form-control form-control-sm text-end font-monospace"
												/>
											</td>
											<td>
												<button
													type="button"
													class="btn btn-icon btn-sm btn-ghost-secondary"
													@click="removeLine(idx)"
													:title="t('Remove')"
												>
													<i class="ti ti-trash"></i>
												</button>
											</td>
										</tr>
									</tbody>
								</table>
							</div>
						</div>
					</div>
				</div>
				<div class="modal-footer">
					<button type="button" class="btn btn-outline-secondary" @click="closeModal">{{ t("Cancel") }}</button>
					<button type="button" class="btn btn-primary" :disabled="saving || !canSave" @click="saveCategory">
						<span v-if="saving" class="spinner-border spinner-border-sm me-1"></span>{{ t("Save") }}
					</button>
				</div>
			</div>
		</div>
	</div>
</template>
