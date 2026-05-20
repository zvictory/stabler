<script setup>
import { computed, onMounted, ref, watch } from "vue";
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
const plannedDate = ref("");
const status = ref("");

const STEP_TYPES = ["GREET", "MERCHANDISING", "ORDER", "PHOTO", "PAYMENT", "SURVEY", "FAREWELL"];
const STEP_STATUSES = ["Pending", "Done", "Skipped"];
const VISIT_STATUSES = ["Planned", "InProgress", "Completed", "Skipped"];

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	{ value: "Planned", label: t("Planned") },
	{ value: "InProgress", label: t("In progress") },
	{ value: "Completed", label: t("Completed") },
	{ value: "Skipped", label: t("Skipped") },
]);

const statusBadge = (s) => {
	if (s === "Completed") return "bg-success-lt";
	if (s === "InProgress") return "bg-info-lt";
	if (s === "Skipped") return "bg-warning-lt";
	return "bg-secondary-lt";
};

const drawerOpen = ref(false);
const drawerMode = ref("create");
const submitting = ref(false);
const submitError = ref("");

function blankVisit() {
	return {
		name: "",
		outlet: "",
		route: "",
		field_user: "",
		company: activeCompany.value || "",
		planned_date: "",
		status: "Planned",
		notes: "",
		skip_reason: "",
		steps: [],
	};
}

const form = ref(blankVisit());

function openCreate() {
	form.value = blankVisit();
	drawerMode.value = "create";
	submitError.value = "";
	drawerOpen.value = true;
}

function openEdit(row) {
	// Fetch full doc (list view omits child rows + notes)
	loadDetail(row.name);
}

async function loadDetail(name) {
	submitError.value = "";
	drawerMode.value = "edit";
	drawerOpen.value = true;
	submitting.value = true;
	try {
		const doc = await call("stabler.api.sfa.get_visit", { name });
		form.value = {
			name: doc.name,
			outlet: doc.outlet || "",
			route: doc.route || "",
			field_user: doc.field_user || "",
			company: doc.company || activeCompany.value || "",
			planned_date: doc.planned_date || "",
			status: doc.status || "Planned",
			notes: doc.notes || "",
			skip_reason: doc.skip_reason || "",
			steps: (doc.steps || []).map((s) => ({
				step_type: s.step_type || "",
				status: s.status || "Pending",
				notes: s.notes || "",
				reference_doctype: s.reference_doctype || "",
				reference_name: s.reference_name || "",
			})),
		};
	} catch (e) {
		submitError.value = e?.message || t("Failed to load visit.");
	} finally {
		submitting.value = false;
	}
}

function closeDrawer() {
	if (submitting.value) return;
	drawerOpen.value = false;
}

function addStep() {
	form.value.steps.push({
		step_type: "",
		status: "Pending",
		notes: "",
		reference_doctype: "",
		reference_name: "",
	});
}

