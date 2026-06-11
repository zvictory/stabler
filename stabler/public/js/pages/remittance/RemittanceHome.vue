<script setup>
import { computed } from "vue";
import { useRoute, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";

const route = useRoute();
const tabs = [
	{ name: "remittance-new", path: "/remittance/new", label: t("New Transfer"), icon: "ti-plus" },
	{ name: "remittance-transfers", path: "/remittance/transfers", label: t("Transfers"), icon: "ti-list" },
];
const activeTab = computed(() => route.name);
</script>

<template>
	<ModuleHeader :title='t("Remittance")' icon="ti-send" :tabs="tabs" :active-tab="activeTab" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
