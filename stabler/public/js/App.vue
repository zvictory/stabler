<script setup>
import { computed, onMounted } from "vue";
import { useRoute } from "vue-router";
import Sidebar from "./components/Sidebar.vue";
import CommandPalette from "./components/CommandPalette.vue";
import ToastHost from "./components/ToastHost.vue";
import ConfirmHost from "./components/ConfirmHost.vue";
import UpdateBanner from "./components/UpdateBanner.vue";
import BackgroundJobsBanner from "./components/BackgroundJobsBanner.vue";
import { useSession } from "./stores/session.js";
import { startBackgroundHealthCheck } from "./composables/backgroundHealth.js";

const route = useRoute();
const session = useSession();

const isStandalone = computed(() => {
	return route.path === "/login" || route.matched.some((r) => r.meta?.standalone);
});

onMounted(() => {
	session.setupRehydration();
	startBackgroundHealthCheck();
});
</script>

<template>
	<div v-if="isStandalone" class="standalone-page">
		<router-view v-slot="{ Component }">
			<component :is="Component" />
		</router-view>
		<ToastHost />
		<ConfirmHost />
	</div>
	<div v-else class="page">
		<Sidebar />
		<div class="page-wrapper">
			<UpdateBanner />
			<BackgroundJobsBanner />
			<router-view v-slot="{ Component }">
				<component :is="Component" />
			</router-view>

			<CommandPalette />
			<ToastHost />
			<ConfirmHost />

			<footer class="footer footer-transparent d-print-none">
				<div class="container-xl">
					<div class="row text-center align-items-center flex-row-reverse">
						<div class="col-lg-auto ms-lg-auto">
							<ul class="list-inline list-inline-dots mb-0">
								<li class="list-inline-item">Stabler v0.1</li>
							</ul>
						</div>
						<div class="col-12 col-lg-auto mt-3 mt-lg-0">
							<ul class="list-inline list-inline-dots mb-0">
								<li class="list-inline-item">© 2026 Stabler</li>
							</ul>
						</div>
					</div>
				</div>
			</footer>
		</div>
	</div>
</template>
