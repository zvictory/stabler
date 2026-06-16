<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRouter } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import { getStatusBadgeClass } from "../../composables/status.js";
import EmptyState from "../../components/EmptyState.vue";
import ListToolbar from "../../components/ListToolbar.vue";
import SkeletonRows from "../../components/SkeletonRows.vue";

const session = useSession();
const { activeCompany } = storeToRefs(session);
const router = useRouter();

const loading = ref(false);
const error = ref("");
const search = ref("");
const rows = ref([]);

const filteredRows = computed(() => {
	const q = search.value.trim().toLowerCase();
	if (!q) return rows.value;
	return rows.value.filter((r) =>
		[r.rule_set_name, r.company, r.name]
			.filter(Boolean)
			.some((v) => String(v).toLowerCase().includes(q)),
	);
});

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	error.value = "";
	try {
		rows.value = await call("stabler.api.hr_attendance.list_rule_sets", {
			company: activeCompany.value,
		});
	} catch (e) {
		error.value = e?.message || String(e);
		rows.value = [];
	} finally {
		loading.value = false;
	}
}

function openRow(r) {
	router.push(`/hr/attendance-rules/${r.name}`);
}

function openNew() {
	router.push("/hr/attendance-rules/new");
}

watch(activeCompany, load);
onMounted(load);
</script>

<template>
	<div class="card">
		<ListToolbar
			v-model="search"
			:placeholder="t('Rule set name or company…') + '  ⌘K'"
			:count="filteredRows.length"
			:primary-label="t('New rule set')"
			primary-icon="ti-plus"
			@primary-click="openNew"
		/>

		<div v-if="error" class="alert alert-danger m-3">{{ error }}</div>

		<div class="table-responsive">
			<table class="table card-table table-vcenter">
				<thead>
					<tr>
						<th>{{ t("Name") }}</th>
						<th>{{ t("Company") }}</th>
						<th>{{ t("Status") }}</th>
						<th>{{ t("Default") }}</th>
					</tr>
				</thead>
				<SkeletonRows v-if="loading" :rows="5" :cols="4" />
				<tbody v-else>
					<tr
						v-for="r in filteredRows"
						:key="r.name"
						style="cursor: pointer"
						@click="openRow(r)"
					>
						<td class="fw-medium">{{ r.rule_set_name }}</td>
						<td class="text-secondary">{{ r.company }}</td>
						<td>
							<span
								class="badge"
								:class="r.enabled ? 'bg-green-lt' : 'bg-secondary-lt'"
							>
								{{ r.enabled ? t("Enabled") : t("Disabled") }}
							</span>
						</td>
						<td>
							<span v-if="r.is_default" class="badge bg-blue-lt">
								{{ t("Default") }}
							</span>
							<span v-else class="text-secondary">—</span>
						</td>
					</tr>
				</tbody>
			</table>
		</div>

		<EmptyState
			v-if="!loading && filteredRows.length === 0"
			icon="ti-adjustments"
			accentIcon="ti-plus"
			tone="primary"
			:title="t('No rule sets')"
			:subtitle="t('Create an attendance rule set to define late fees, overtime, and night shift premiums.')"
		>
			<template #actions>
				<button class="btn btn-primary" @click="openNew">
					<i class="ti ti-plus me-1"></i>{{ t("New rule set") }}
				</button>
			</template>
		</EmptyState>
	</div>
</template>
