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
			<table class="table table-vcenter card-table">
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
					<tr v-for="r in rows" :key="r.name">
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
</template>
