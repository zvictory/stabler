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

function blankFieldUser() {
	return {
		user: "",
		company: activeCompany.value || "",
		is_active: 1,
		default_warehouse: "",
		default_route: "",
		mobile_phone: "",
	};
}

const drawerOpen = ref(false);
const drawerMode = ref("create");
const form = ref(blankFieldUser());
const submitting = ref(false);
const submitError = ref("");

function openCreate() {
	form.value = blankFieldUser();
	drawerMode.value = "create";
	submitError.value = "";
	drawerOpen.value = true;
}

function openEdit(row) {
	form.value = JSON.parse(JSON.stringify(row));
	drawerMode.value = "edit";
	submitError.value = "";
	drawerOpen.value = true;
}

function closeDrawer() {
	if (submitting.value) return;
	drawerOpen.value = false;
	submitError.value = "";
}

async function submitDrawer() {
	submitError.value = "";
	const f = form.value;
	if (!f.user?.trim()) {
		submitError.value = t("User is required.");
		return;
	}
	if (!f.company) {
		submitError.value = t("Company is required.");
		return;
	}
	const payload = {
		user: f.user.trim(),
		company: f.company,
		is_active: f.is_active ? 1 : 0,
		default_warehouse: f.default_warehouse || null,
		default_route: f.default_route || null,
		mobile_phone: f.mobile_phone || null,
	};
	submitting.value = true;
	try {
		if (drawerMode.value === "create") {
			await call("stabler.api.sfa.create_field_user", { payload });
		} else {
			await call("stabler.api.sfa.update_field_user", { name: f.name, payload });
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
		rows.value = await call("stabler.api.sfa.list_field_users", {
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
			<h3 class="card-title mb-0">{{ t("Field Users") }}</h3>
			<button type="button" class="btn btn-sm btn-success ms-auto" @click="openCreate">
				<i class="ti ti-plus me-1"></i>{{ t("New field user") }}
			</button>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-user-check"
			:title="t('No field users yet')"
			:description="t('Field users represent sales reps who execute visits and own van stock.')"
		>
			<template #actions>
				<button type="button" class="btn btn-primary" @click="openCreate">
					<i class="ti ti-plus me-1"></i>{{ t("New field user") }}
				</button>
			</template>
		</EmptyState>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table table-hover">
				<thead>
					<tr>
						<th>{{ t("User") }}</th>
						<th>{{ t("Default Warehouse") }}</th>
						<th>{{ t("Default Route") }}</th>
						<th>{{ t("Mobile Phone") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.user }}</td>
						<td>{{ r.default_warehouse || "—" }}</td>
						<td>{{ r.default_route || "—" }}</td>
						<td>{{ r.mobile_phone || "—" }}</td>
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
			<div class="modal-dialog modal-dialog-centered" role="document">
				<div class="modal-content">
					<div class="modal-header">
						<h5 class="modal-title">
							{{ drawerMode === "create" ? t("New field user") : t("Edit field user") }}
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
							<div class="col-12">
								<label class="form-label">
									{{ t("User") }} <span class="text-danger">*</span>
								</label>
								<input
									v-model="form.user"
									type="text"
									class="form-control"
									:disabled="drawerMode === 'edit'"
									:placeholder="t('user@example.com')"
									autofocus
								/>
							</div>
							<div class="col-12">
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
								<label class="form-label">{{ t("Default Warehouse") }}</label>
								<input v-model="form.default_warehouse" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Default Route") }}</label>
								<input v-model="form.default_route" type="text" class="form-control" />
							</div>
							<div class="col-md-6">
								<label class="form-label">{{ t("Mobile Phone") }}</label>
								<input v-model="form.mobile_phone" type="tel" class="form-control" />
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
							:disabled="submitting || !form.user?.trim() || !form.company"
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
