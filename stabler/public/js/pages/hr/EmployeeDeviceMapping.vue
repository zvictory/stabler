<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDate } from "../../composables/date.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import { useConfirm } from "../../composables/useConfirm.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";
import DateInput from "../../components/DateInput.vue";

const toast = useToast();
const { confirm } = useConfirm();

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");
const statusFilter = ref("");
const busy = ref("");

const statusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	{ value: "Active", label: t("Active") },
	{ value: "Inactive", label: t("Inactive") },
]);

// Devices for picker
const devices = ref([]);
const devicesLoaded = ref(false);

async function loadDevices() {
	if (devicesLoaded.value) return;
	try {
		devices.value = await call("stabler.api.hr_gate_admin.list_gate_devices");
		devicesLoaded.value = true;
	} catch (e) {
		// non-fatal — device list is optional UX
	}
}

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	return rows.value.filter((r) => {
		const matchQ = !q ||
			[r.employee, r.employee_name, r.device_user_id, r.phone, r.device]
				.filter(Boolean)
				.some((v) => String(v).toLowerCase().includes(q));
		const matchStatus = !statusFilter.value || r.status === statusFilter.value;
		return matchQ && matchStatus;
	});
});

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr_gate_admin.list_device_mappings", {
			search: search.value,
			status: statusFilter.value,
			limit: 500,
		});
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);
watch(statusFilter, load);

// Debounce search
let searchTimer = null;
watch(search, () => {
	clearTimeout(searchTimer);
	searchTimer = setTimeout(load, 300);
});

// ----- Drawer (create / edit) -----
const drawerOpen = ref(false);
const submitting = ref(false);
const formError = ref("");
const isEdit = ref(false);

function blankForm() {
	return {
		name: "",
		employee: "",
		employee_name: "",
		device: "",
		device_user_id: "",
		phone: "",
		status: "Active",
		active_from: "",
		active_to: "",
	};
}

const form = ref(blankForm());

function openNew() {
	form.value = blankForm();
	formError.value = "";
	isEdit.value = false;
	drawerOpen.value = true;
	loadDevices();
}

function openEdit(r) {
	form.value = {
		name: r.name,
		employee: r.employee || "",
		employee_name: r.employee_name || "",
		device: r.device || "",
		device_user_id: r.device_user_id || "",
		phone: r.phone || "",
		status: r.status || "Active",
		active_from: r.active_from || "",
		active_to: r.active_to || "",
	};
	formError.value = "";
	isEdit.value = true;
	drawerOpen.value = true;
	loadDevices();
}

function closeDrawer() {
	drawerOpen.value = false;
}

async function save() {
	formError.value = "";
	if (!form.value.employee.trim()) {
		formError.value = t("Employee ID is required.");
		return;
	}
	if (!form.value.device_user_id.trim()) {
		formError.value = t("Device user ID is required.");
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.hr_gate_admin.save_device_mapping", { ...form.value });
		toast.success(isEdit.value ? t("Mapping updated.") : t("Mapping created."));
		closeDrawer();
		await load();
	} catch (e) {
		formError.value = e?.message || String(e);
	} finally {
		submitting.value = false;
	}
}

