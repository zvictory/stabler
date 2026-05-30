<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";

const route = useRoute();
const session = useSession();
const { activeCompany } = storeToRefs(session);

const tabs = computed(() => [
	{ name: "hr-employees", path: "/hr/employees", label: t("Employees"), icon: "ti-users" },
	{ name: "hr-org", path: "/hr/org", label: t("Positions"), icon: "ti-sitemap" },
	{ name: "hr-attendance", path: "/hr/attendance", label: t("Attendance"), icon: "ti-calendar-event" },
	{ name: "hr-leave", path: "/hr/leave", label: t("Leave"), icon: "ti-beach" },
	{ name: "hr-payroll", path: "/hr/payroll", label: t("Payroll"), icon: "ti-cash" },
]);
const activeTab = computed(() => route.name);

const overview = ref(null);
async function loadOverview() {
	if (!activeCompany.value) return;
	try {
		overview.value = await call("stabler.api.hr.hr_overview", { company: activeCompany.value });
	} catch {
		overview.value = null;
	}
}
onMounted(loadOverview);
watch(activeCompany, loadOverview);
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ t("Module") }}</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-users-group"></i> {{ t("People") }}
					</h2>
				</div>
				<div v-if="overview" class="col-auto d-none d-md-flex gap-3">
					<div class="text-center">
						<div class="h2 m-0">{{ overview.active_employees }}</div>
						<div class="small text-secondary">{{ t("Active") }}</div>
					</div>
					<div class="text-center">
						<div class="h2 m-0">{{ overview.on_leave_today }}</div>
						<div class="small text-secondary">{{ t("On leave today") }}</div>
					</div>
					<div class="text-center">
						<div class="h2 m-0 text-warning">{{ overview.pending_leave_requests }}</div>
						<div class="small text-secondary">{{ t("Pending requests") }}</div>
					</div>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<ul class="nav nav-bordered mb-3">
				<li v-for="tab in tabs" :key="tab.name" class="nav-item">
					<router-link :to="tab.path" class="nav-link" :class="{ active: activeTab === tab.name }">
						<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
					</router-link>
				</li>
			</ul>
			<router-view />
		</div>
	</div>
</template>
