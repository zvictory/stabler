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
const postingDate = ref("");
const status = ref("");

const statusBadge = (s) => {
	if (s === "Reconciled") return "bg-success-lt";
	if (s === "Dispatched") return "bg-info-lt";
	if (s === "Returned") return "bg-warning-lt";
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
		rows.value = await call("stabler.api.sfa.list_van_stock", {
			company: activeCompany.value,
			posting_date: postingDate.value || undefined,
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
watch([postingDate, status], load);
</script>

<template>
	<div class="card">
		<div class="card-header d-flex flex-wrap gap-2 align-items-center">
			<h3 class="card-title mb-0">{{ t("Van Stock") }}</h3>
			<div class="ms-auto d-flex gap-2">
				<input
					v-model="postingDate"
					type="date"
					class="form-control form-control-sm"
					:aria-label="t('Posting date')"
				/>
				<select v-model="status" class="form-select form-select-sm" :aria-label="t('Status')">
					<option value="">{{ t("All statuses") }}</option>
					<option value="Loaded">{{ t("Loaded") }}</option>
					<option value="Dispatched">{{ t("Dispatched") }}</option>
					<option value="Returned">{{ t("Returned") }}</option>
					<option value="Reconciled">{{ t("Reconciled") }}</option>
				</select>
			</div>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-truck-loading"
			:title="t('No van stock yet')"
			:description="t('Van stock tracks what each field user has loaded for the day.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("Reference") }}</th>
						<th>{{ t("Field User") }}</th>
						<th>{{ t("Posting Date") }}</th>
						<th>{{ t("Warehouse") }}</th>
						<th>{{ t("Status") }}</th>
					</tr>
				</thead>
				<tbody>
					<tr v-for="r in rows" :key="r.name">
						<td>{{ r.name }}</td>
						<td>{{ r.field_user }}</td>
						<td>{{ r.posting_date || "—" }}</td>
						<td>{{ r.warehouse || "—" }}</td>
						<td><span class="badge" :class="statusBadge(r.status)">{{ t(r.status) }}</span></td>
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