async function deleteMapping(r) {
	const ok = await confirm({
		title: t("Delete mapping"),
		body: t("Remove the link between {0} and device user {1}? This will not affect attendance records already generated.")
			.replace("{0}", r.employee_name || r.employee)
			.replace("{1}", r.device_user_id),
		danger: true,
		confirmLabel: t("Delete"),
	});
	if (!ok) return;
	busy.value = r.name;
	try {
		await call("stabler.api.hr_gate_admin.delete_device_mapping", { name: r.name });
		toast.success(t("Mapping deleted."));
		await load();
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Employee, device ID or phone…') + '  ⌘K'"
			:count="filteredRows.length"
			:primary-label="t('New mapping')"
			primary-icon="ti-plus"
			@primary-click="openNew"
		>
			<template #filters>
				<select
					v-model="statusFilter"
					class="form-select form-select-sm"
					style="width:auto"
				>
					<option v-for="opt in statusOptions" :key="opt.value" :value="opt.value">
						{{ opt.label }}
					</option>
				</select>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Employee") }}</th>
						<th>{{ t("Device") }}</th>
						<th>{{ t("Device user ID") }}</th>
						<th>{{ t("Phone") }}</th>
						<th>{{ t("Active from") }}</th>
						<th>{{ t("Active to") }}</th>
						<th>{{ t("Status") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="6" :cols="8" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name">
						<td>
							<div class="fw-medium">{{ r.employee_name || r.employee }}</div>
							<div class="small text-secondary font-monospace">{{ r.employee }}</div>
						</td>
						<td class="text-secondary small">{{ r.device || "—" }}</td>
						<td class="font-monospace">{{ r.device_user_id || "—" }}</td>
						<td class="font-monospace">{{ r.phone || "—" }}</td>
						<td class="font-monospace small">{{ formatDate(r.active_from) }}</td>
						<td class="font-monospace small">{{ formatDate(r.active_to) }}</td>
						<td>
							<span class="badge" :class="getStatusBadgeClass('Device Mapping', r.status)">
								{{ t(r.status || "—") }}
							</span>
						</td>
						<td class="text-end">
							<div class="btn-list justify-content-end">
								<button
									class="btn btn-sm btn-ghost-secondary"
									:title="t('Edit')"
									@click="openEdit(r)"
								>
									<i class="ti ti-pencil"></i>
								</button>
								<button
									class="btn btn-sm btn-ghost-danger"
									:title="t('Delete')"
									:disabled="busy === r.name"
									@click="deleteMapping(r)"
								>
									<i class="ti ti-trash"></i>
								</button>
							</div>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-user-scan"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No employee–device mappings')"
			:subtitle="t('Map employees to device user IDs so gate events resolve to attendance records.')"
		>
			<template #actions>
				<button class="btn btn-primary" @click="openNew">
					<i class="ti ti-plus me-1"></i>{{ t("New mapping") }}
				</button>
			</template>
		</EmptyState>
	</div>

	<!-- Mapping drawer -->
	<div v-if="drawerOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="width:460px">
		<div class="offcanvas-header border-bottom">
			<h5 class="offcanvas-title">
				{{ isEdit ? t("Edit mapping") : t("New employee–device mapping") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDrawer"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="formError" class="alert alert-danger">{{ formError }}</div>

			<p class="text-secondary small mb-3">
				{{ t("Link an ERPNext employee to a TimePay (or other device) user ID. When a raw gate event arrives with this device user ID, it will be matched to this employee automatically.") }}
			</p>

			<div class="mb-3">
				<label class="form-label">{{ t("Employee ID") }} *</label>
				<input
					v-model="form.employee"
					type="text"
					class="form-control"
					:placeholder="t('e.g. EMP-00042')"
				/>
				<div class="form-text">{{ t("ERPNext Employee docname (EMP-XXXXX).") }}</div>
			</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Employee name") }}</label>
				<input
					v-model="form.employee_name"
					type="text"
					class="form-control"
					:placeholder="t('Full name (optional — filled automatically on save)')"
				/>
			</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Device user ID") }} *</label>
				<input
					v-model="form.device_user_id"
					type="text"
					class="form-control"
					:placeholder="t('ID as it appears in raw gate events')"
				/>
				<div class="form-text">{{ t("This must match exactly the value in raw events (TimePay user ID, badge code, etc.).") }}</div>
			</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Gate device") }}</label>
				<select v-model="form.device" class="form-select">
					<option value="">{{ t("— Any device —") }}</option>
					<option v-for="d in devices" :key="d.name" :value="d.name">
						{{ d.device_name || d.name }}
					</option>
				</select>
				<div class="form-text">{{ t("Restrict this mapping to a specific reader, or leave blank to match all devices.") }}</div>
			</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Phone") }}</label>
				<input
					v-model="form.phone"
					type="text"
					class="form-control"
					:placeholder="t('+998 XX XXX XX XX')"
				/>
			</div>

			<div class="row g-3 mb-3">
				<div class="col-6">
					<label class="form-label">{{ t("Active from") }}</label>
					<DateInput v-model="form.active_from" />
				</div>
				<div class="col-6">
					<label class="form-label">{{ t("Active to") }}</label>
					<DateInput v-model="form.active_to" />
					<div class="form-text">{{ t("Leave blank for open-ended.") }}</div>
				</div>
			</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Status") }}</label>
				<select v-model="form.status" class="form-select">
					<option value="Active">{{ t("Active") }}</option>
					<option value="Inactive">{{ t("Inactive") }}</option>
				</select>
			</div>
		</div>
		<div class="offcanvas-footer border-top p-3 d-flex gap-2 justify-content-end">
			<button type="button" class="btn btn-link link-secondary" @click="closeDrawer">
				{{ t("Cancel") }}
			</button>
			<button type="button" class="btn btn-primary" :disabled="submitting" @click="save">
				<i class="ti ti-device-floppy me-1"></i>{{ t("Save mapping") }}
			</button>
		</div>
	</div>
	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
</template>
