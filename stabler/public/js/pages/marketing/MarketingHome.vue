<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

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
	<ModuleHeader :title='t("Trade Marketing")' icon="ti-target-arrow" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
