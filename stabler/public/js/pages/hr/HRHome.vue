<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { useSession } from "../../stores/session.js";
import { call } from "../../api/client.js";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

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
	<ModuleHeader :title='t("People")' icon="ti-users-group" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
