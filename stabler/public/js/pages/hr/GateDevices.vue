<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { formatDateTime } from "../../composables/date.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import { useToast } from "../../composables/useToast.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const toast = useToast();

const loading = ref(false);
const error = ref("");
const rows = ref([]);
const search = ref("");

const integrationOptions = computed(() => [
	{ value: "Timepay", label: t("Timepay") },
	{ value: "Manual", label: t("Manual") },
	{ value: "Excel", label: t("Excel") },
	{ value: "Other", label: t("Other") },
]);

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.device_name, r.integration_type, r.branch, r.status]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr_gate_admin.list_gate_devices");
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(load);

// ----- Drawer (create / edit) -----
const drawerOpen = ref(false);
const submitting = ref(false);
const formError = ref("");
const isEdit = ref(false);

function blankForm() {
	return {
		name: "",
		device_name: "",
		integration_type: "Timepay",
		enabled: true,
		branch: "",
		status: "Active",
	};
}

const form = ref(blankForm());

function openNew() {
	form.value = blankForm();
	formError.value = "";
	isEdit.value = false;
	drawerOpen.value = true;
}

function openEdit(r) {
	form.value = {
		name: r.name,
		device_name: r.device_name || "",
		integration_type: r.integration_type || "Timepay",
		enabled: !!r.enabled,
		branch: r.branch || "",
		status: r.status || "Active",
	};
	formError.value = "";
	isEdit.value = true;
	drawerOpen.value = true;
}

function closeDrawer() {
	drawerOpen.value = false;
}

async function save() {
	formError.value = "";
	if (!form.value.device_name.trim()) {
		formError.value = t("Device name is required.");
		return;
	}
	submitting.value = true;
	try {
		await call("stabler.api.hr_gate_admin.save_gate_device", {
			payload: JSON.stringify({ ...form.value, enabled: form.value.enabled ? 1 : 0 }),
		});
		toast.success(isEdit.value ? t("Device updated.") : t("Device created."));
		closeDrawer();
		await load();
	} catch (e) {
		formError.value = e?.message || String(e);
	} finally {
		submitting.value = false;
	}
}

watch(search, () => {}); // reactive — filteredRows handles it
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Device name or branch…') + '  ⌘K'"
			:count="filteredRows.length"
			:primary-label="t('New device')"
			primary-icon="ti-plus"
			@primary-click="openNew"
		/>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Device name") }}</th>
						<th>{{ t("Integration") }}</th>
						<th>{{ t("Branch") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Last sync") }}</th>
						<th>{{ t("Enabled") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="7" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name">
						<td class="fw-medium">{{ r.device_name || r.name }}</td>
						<td>{{ r.integration_type || "—" }}</td>
						<td>{{ r.branch || "—" }}</td>
						<td>
							<span class="badge" :class="getStatusBadgeClass('Gate Device', r.status)">
								{{ t(r.status || "—") }}
							</span>
						</td>
						<td class="text-secondary small font-monospace">
							{{ formatDateTime(r.last_sync) }}
						</td>
						<td>
							<span v-if="r.enabled" class="badge bg-green-lt">{{ t("Yes") }}</span>
							<span v-else class="badge bg-secondary-lt">{{ t("No") }}</span>
						</td>
						<td class="text-end">
							<button
								class="btn btn-sm btn-ghost-secondary"
								:title="t('Edit')"
								@click="openEdit(r)"
							>
								<i class="ti ti-pencil"></i>
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-device-tablet"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No gate devices')"
			:subtitle="t('Register a hardware reader or integration to start collecting raw attendance events.')"
		>
			<template #actions>
				<button class="btn btn-primary" @click="openNew">
					<i class="ti ti-plus me-1"></i>{{ t("New device") }}
				</button>
			</template>
		</EmptyState>
	</div>

	<!-- Device drawer -->
	<div v-if="drawerOpen" class="offcanvas offcanvas-end show" tabindex="-1" style="width:420px">
		<div class="offcanvas-header border-bottom">
			<h5 class="offcanvas-title">
				{{ isEdit ? t("Edit device") : t("New gate device") }}
			</h5>
			<button type="button" class="btn-close" @click="closeDrawer"></button>
		</div>
		<div class="offcanvas-body">
			<div v-if="formError" class="alert alert-danger">{{ formError }}</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Device name") }} *</label>
				<input
					v-model="form.device_name"
					type="text"
					class="form-control"
					:placeholder="t('e.g. Main entrance reader')"
				/>
			</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Integration type") }}</label>
				<select v-model="form.integration_type" class="form-select">
					<option v-for="opt in integrationOptions" :key="opt.value" :value="opt.value">
						{{ opt.label }}
					</option>
				</select>
			</div>

			<div class="mb-3">
				<label class="form-label">{{ t("Branch") }}</label>
				<input
					v-model="form.branch"
					type="text"
					class="form-control"
					:placeholder="t('Office branch or location')"
				/>
			</div>

			<div class="mb-3">
				<div class="form-check form-switch">
					<input
						v-model="form.enabled"
						class="form-check-input"
						type="checkbox"
						role="switch"
						id="deviceEnabled"
					/>
					<label class="form-check-label" for="deviceEnabled">{{ t("Enabled") }}</label>
				</div>
			</div>
		</div>
		<div class="offcanvas-footer border-top p-3 d-flex gap-2 justify-content-end">
			<button type="button" class="btn btn-link link-secondary" @click="closeDrawer">
				{{ t("Cancel") }}
			</button>
			<button type="button" class="btn btn-primary" :disabled="submitting" @click="save">
				<i class="ti ti-device-floppy me-1"></i>{{ t("Save device") }}
			</button>
		</div>
	</div>
	<div v-if="drawerOpen" class="offcanvas-backdrop fade show" @click="closeDrawer"></div>
</template>
