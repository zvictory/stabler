<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";

const route = useRoute();

const tabs = computed(() => [
	{ name: "marketing-plans", path: "/marketing/plans", label: t("Promo Plans"), icon: "ti-flag-2" },
	{ name: "marketing-roi", path: "/marketing/roi", label: t("Campaign ROI"), icon: "ti-chart-bar" },
	{ name: "marketing-claims", path: "/marketing/claims", label: t("Claims"), icon: "ti-file-invoice" },
	{ name: "marketing-equipment", path: "/marketing/equipment", label: t("Equipment"), icon: "ti-fridge" },
	{ name: "marketing-repairs", path: "/marketing/repairs", label: t("Repair Requests"), icon: "ti-tool" },
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
						<i class="ti ti-target-arrow"></i> {{ t("Trade Marketing") }}
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
