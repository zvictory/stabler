<script setup>
defineProps({
	rows: { type: Number, default: 5 },
	cols: { type: Number, default: 3 },
	hideFirstOnMobile: { type: Boolean, default: false },
});
</script>

<template>
	<tbody class="placeholder-glow">
		<tr v-for="r in rows" :key="r">
			<td
				v-for="c in cols"
				:key="c"
				:class="{ 'd-none d-md-table-cell': hideFirstOnMobile && c === 1 }"
			>
				<span class="placeholder col-8 py-2 rounded-1"></span>
			</td>
		</tr>
	</tbody>
</template>
