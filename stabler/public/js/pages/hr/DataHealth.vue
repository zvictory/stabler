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
const data = ref(null);

async function load() {
	if (!activeCompany.value) return;
	loading.value = true;
	try {
		data.value = await call("stabler.api.hr_overview.data_health", { company: activeCompany.value });
	} catch {
		data.value = null;
	} finally {
		loading.value = false;
	}
}
onMounted(load);
watch(activeCompany, load);

const sections = computed(() => {
	const d = data.value;
	if (!d) return [];
	const out = [];
	if (d.can_see_money) {
		out.push({ key: "base", icon: "ti-cash", tone: "danger", title: t("Base salary = 0"), hint: t("Payroll outputs zero until a salary is entered."), rows: d.base_salary_zero || [] });
	}
	out.push({ key: "profile", icon: "ti-user-question", tone: "warning", title: t("Profile gaps"), hint: t("Unassigned department or position."), rows: d.profile_gaps || [] });
	out.push({ key: "comp", icon: "ti-settings", tone: "secondary", title: t("Missing work mode / region"), hint: t("Needed for correct allowances and overtime."), rows: d.comp_config_gaps || [] });
	return out;
});

const allClean = computed(() => sections.value.length && sections.value.every((s) => !s.rows.length));
const toneBadge = (tone) => ({ danger: "bg-red-lt", warning: "bg-yellow-lt", secondary: "bg-secondary-lt" }[tone] || "bg-secondary-lt");
const toneText = (tone) => ({ danger: "text-danger", warning: "text-warning", secondary: "text-secondary" }[tone] || "");
</script>

<template>
	<div v-if="loading" class="text-center py-5"><div class="spinner-border text-primary"></div></div>

	<template v-else-if="data">
		<div class="mb-3">
			<h2 class="m-0">{{ t("Data health") }}</h2>
			<div class="text-secondary small">{{ t("Records that block payroll or look unfinished. Fix at the source.") }}</div>
		</div>

		<EmptyState
			v-if="allClean"
			icon="ti-circle-check"
			accentIcon="ti-check"
			tone="success"
			:title="t('Everything looks complete')"
			:subtitle="t('No data gaps found for this company.')"
		/>

		<div v-else class="row g-3">
			<div v-for="s in sections" :key="s.key" class="col-lg-6">
				<div class="card h-100">
					<div class="card-header py-2">
						<h3 class="card-title m-0"><i class="ti me-2" :class="[s.icon, toneText(s.tone)]"></i>{{ s.title }}</h3>
						<span class="badge ms-auto" :class="s.rows.length ? toneBadge(s.tone) : 'bg-green-lt'">{{ s.rows.length }}</span>
					</div>
					<div class="card-body py-2 text-secondary small">{{ s.hint }}</div>
					<div v-if="s.rows.length" class="list-group list-group-flush" style="max-height: 340px; overflow-y: auto">
						<RouterLink
							v-for="r in s.rows"
							:key="r.employee"
							:to="`/hr/employees/${encodeURIComponent(r.employee)}`"
							class="list-group-item list-group-item-action d-flex align-items-center gap-2"
						>
							<div class="flex-fill">
								<div class="fw-semibold">{{ r.employee_name }}</div>
								<div class="text-secondary small">{{ r.department || t("No department") }}</div>
							</div>
							<span v-for="m in (r.missing || [])" :key="m" class="badge bg-secondary-lt">{{ t(m) }}</span>
							<span class="small text-primary">{{ t("Fix") }} <i class="ti ti-arrow-right"></i></span>
						</RouterLink>
					</div>
					<div v-else class="card-body text-success small"><i class="ti ti-check me-1"></i>{{ t("None") }}</div>
				</div>
			</div>
		</div>
	</template>

	<div v-else class="alert alert-warning">{{ t("Could not load data health.") }}</div>
</template>
