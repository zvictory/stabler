<script setup>
import { computed, watchEffect } from "vue";
import { useRoute, useRouter, RouterLink, RouterView } from "vue-router";
import { t } from "../../composables/i18n.js";
import { useSession } from "../../stores/session.js";

const route = useRoute();
const router = useRouter();
const session = useSession();

const tabs = computed(() => [
	...(session.isMfgManager
		? [{ name: "manufacturing-boms", path: "/manufacturing/boms", label: t("BOMs"), icon: "ti-list-tree" }]
		: []),
	{ name: "manufacturing-work-orders", path: "/manufacturing/work-orders", label: t("Work Orders"), icon: "ti-tool" },
]);
const activeTab = computed(() => route.name);

// Redirect operators away from the BOMs route — the server guards it too,
// but the redirect avoids a visible error flash.
watchEffect(() => {
	if (route.name === "manufacturing-boms" && !session.isMfgManager) {
		router.replace("/manufacturing/work-orders");
	}
});
</script>

<template>
	<div class="page-header d-print-none">
		<div class="container-xl">
			<div class="row g-2 align-items-center">
				<div class="col">
					<div class="page-pretitle">{{ t("Module") }}</div>
					<h2 class="page-title d-flex align-items-center gap-2">
						<i class="ti ti-tools"></i> {{ t("Manufacturing") }}
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
