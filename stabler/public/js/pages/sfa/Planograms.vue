<script setup>
import { onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import EmptyState from "../../components/EmptyState.vue";
import DateInput from "../../components/DateInput.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);

const drawerOpen = ref(false);
const drawerMode = ref("create");
const form = ref(blankForm());
const submitting = ref(false);
const submitError = ref("");

function blankForm() {
	return {
		name: "",
		outlet: "",
		company: activeCompany.value || "",
		category: "",
		valid_from: "",
		is_active: 1,
		items: [],
	};
}

function blankItem() {
	return { item: "", expected_facings: 1, shelf_position: "" };
}

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_planograms", {
			company: activeCompany.value,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function openCreate() {
	form.value = blankForm();
	drawerMode.value = "create";
	submitError.value = "";
	drawerOpen.value = true;
}

async function openEdit(row) {
	submitError.value = "";
	drawerMode.value = "edit";
	try {
		const full = await call("stabler.api.sfa.get_planogram", { name: row.name });
		form.value = {
			name: full.name,
			outlet: full.outlet || "",
			company: full.company || activeCompany.value || "",
			category: full.category || "",
			valid_from: full.valid_from || "",
			is_active: full.is_active ? 1 : 0,
			items: (full.items || []).map((it) => ({
				item: it.item || "",
				expected_facings: it.expected_facings ?? 1,
				shelf_position: it.shelf_position || "",
			})),
		};
		drawerOpen.value = true;
	} catch (e) {
		error.value = e?.message || t("Failed to load planogram.");
	}
}

function closeDrawer() {
	if (submitting.value) return;
	drawerOpen.value = false;
	submitError.value = "";
}

function addItem() {
	form.value.items.push(blankItem());
}

function removeItem(idx) {
	form.value.items.splice(idx, 1);
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.outlet?.trim()) return (submitError.value = t("Outlet is required."));
	if (!f.company?.trim()) return (submitError.value = t("Company is required."));
	for (const [i, row] of f.items.entries()) {
		if (!row.item?.trim()) {
			return (submitError.value = t("Item is required on row {0}.").replace("{0}", String(i + 1)));
		}
		if (row.expected_facings == null || row.expected_facings === "") {
			return (submitError.value = t("Expected facings is required on row {0}.").replace(
				"{0}",
				String(i + 1)
			));
		}
	}
	submitting.value = true;
	try {
		const payload = {
			outlet: f.outlet,
			company: f.company,
			category: f.category || null,
			valid_from: f.valid_from || null,
			is_active: f.is_active ? 1 : 0,
			items: f.items.map((it) => ({
				item: it.item,
				expected_facings: Number(it.expected_facings) || 0,
				shelf_position: it.shelf_position || null,
			})),
		};
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_planogram", { payload });
		} else {
			await call("stabler.api.sfa.update_planogram", { name: f.name, payload });
		}
		drawerOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Failed to save planogram.");
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
			<h3 class="card-title mb-0">{{ t("Planograms") }}</h3>
			<div class="ms-auto">
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-layout-grid"
			:title="t('No planograms yet')"
			:description="t('Planograms describe expected shelf facings per outlet and category.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Outlet") }}</th>
						<th>{{ t("Category") }}</th>
						<th>{{ t("Valid From") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="w-1"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.name }}</td>
						<td>{{ r.outlet }}</td>
						<td>{{ r.category || "—" }}</td>
						<td>{{ formatDate(r.valid_from) }}</td>
						<td>
							<span
								class="badge"
								:class="r.is_active ? 'bg-success-lt' : 'bg-secondary-lt'"
							>
								{{ r.is_active ? t("Active") : t("Inactive") }}
							</span>
						</td>
						<td class="text-end">
							<button type="button" class="btn btn-sm btn-link" @click="openEdit(r)">
								{{ t("Edit") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>

	<template v-if="drawerOpen">
		<div class="modal-backdrop fade show" @click="closeDrawer"></div>
		<div class="modal fade show d-block" tabindex="-1" role="dialog">
			<div class="modal-dialog modal-dialog-centered modal-lg" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">
							{{ drawerMode === "create" ? t("New planogram") : t("Edit planogram") }}
						</h5>
						<button
							type="button"
							class="btn-close"
							:aria-label="t('Close')"
							@click="closeDrawer"
						></button>
					</div>
					<div class="modal-body">
						<div v-if="submitError" class="alert alert-danger">{{ submitError }}</div>
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label">{{ t("Outlet") }} <span class="text-danger">*</span></label>
								<input v-model="form.outlet" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Company") }} <span class="text-danger">*</span></label>
								<input v-model="form.company" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Category") }}</label>
								<input v-model="form.category" type="text" class="form-control" />
							</div>
							<div class="col-md-4">
								<label class="form-label">{{ t("Valid From") }}</label>
								<DateInput v-model="form.valid_from" />
							</div>
							<div class="col-md-2">
								<label class="form-label">{{ t("Active") }}</label>
								<div class="form-check form-switch mt-1">
									<input
										v-model="form.is_active"
										:true-value="1"
										:false-value="0"
										class="form-check-input"
										type="checkbox"
									/>
								</div>
							</div>
						</div>

						<h6 class="text-uppercase text-secondary small mt-4 mb-2">{{ t("Items") }}</h6>
						<div class="table-responsive">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th>{{ t("Item") }} <span class="text-danger">*</span></th>
										<th style="width: 160px">{{ t("Expected Facings") }} <span class="text-danger">*</span></th>
										<th style="width: 200px">{{ t("Shelf Position") }}</th>
										<th class="w-1"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-if="!form.items.length">
										<td colspan="4" class="text-secondary text-center small">
											{{ t("No items yet.") }}
										</td>
									</tr>
									<tr v-for="(row, idx) in form.items" :key="idx">
										<td>
											<input v-model="row.item" type="text" class="form-control form-control-sm" />
										</td>
										<td>
											<input
												v-model.number="row.expected_facings"
												type="number"
												inputmode="decimal"
												min="0"
												class="form-control form-control-sm"
											/>
										</td>
										<td>
											<input v-model="row.shelf_position" type="text" class="form-control form-control-sm" />
										</td>
										<td>
											<button
												type="button"
												class="btn btn-sm btn-link link-danger"
												:aria-label="t('Remove')"
												@click="removeItem(idx)"
											>
												<i class="ti ti-x"></i>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
						<button type="button" class="btn btn-sm btn-outline-primary" @click="addItem">
							<i class="ti ti-plus me-1"></i>{{ t("Add item") }}
						</button>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-link link-secondary"
							:disabled="submitting"
							@click="closeDrawer"
						>
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submitting || !form.outlet?.trim() || !form.company?.trim()"
							@click="submitDrawer"
						>
							<span v-if="submitting" class="spinner-border spinner-border-sm me-2"></span>
							<i v-else class="ti ti-device-floppy me-1"></i>
							{{ t("Save") }}
						</button>
					</div>
				</div>
			</div>
		</div>
	</template>
</template>