function removeStep(idx) {
	form.value.steps.splice(idx, 1);
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.outlet?.trim()) return (submitError.value = t("Outlet is required."));
	if (!f.field_user?.trim()) return (submitError.value = t("Field User is required."));
	if (!f.company?.trim()) return (submitError.value = t("Company is required."));
	for (let i = 0; i < f.steps.length; i++) {
		if (!f.steps[i].step_type) {
			return (submitError.value = t("Step #{0}: type is required.").replace("{0}", String(i + 1)));
		}
	}
	submitting.value = true;
	try {
		const payload = {
			outlet: f.outlet.trim(),
			route: f.route || null,
			field_user: f.field_user.trim(),
			company: f.company.trim(),
			planned_date: f.planned_date || null,
			status: f.status,
			notes: f.notes || null,
			skip_reason: f.skip_reason || null,
			steps: f.steps.map((s) => ({
				step_type: s.step_type,
				status: s.status || "Pending",
				notes: s.notes || null,
				reference_doctype: s.reference_doctype || null,
				reference_name: s.reference_name || null,
			})),
		};
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_visit", payload);
		} else {
			await call("stabler.api.sfa.update_visit", { name: f.name, payload });
		}
		drawerOpen.value = false;
		await load();
	} catch (e) {
		submitError.value = e?.message || t("Failed to save visit.");
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
		rows.value = await call("stabler.api.sfa.list_visits", {
			company: activeCompany.value,
			planned_date: plannedDate.value || undefined,
			status: status.value || undefined,
		});
	} catch (e) {
		error.value = e?.message || t("Something went wrong");
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(activeCompany, load);
watch([plannedDate, status], load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Visits") }}</h3>
			<div class="ms-auto d-flex gap-2">
				<input
					v-model="plannedDate"
					type="date"
					class="form-control form-control-sm"
					:aria-label="t('Planned date')"
				/>
				<select v-model="status" class="form-select form-select-sm" :aria-label="t('Status')">
					<option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
						{{ opt.label }}
					</option>
				</select>
				<button type="button" class="btn btn-sm btn-success" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New Visit") }}
				</button>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-map-pin-check"
			:title="t('No visits yet')"
			:description="t('Visits appear once they are planned from a route or created manually.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("Visit") }}</th>
						<th>{{ t("Outlet") }}</th>
						<th>{{ t("Field User") }}</th>
						<th>{{ t("Planned Date") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Checked in") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr
						v-for="r in rows"
						:key="r.name"
						style="cursor: pointer"
						@click="openEdit(r)"
					>
						<td>{{ r.name }}</td>
						<td>{{ r.outlet }}</td>
						<td>{{ r.field_user || "—" }}</td>
						<td>{{ r.planned_date || "—" }}</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ t(r.status) }}</span></td>
						<td>{{ r.check_in_at || "—" }}</td>
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
							{{ drawerMode === "create" ? t("New Visit") : t("Edit Visit") }}
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
								<label class="form-label">
									{{ t("Outlet") }} <span class="text-danger">*</span>
								</label>
								<input v-model="form.outlet" type="text" class="form-control" autofocus />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Route") }}</label>
								<input v-model="form.route" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Field User") }} <span class="text-danger">*</span>
								</label>
								<input v-model="form.field_user" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">
									{{ t("Company") }} <span class="text-danger">*</span>
								</label>
								<input v-model="form.company" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Planned Date") }}</label>
								<input v-model="form.planned_date" type="date" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Status") }}</label>
								<select v-model="form.status" class="form-select">
									<option v-for="s in VISIT_STATUSES" :key="s" :value="s">{{ t(s) }}</option>
								</select>
							</div>
							<div class="col-12">
								<label class="form-label">{{ t("Notes") }}</label>
								<textarea v-model="form.notes" class="form-control" rows="2"></textarea>
							</div>
							<div v-if="form.status === 'Skipped'" class="col-12">
								<label class="form-label">{{ t("Skip Reason") }}</label>
								<textarea v-model="form.skip_reason" class="form-control" rows="2"></textarea>
							</div>
						</div>

						<hr class="my-3" />
						<div class="d-flex align-items-center mb-2">
							<h6 class="m-0">{{ t("Steps") }}</h6>
							<button
								type="button"
								class="btn btn-sm btn-outline-primary ms-auto"
								@click="addStep"
							>
								<i class="ti ti-plus me-1"></i>{{ t("Add row") }}
							</button>
						</div>
						<div v-if="!form.steps.length" class="text-secondary small mb-2">
							{{ t("No steps yet.") }}
						</div>
						<div v-else class="table-responsive">
							<table class="table table-sm table-vcenter">
								<thead>
									<tr>
										<th style="width: 24px">#</th>
										<th>{{ t("Step") }}</th>
										<th>{{ t("Status") }}</th>
										<th>{{ t("Notes") }}</th>
										<th style="width: 40px"></th>
									</tr>
								</thead>
								<tbody>
									<tr v-for="(s, idx) in form.steps" :key="idx">
										<td class="text-secondary">{{ idx + 1 }}</td>
										<td>
											<select v-model="s.step_type" class="form-select form-select-sm">
												<option value="">—</option>
												<option v-for="st in STEP_TYPES" :key="st" :value="st">
													{{ t(st) }}
												</option>
											</select>
										</td>
										<td>
											<select v-model="s.status" class="form-select form-select-sm">
												<option v-for="ss in STEP_STATUSES" :key="ss" :value="ss">
													{{ t(ss) }}
												</option>
											</select>
										</td>
										<td>
											<input
												v-model="s.notes"
												type="text"
												class="form-control form-control-sm"
											/>
										</td>
										<td>
											<button
												type="button"
												class="btn btn-sm btn-link link-danger p-0"
												:aria-label="t('Remove row')"
												@click="removeStep(idx)"
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
							:disabled="
								submitting ||
								!form.outlet?.trim() ||
								!form.field_user?.trim() ||
								!form.company?.trim()
							"
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
