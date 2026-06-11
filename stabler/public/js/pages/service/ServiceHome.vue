<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";

const route = useRoute();
const activeTab = computed(() => route.name);

const tabs = [
	{ name: "service-dashboard", path: "/service/dashboard", label: t("Dashboard"), icon: "ti-layout-dashboard" },
	{ name: "service-tickets", path: "/service/tickets", label: t("Tickets"), icon: "ti-ticket" },
	{ name: "service-calendar", path: "/service/calendar", label: t("Calendar"), icon: "ti-calendar" },
	{ name: "service-equipment", path: "/service/equipment", label: t("Equipment"), icon: "ti-fridge" },
	{ name: "service-map", path: "/service/map", label: t("Map"), icon: "ti-map-2" },
];
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ t("Module") }}</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-tool"></i>{{ t("Service") }}
					</h2>
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
