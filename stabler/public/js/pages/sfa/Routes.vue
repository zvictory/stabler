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

const DAYS = ["Any", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function blankRoute() {
	return {
		route_code: "",
		route_name: "",
		company: activeCompany.value || "",
		field_user: "",
		day_of_week: "Any",
		is_active: 1,
		outlets: [],
	};
}

function blankOutletRow(idx) {
	return { outlet: "", sequence: idx + 1, planned_visit_time: "" };
}

const drawerOpen = ref(false);
const drawerMode = ref("create");
const form = ref(blankRoute());
const submitting = ref(false);
const submitError = ref("");
const detailLoading = ref(false);

function openCreate() {
	form.value = blankRoute();
	drawerMode.value = "create";
	submitError.value = "";
	drawerOpen.value = true;
}

async function openEdit(row) {
	drawerMode.value = "edit";
	submitError.value = "";
	form.value = { ...JSON.parse(JSON.stringify(row)), outlets: [] };
	drawerOpen.value = true;
	detailLoading.value = true;
	try {
		const full = await call("stabler.api.sfa.get_route", { name: row.name });
		const outlets = Array.isArray(full?.outlets) ? full.outlets : [];
		form.value = {
			...form.value,
			...full,
			outlets: outlets.map((o, i) => ({
				outlet: o.outlet || "",
				sequence: o.sequence || i + 1,
				planned_visit_time: o.planned_visit_time || "",
			})),
		};
	} catch (err) {
		submitError.value = err?.message || t("Something went wrong");
	} finally {
		detailLoading.value = false;
	}
}

function closeDrawer() {
	if (submitting.value) return;
	drawerOpen.value = false;
	submitError.value = "";
}

function addOutletRow() {
	form.value.outlets.push(blankOutletRow(form.value.outlets.length));
}

function removeOutletRow(idx) {
	form.value.outlets.splice(idx, 1);
	form.value.outlets.forEach((row, i) => {
		row.sequence = i + 1;
	});
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.route_code?.trim()) {
		submitError.value = t("Route code is required.");
		return;
	}
	if (!f.route_name?.trim()) {
		submitError.value = t("Route name is required.");
		return;
	}
	if (!f.company) {
		submitError.value = t("Company is required.");
		return;
	}
	if (!f.field_user?.trim()) {
		submitError.value = t("Field user is required.");
		return;
	}
	for (const row of f.outlets) {
		if (!row.outlet?.trim()) {
			submitError.value = t("Every route row needs an outlet.");
			return;
		}
	}
	const payload = {
		route_code: f.route_code.trim(),
		route_name: f.route_name.trim(),
		company: f.company,
		field_user: f.field_user.trim(),
		day_of_week: f.day_of_week || "Any",
		is_active: f.is_active ? 1 : 0,
		outlets: f.outlets.map((row, i) => ({
			sequence: row.sequence || i + 1,
			outlet: row.outlet.trim(),
			planned_visit_time: row.planned_visit_time || null,
		})),
	};
	submitting.value = true;
	try {
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_route", { payload });
		} else {
			await call("stabler.api.sfa.update_route", { name: f.name, payload });
		}
		drawerOpen.value = false;
		await load();
	} catch (err) {
		submitError.value = err?.message || t("Something went wrong");
	} finally {
		submitting.value = false;
	}
}

async function load() {
	if (!activeCompany.value) {
		rows.value = [];
		return;
	}
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.sfa.list_routes", {
			company: activeCompany.value,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, () => {
	form.value.company = activeCompany.value || "";
	load();
});
</script>

