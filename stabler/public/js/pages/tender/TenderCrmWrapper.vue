<script setup>
import { useRoute } from "vue-router";
import TenderMasterBoard from "./TenderMasterBoard.vue";
import TenderCrm from "./TenderCrm.vue";

const route = useRoute();
</script>

<template>
	<!-- Wrapper for Level 1 (TenderMasterBoard) and Level 2 (TenderCrm) - both render <TenderPage> -->
	<TenderCrm v-if="route.query?.tender" />
	<TenderMasterBoard v-else />
</template>
