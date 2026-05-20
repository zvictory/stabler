<script setup>
import { onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import EmptyState from "../../components/EmptyState.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const category = ref("");

const drawerOpen = ref(false);
const drawerMode = ref("create");
const form = ref(blankForm());
const submitting = ref(false);
const submitError = ref("");
const uploading = ref(false);

function blankForm() {
	return {
		name: "",
		visit: "",
		outlet: "",
		field_user: "",
		company: activeCompany.value || "",
		category: "Shelf",
		captured_at: "",
		photo_url: "",
		photo_lat: null,
		photo_lng: null,
		notes: "",
	};
}

const categoryLabel = (c) => {
	if (c === "Shelf") return t("Shelf");
	if (c === "Storefront") return t("Storefront");
	if (c === "Promo") return t("Promo");
	if (c === "Other") return t("Other");
	return c || "—";
};

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_photo_reports", {
			company: activeCompany.value,
			category: category.value || undefined,
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
		const full = await call("stabler.api.sfa.get_photo_report", { name: row.name });
		form.value = {
			name: full.name,
			visit: full.visit || "",
			outlet: full.outlet || "",
			field_user: full.field_user || "",
			company: full.company || activeCompany.value || "",
			category: full.category || "Shelf",
			captured_at: full.captured_at || "",
			photo_url: full.photo_url || "",
			photo_lat: full.photo_lat ?? null,
			photo_lng: full.photo_lng ?? null,
			notes: full.notes || "",
		};
		drawerOpen.value = true;
	} catch (e) {
		error.value = e?.message || t("Failed to load photo report.");
	}
}

function closeDrawer() {
	if (submitting.value || uploading.value) return;
	drawerOpen.value = false;
	submitError.value = "";
}

async function onPhotoSelect(e) {
	const file = e.target.files?.[0];
	if (!file) return;
	uploading.value = true;
	submitError.value = "";
	try {
		const fd = new FormData();
		fd.append("file", file);
		fd.append("is_private", "0");
		const csrf = (window.__STABLER__ && window.__STABLER__.csrfToken) || "";
		const res = await fetch("/api/method/upload_file", {
			method: "POST",
			credentials: "same-origin",
			body: fd,
			headers: { "X-Frappe-CSRF-Token": csrf },
		});
		if (!res.ok) throw new Error(`${t("Upload failed")}: ${res.status}`);
		const json = await res.json();
		form.value.photo_url = json.message?.file_url || "";
	} catch (err) {
		submitError.value = err?.message || t("Upload failed");
	} finally {
		uploading.value = false;
		// Allow re-selecting the same file
		e.target.value = "";
	}
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.outlet?.trim()) return (submitError.value = t("Outlet is required."));
	if (!f.company?.trim()) return (submitError.value = t("Company is required."));
	if (!f.category) return (submitError.value = t("Category is required."));
	if (!f.photo_url?.trim()) return (submitError.value = t("Photo is required."));
	submitting.value = true;
	try {
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_photo_report", {
				payload: {
					visit: f.visit || null,
					outlet: f.outlet,
					field_user: f.field_user || null,
					company: f.company,
					category: f.category,
					captured_at: f.captured_at || null,
					photo_url: f.photo_url,
					photo_lat: f.photo_lat,
					photo_lng: f.photo_lng,
					notes: f.notes || null,
				},
			});
		} else {
			await call("stabler.api.sfa.update_photo_report", {
				name: f.name,
				payload: {
					visit: f.visit || null,
					outlet: f.outlet,
					field_user: f.field_user || null,
					company: f.company,
					category: f.category,
					captured_at: f.captured_at || null,
					photo_url: f.photo_url,
					photo_lat: f.photo_lat,
					photo_lng: f.photo_lng,
					notes: f.notes || null,
				},
			});
		}
		drawerOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Failed to save photo report.");
	} finally {
		submitting.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
watch(category, load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Photo Reports") }}</h3>
			<div class="ms-auto d-flex gap-2 align-items-center">
				<select v-model="category" class="form-select form-select-sm" :aria-label="t('Category')">
					<option value="">{{ t("All categories") }}</option>
					<option value="Shelf">{{ t("Shelf") }}</option>
					<option value="Storefront">{{ t("Storefront") }}</option>
					<option value="Promo">{{ t("Promo") }}</option>
					<option value="Other">{{ t("Other") }}</option>
				</select>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-camera"
			:title="t('No photo reports yet')"
			:description="t('Photos capture shelves, storefronts and promotions during visits.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Outlet") }}</th>
						<th>{{ t("Field User") }}</th>
						<th>{{ t("Category") }}</th>
						<th>{{ t("Captured At") }}</th>
						<th>{{ t("Photo") }}</th>
						<th class="w-1"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.name }}</td>
						<td>{{ r.outlet }}</td>
						<td>{{ r.field_user || "—" }}</td>
						<td>{{ categoryLabel(r.category) }}</td>
						<td>{{ r.captured_at || "—" }}</td>
						<td>
							<a v-if="r.photo_url" :href="r.photo_url" target="_blank" rel="noopener">
								{{ t("Open") }}
							</a>
							<span v-else>—</span>
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
							{{ drawerMode === "create" ? t("New photo report") : t("Edit photo report") }}
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
								<label class="form-label">{{ t("Visit") }}</label>
								<input v-model="form.visit" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Field User") }}</label>
								<input v-model="form.field_user" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Company") }} <span class="text-danger">*</span></label>
								<input v-model="form.company" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Category") }} <span class="text-danger">*</span></label>
								<select v-model="form.category" class="form-select">
									<option value="Shelf">{{ t("Shelf") }}</option>
									<option value="Storefront">{{ t("Storefront") }}</option>
									<option value="Promo">{{ t("Promo") }}</option>
									<option value="Other">{{ t("Other") }}</option>
								</select>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Captured At") }}</label>
								<input v-model="form.captured_at" type="datetime-local" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Latitude") }}</label>
								<input
									v-model.number="form.photo_lat"
									type="number"
									inputmode="decimal"
									step="0.000001"
									class="form-control"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Longitude") }}</label>
								<input
									v-model.number="form.photo_lng"
									type="number"
									inputmode="decimal"
									step="0.000001"
									class="form-control"
								/>
							</div>
							<div class="col-12">
								<label class="form-label">
									{{ t("Photo") }} <span class="text-danger">*</span>
								</label>
								<input
									type="file"
									accept="image/*"
									class="form-control"
									:disabled="uploading"
									@change="onPhotoSelect"
								/>
								<div v-if="uploading" class="form-hint text-secondary">
									{{ t("Uploading…") }}
								</div>
								<div v-if="form.photo_url" class="mt-2">
									<img
										:src="form.photo_url"
										class="img-thumbnail"
										style="max-height: 160px"
										alt=""
									/>
									<div class="small text-secondary mt-1">{{ form.photo_url }}</div>
								</div>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("Notes") }}</label>
								<textarea v-model="form.notes" class="form-control" rows="2"></textarea>
							</div>
						</div>
					</div>
					<div class="modal-footer">
						<button
							type="button"
							class="btn btn-link link-secondary"
							:disabled="submitting || uploading"
							@click="closeDrawer"
						>
							{{ t("Cancel") }}
						</button>
						<button
							type="button"
							class="btn btn-primary ms-auto"
							:disabled="submitting || uploading || !form.outlet?.trim() || !form.company?.trim() || !form.photo_url?.trim()"
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
