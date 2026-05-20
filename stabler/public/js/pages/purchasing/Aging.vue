<script setup>
import AgingTable from "../../components/AgingTable.vue";
</script>

<template>
	<AgingTable
		endpoint="stabler.api.purchasing.ap_aging"
		party-label="Supplier"
		party-key="supplier"
		party-name-key="supplier_name"
		heading="Accounts Payable Aging"
	/>
</template>
