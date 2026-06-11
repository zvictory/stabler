<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const tabs = [
	{ name: "installment-new", path: "/installment/new", label: t("New Contract"), icon: "ti-plus" },
	{ name: "installment-contracts", path: "/installment/contracts", label: t("Contracts"), icon: "ti-file-invoice" },
	{ name: "installment-calendar", path: "/installment/calendar", label: t("Calendar"), icon: "ti-calendar" },
];
const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("Installment")' icon="ti-calendar-dollar" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
