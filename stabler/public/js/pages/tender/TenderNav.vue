<script setup>
// Role-aware sub-nav for the tender module: shows only the windows the current
// user's roles allow (director / sourcing / declarant / logist), plus the shared
// board surfaces. Fetches the permitted views once.
import { onMounted } from "vue";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";

const session = useSession();
const can = (view) => session.tenderViews.includes(view);
onMounted(() => session.ensureTenderViews());
</script>

<template>
	<div class="d-flex gap-2 flex-wrap mb-3">
		<router-link v-if="can('director')" to="/tender/director" class="btn btn-outline-secondary btn-sm" active-class="btn-primary">
			<i class="ti ti-layout-dashboard me-1"></i>{{ t("Director board") }}
		</router-link>
		<router-link to="/tender/board" class="btn btn-outline-secondary btn-sm" active-class="btn-primary">
			<i class="ti ti-layout-kanban me-1"></i>{{ t("Contract board") }}
		</router-link>
		<router-link v-if="can('sourcing')" to="/tender/my-tenders" class="btn btn-outline-secondary btn-sm" active-class="btn-primary">
			<i class="ti ti-list-check me-1"></i>{{ t("My tenders") }}
		</router-link>
		<router-link v-if="can('sourcing')" to="/tender/po-control" class="btn btn-outline-secondary btn-sm" active-class="btn-primary">
			<i class="ti ti-clipboard-check me-1"></i>{{ t("Tender PO control") }}
		</router-link>
		<router-link v-if="can('declarant')" to="/tender/customs" class="btn btn-outline-secondary btn-sm" active-class="btn-primary">
			<i class="ti ti-file-invoice me-1"></i>{{ t("Customs queue") }}
		</router-link>
		<router-link v-if="can('logist')" to="/tender/logistics" class="btn btn-outline-secondary btn-sm" active-class="btn-primary">
			<i class="ti ti-truck-delivery me-1"></i>{{ t("Logistics") }}
		</router-link>
	</div>
</template>
