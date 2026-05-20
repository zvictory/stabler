<script setup>
import AgingTable from "../../components/AgingTable.vue";
</script>

<template>
	<AgingTable
		endpoint="stabler.api.sales.ar_aging"
		party-label="Customer"
		party-key="customer"
		party-name-key="customer_name"
		heading="Accounts Receivable Aging"
	/>
</template>