<template>
	<div class="card">
		<div class="card-header d-flex align-items-center gap-2">
			<h3 class="card-title mb-0">{{ t("Routes") }}</h3>
			<button type="button" class="btn btn-sm btn-success ms-auto" @click="openCreate">
				<i class="ti ti-plus me-1"></i>{{ t("New route") }}
			</button>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-route"
			:title="t('No routes yet')"
			:description="t('Define routes so field users know which outlets to visit each day.')"
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New route") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Route Code") }}</th>
						<th>{{ t("Route Name") }}</th>
						<th>{{ t("Field User") }}</th>
						<th>{{ t("Day of Week") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.route_code }}</td>
						<td>{{ r.route_name }}</td>
						<td>{{ r.field_user || "—" }}</td>
						<td>{{ r.day_of_week || t("Any") }}</td>
						<td>
							<span
								class="badge"
								:class="r.is_active ? 'bg-success-lt' : 'bg-secondary-lt'"
							>
								{{ r.is_active ? t("Active") : t("Inactive") }}
							</span>
						</td>
						<td class="text-end">
							<button
								type="button"
								class="btn btn-sm btn-link"
								@click="openEdit(r)"
							>
								<i class="ti ti-edit me-1"></i>{{ t("Edit") }}
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
							{{ drawerMode === "create" ? t("New route") : t("Edit route") }}
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
						<div v-if="detailLoading" class="text-secondary small mb-2">
							{{ t("Loading…") }}
						</div>
						<div class="row g-3">
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Route Code") }} <span class="text-danger">*</span>
								</label>
								<input
									v-model="form.route_code"
									type="text"
									class="form-control"
									:disabled="drawerMode === 'edit'"
									autofocus
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Route Name") }} <span class="text-danger">*</span>
								</label>
								<input v-model="form.route_name" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Company") }} <span class="text-danger">*</span>
								</label>
								<input
									v-model="form.company"
									type="text"
									class="form-control"
									:disabled="drawerMode === 'edit'"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Field User") }} <span class="text-danger">*</span>
								</label>
								<input
									v-model="form.field_user"
									type="text"
									class="form-control"
									:placeholder="t('user@example.com')"
								/>
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Day of Week") }}</label>
								<select v-model="form.day_of_week" class="form-select">
									<option v-for="d in DAYS" :key="d" :value="d">{{ t(d) }}</option>
								</select>
							</div>
							<div class="col-md-6 d-flex align-items-end">
								<label class="form-check">
									<input
										v-model="form.is_active"
										type="checkbox"
										class="form-check-input"
										:true-value="1"
										:false-value="0"
									/>
									<span class="form-check-label">{{ t("Active") }}</span>
								</label>
							</div>
						</div>

						<hr />

						<div class="d-flex align-items-center mb-2">
							<h6 class="text-uppercase text-secondary small mb-0">
								{{ t("Outlets") }}
							</h6>
							<button
								type="button"
								class="btn btn-sm btn-outline-primary ms-auto"
								@click="addOutletRow"
							>
								<i class="ti ti-plus me-1"></i>{{ t("Add outlet") }}
							</button>
						</div>
						<div v-if="!form.outlets.length" class="text-secondary small">
							{{ t("No outlets in this route yet.") }}
						</div>
						<div v-else class="table-responsive">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th style="width: 60px">{{ t("#") }}</th>
										<th>{{ t("Outlet") }}</th>
										<th style="width: 140px">{{ t("Planned Time") }}</th>
										<th style="width: 40px"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(row, idx) in form.outlets" :key="idx">
										<td>
											<input
												v-model.number="row.sequence"
												type="number"
												inputMode="numeric"
												class="form-control form-control-sm"
											/>
										</td>
										<td>
											<input
												v-model="row.outlet"
												type="text"
												class="form-control form-control-sm"
												:placeholder="t('Outlet code')"
											/>
										</td>
										<td>
											<input
												v-model="row.planned_visit_time"
												type="time"
												class="form-control form-control-sm"
											/>
										</td>
										<td class="text-end">
											<button
												type="button"
												class="btn btn-sm btn-link text-danger"
												:aria-label="t('Remove')"
												@click="removeOutletRow(idx)"
											>
												<i class="ti ti-x"></i>
											</button>
										</td>
									</tr>
								</tbody>
							</table>
						</div>
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
							:disabled="submitting || !form.route_code?.trim() || !form.route_name?.trim() || !form.company || !form.field_user?.trim()"
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
