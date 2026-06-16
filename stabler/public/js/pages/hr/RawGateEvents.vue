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
const processingStatusFilter = ref("");
const deviceFilter = ref("");
const busy = ref("");

// Devices for filter picker
const devices = ref([]);

const processingStatusOptions = computed(() => [
	{ value: "", label: t("All statuses") },
	{ value: "Pending", label: t("Pending") },
	{ value: "Processed", label: t("Processed") },
	{ value: "Duplicate", label: t("Duplicate") },
	{ value: "Unmatched", label: t("Unmatched") },
	{ value: "Error", label: t("Error") },
]);

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.external_event_id, r.device_user_id, r.matched_employee, r.device, r.error_message]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

async function loadDevices() {
	try {
		devices.value = await call("stabler.api.hr_gate_admin.list_gate_devices");
	} catch (e) {
		// non-fatal
	}
}

async function load() {
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr_gate_admin.list_raw_events", {
			processing_status: processingStatusFilter.value,
			device: deviceFilter.value,
			limit: 200,
			start: 0,
		});
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

onMounted(() => {
	loadDevices();
	load();
});

watch([processingStatusFilter, deviceFilter], load);

async function reprocess(r) {
	busy.value = r.name;
	try {
		const res = await call("stabler.api.hr_gate_admin.reprocess_raw_event", { name: r.name });
		// Update row in-place so the badge reflects new status immediately
		const idx = rows.value.findIndex((x) => x.name === r.name);
		if (idx !== -1 && res?.processing_status) {
			rows.value[idx] = { ...rows.value[idx], processing_status: res.processing_status };
		}
		toast.success(t("Event requeued for processing."));
	} catch (e) {
		toast.error(e?.message || String(e));
	} finally {
		busy.value = "";
	}
}
</script>

<template>
	<div class="card">
		<!-- Info banner: events are immutable -->
		<div class="card-header bg-azure-lt border-bottom py-2 px-3">
			<div class="d-flex align-items-center gap-2 small text-azure">
				<i class="ti ti-info-circle flex-shrink-0"></i>
				<span>
					{{ t("Raw gate events are immutable — they represent exactly what the device reported. Use Reprocess to re-run matching on unmatched or errored events.") }}
				</span>
			</div>
		</div>

		<ListToolbar
			v-model="search"
			:placeholder="t('Event ID, device user or employee…') + '  ⌘K'"
			:count="filteredRows.length"
		>
			<template #filters>
				<select
					v-model="processingStatusFilter"
					class="form-select form-select-sm"
					style="width:auto"
				>
					<option v-for="opt in processingStatusOptions" :key="opt.value" :value="opt.value">
						{{ opt.label }}
					</option>
				</select>

				<select
					v-model="deviceFilter"
					class="form-select form-select-sm"
					style="width:auto"
				>
					<option value="">{{ t("All devices") }}</option>
					<option v-for="d in devices" :key="d.name" :value="d.name">
						{{ d.device_name || d.name }}
					</option>
				</select>
			</template>
		</ListToolbar>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Event ID") }}</th>
						<th>{{ t("Device") }}</th>
						<th>{{ t("Device user") }}</th>
						<th>{{ t("Timestamp") }}</th>
						<th>{{ t("Direction") }}</th>
						<th>{{ t("Matched employee") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Error") }}</th>
						<th class="text-end"></th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="8" :cols="9" />
				<tbody v-else>
					<tr v-for="r in filteredRows" :key="r.name">
						<td class="font-monospace small">{{ r.external_event_id || r.name }}</td>
						<td class="small text-secondary">{{ r.device || "—" }}</td>
						<td class="font-monospace">{{ r.device_user_id || "—" }}</td>
						<td class="font-monospace small">{{ formatDateTime(r.timestamp) }}</td>
						<td>
							<span
								v-if="r.direction"
								class="badge"
								:class="r.direction === 'In' ? 'bg-green-lt' : r.direction === 'Out' ? 'bg-orange-lt' : 'bg-secondary-lt'"
							>
								{{ t(r.direction) }}
							</span>
							<span v-else class="text-secondary">—</span>
						</td>
						<td>
							<span v-if="r.matched_employee" class="fw-medium">{{ r.matched_employee }}</span>
							<span v-else class="text-secondary">—</span>
						</td>
						<td>
							<span class="badge" :class="getStatusBadgeClass('Raw Gate Event', r.processing_status)">
								{{ t(r.processing_status || "—") }}
							</span>
						</td>
						<td class="small text-danger" style="max-width:200px; white-space:normal">
							{{ r.error_message || "" }}
						</td>
						<td class="text-end">
							<button
								v-if="r.processing_status !== 'Processed'"
								class="btn btn-sm btn-outline-secondary"
								:disabled="busy === r.name"
								:title="t('Reprocess this event')"
								@click="reprocess(r)"
							>
								<i class="ti ti-refresh me-1"></i>{{ t("Reprocess") }}
							</button>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-topology-star-3"
			tone="secondary"
			:title="t('No raw events')"
			:subtitle="t('Events appear here as soon as a device or integration pushes data. Use the filters above to narrow results.')"
		/>
	</div>
</template>
