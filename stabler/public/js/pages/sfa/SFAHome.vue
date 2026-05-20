<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";

const route = useRoute();

const tabs = computed(() => [
	{ name: "sfa-outlets", path: "/sfa/outlets", label: t("Outlets"), icon: "ti-building-store" },
	{ name: "sfa-routes", path: "/sfa/routes", label: t("Routes"), icon: "ti-route" },
	{ name: "sfa-visits", path: "/sfa/visits", label: t("Visits"), icon: "ti-map-pin-check" },
	{ name: "sfa-field-users", path: "/sfa/field-users", label: t("Field Users"), icon: "ti-user-check" },
	{ name: "sfa-van-stock", path: "/sfa/van-stock", label: t("Van Stock"), icon: "ti-truck-loading" },
	{ name: "sfa-promos", path: "/sfa/promos", label: t("Promos"), icon: "ti-discount-2" },
	{ name: "sfa-photos", path: "/sfa/photos", label: t("Photos"), icon: "ti-camera" },
	{ name: "sfa-planograms", path: "/sfa/planograms", label: t("Planograms"), icon: "ti-layout-grid" },
	{ name: "sfa-osa", path: "/sfa/osa", label: t("OSA"), icon: "ti-checkup-list" },
	{ name: "sfa-receivables", path: "/sfa/receivables", label: t("Receivables"), icon: "ti-receipt-2" },
]);

const activeTab = computed(() => route.name);
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ t("Module") }}</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-route"></i> {{ t("Field Sales") }}
					</h2>
				</div>
			</div>
		</div>
	</div>

	<div class="page-body">
		<div class="container-xl">
			<ul class="nav nav-bordered mb-3">
				<li v-for="tab in tabs" :key="tab.name" class="nav-item">
					<router-link
						:to="tab.path"
						class="nav-link"
						:class="{ active: activeTab === tab.name }"
					>
						<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
					</router-link>
				</li>
			</ul>

			<router-view />
		</div>
	</div>
</template>
