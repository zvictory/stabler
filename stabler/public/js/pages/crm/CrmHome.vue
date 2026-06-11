<script setup>
import { computed } from "vue";
import { useRoute } from "vue-router";
import { t } from "../../composables/i18n.js";

const route = useRoute();
const tabs = [
	{ name: "crm-leads", path: "/crm/leads", label: t("Leads"), icon: "ti-user-plus" },
	{ name: "crm-deals", path: "/crm/deals", label: t("Deals"), icon: "ti-briefcase" },
];
const activeTab = computed(() => route.name);
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">Module</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-address-book"></i> {{ t("CRM") }}
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
