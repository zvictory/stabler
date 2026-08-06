<script setup>
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	active: { type: String, default: "overview" },
	views: { type: Object, default: () => ({}) },
	hasFinance: { type: Boolean, default: false },
});

const route = useRoute();
const router = useRouter();
const tabs = computed(() => [
	{ key: "overview", label: t("Overview"), icon: "ti-layout-dashboard" },
	{ key: "documents", label: t("Documents"), icon: "ti-files" },
	{ key: "vendor-po", label: t("Vendor & PO"), icon: "ti-shopping-cart" },
	{ key: "delivery", label: t("Delivery"), icon: "ti-truck-delivery" },
	{ key: "documents", label: t("Documents"), icon: "ti-files" },
	...(props.hasFinance ? [{ key: "finance", label: t("Finance"), icon: "ti-report-money" }] : []),
]);
const allowedTabs = computed(() => tabs.value.map((tab) => tab.key));
const activeTab = computed(() => {
	const requested = String(route.query.tab || "overview");
	return allowedTabs.value.includes(requested) ? requested : "overview";
});

function selectTab(tab) {
	router.replace({ query: { ...route.query, tab } });
}
</script>

<template>
	<nav class="nav nav-tabs mb-3" :aria-label="t('Tender workspace sections')">
		<button
			v-for="tab in tabs"
			:key="tab.key"
			type="button"
			class="nav-link"
			:class="{ active: activeTab === tab.key || active === tab.key }"
			@click="selectTab(tab.key)"
		>
			<i class="ti me-1" :class="tab.icon"></i>{{ tab.label }}
		</button>
	</nav>
</template>
