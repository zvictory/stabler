<script setup>
import { t } from "../../composables/i18n.js";
import ModuleHeader from "../../components/ModuleHeader.vue";
</script>
<template>
	<ModuleHeader :title='t("Processes")' icon="ti-sitemap" />

	<div class="page-body">
		<div class="container-xl">
			<router-view />
		</div>
	</div>
</template>
