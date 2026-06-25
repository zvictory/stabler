<script setup>
import { computed } from "vue";
import { storeToRefs } from "pinia";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const session = useSession();
const { roles } = storeToRefs(session);

// Two-level navigation: primary AREAS, each with secondary TABS.
// `roles` gates an area to the people who need it (admins see all). An area
// with no roles is public to every authenticated HR user.
const AREAS = [
	{
		key: "overview", label: t("Overview"), icon: "ti-layout-dashboard",
		landing: "/hr/overview", roles: [], tabs: [],
	},
	{
		key: "people", label: t("People"), icon: "ti-id-badge-2",
		landing: "/hr/employees", roles: ["HR User", "HR Manager"],
		tabs: [
			{ name: "hr-employees", path: "/hr/employees", label: t("Employees"), icon: "ti-users" },
		],
	},
	{
		key: "attendance", label: t("Attendance"), icon: "ti-calendar-clock",
		landing: "/hr/attendance-dashboard", roles: ["HR User", "HR Manager"],
		tabs: [
			{ name: "hr-attendance-dashboard", path: "/hr/attendance-dashboard", label: t("Dashboard"), icon: "ti-layout-dashboard" },
			{ name: "hr-attendance", path: "/hr/attendance", label: t("Daily"), icon: "ti-calendar-event" },
			{ name: "hr-exceptions-queue", path: "/hr/exceptions-queue", label: t("Exceptions"), icon: "ti-alert-triangle" },
			{ name: "hr-corrections", path: "/hr/corrections", label: t("Corrections"), icon: "ti-edit" },
			{ name: "hr-leave", path: "/hr/leave", label: t("Leave"), icon: "ti-beach" },
		],
	},
	{
		key: "payroll", label: t("Payroll"), icon: "ti-cash",
		landing: "/hr/payroll-readiness",
		roles: ["Accounts User", "Accounts Manager", "Payroll Manager", "HR Manager"],
		tabs: [
			{ name: "hr-payroll-readiness", path: "/hr/payroll-readiness", label: t("Readiness"), icon: "ti-lock-check" },
			{ name: "hr-payroll-preview", path: "/hr/payroll-preview", label: t("Computed Pay"), icon: "ti-calculator" },
			{ name: "hr-payroll", path: "/hr/payroll", label: t("Salary slips"), icon: "ti-cash" },
		],
	},
	{
		key: "settings", label: t("Settings"), icon: "ti-settings",
		landing: "/hr/attendance-rules", roles: ["HR Manager"],
		tabs: [
			{ name: "hr-attendance-rules", path: "/hr/attendance-rules", label: t("Rule sets"), icon: "ti-adjustments" },
			{ name: "hr-attendance-simulator", path: "/hr/attendance-simulator", label: t("Simulator"), icon: "ti-player-play" },
			{ name: "hr-device-mapping", path: "/hr/employee-device-mapping", label: t("Device mapping"), icon: "ti-link" },
			{ name: "hr-gate-devices", path: "/hr/gate-devices", label: t("Gate devices"), icon: "ti-door" },
			{ name: "hr-raw-events", path: "/hr/raw-gate-events", label: t("Gate events"), icon: "ti-clock-bolt" },
			{ name: "hr-timepay-settings", path: "/hr/timepay-settings", label: t("TimePay"), icon: "ti-key" },
		],
	},
];

const isAdmin = computed(() => session.isAdmin);
const myRoles = computed(() => roles.value || []);

function allowed(area) {
	if (!area.roles || area.roles.length === 0) return true;
	if (isAdmin.value) return true;
	return area.roles.some((r) => myRoles.value.includes(r));
}

const visibleAreas = computed(() => AREAS.filter(allowed));

// Which area owns the current route? Match a sub-tab name, else the area's own
// detail routes (e.g. the rule-set editor lives under Settings), else Overview.
const SETTINGS_DETAIL = new Set(["hr-attendance-rule", "hr-attendance-rule-new"]);
const activeArea = computed(() => {
	const name = route.name;
	for (const a of visibleAreas.value) {
		if (a.key === "overview" && name === "hr-overview") return a;
		if (a.tabs.some((tb) => tb.name === name)) return a;
	}
	if (SETTINGS_DETAIL.has(name)) return visibleAreas.value.find((a) => a.key === "settings");
	return visibleAreas.value[0];
});

const primaryTabs = computed(() =>
	visibleAreas.value.map((a) => ({ name: a.key, path: a.landing, label: a.label, icon: a.icon })),
);
const activeAreaKey = computed(() => activeArea.value?.key);
const secondaryTabs = computed(() => activeArea.value?.tabs || []);
</script>

<template>
	<ModuleHeader :title='t("People")' icon="ti-users-group" :tabs="primaryTabs" :active-tab="activeAreaKey" />

	<div class="page-body">
		<div class="container-xl">
			<ul v-if="secondaryTabs.length" class="nav nav-pills stbl-hr-subnav mb-3">
				<li v-for="tab in secondaryTabs" :key="tab.name" class="nav-item">
					<RouterLink :to="tab.path" class="nav-link" :class="{ active: route.name === tab.name }">
						<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
					</RouterLink>
				</li>
			</ul>
			<RouterView />
		</div>
	</div>
</template>

<style scoped>
.stbl-hr-subnav {
	gap: 4px;
	border-bottom: 0.5px solid var(--tblr-border-color, rgba(0, 0, 0, 0.1));
	padding-bottom: 8px;
}
</style>
