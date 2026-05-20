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
watch(activeCompany, load);
</script>

<template>
	<div class="card">
		<div class="card-header">
			<h3 class="card-title mb-0">{{ t("Field Users") }}</h3>
		</div>

		<div v-if="loading" class="card-body text-secondary">{{ t("Loading…") }}</div>
		<div v-else-if="error" class="card-body text-danger">{{ error }}</div>
		<EmptyState
			v-else-if="!rows.length"
			icon="ti-user-check"
			:title="t('No field users yet')"
			:description="t('Field users represent sales reps who execute visits and own van stock.')"
		/>
		<div v-else class="table-responsive">
			<table class="table table-vcenter card-table">
				<thead>
					<tr>
						<th>{{ t("User") }}</th>
						<th>{{ t("Default Warehouse") }}</th>
						<th>{{ t("Default Route") }}</th>
						<th>{{ t("Mobile Phone") }}</th>
						<th>{{ t("Status") }}</th>
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
					</tr>
				</tbody>
			</table>
		</div>
	</div>
</template>
