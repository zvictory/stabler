<script setup>
defineProps({
	rows: { type: Number, default: 5 },
	cols: { type: Number, default: 3 },
});
</script>

<template>
	<tbody class="placeholder-glow">
		<tr v-for="r in rows" :key="r">
			<td v-for="c in cols" :key="c">
				<span class="placeholder col-8 py-2 rounded-1"></span>
			</td>
		</tr>
	</tbody>
</template>
