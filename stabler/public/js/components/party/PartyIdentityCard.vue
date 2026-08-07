<script setup>
/**
 * Party Center — kimlik meta şeridi.
 *
 * Detay endpoint'i zaten `email_id`, `mobile_no`, `tax_id`, grup, bölge ve
 * `default_currency` döndürüyor (bkz. `customer_detail` / `supplier_detail`);
 * bu şerit onları tek yerde toplar. Alan adları partiye göre değiştiği için
 * (`customer_group` ↔ `supplier_group`) eşleme `fields` prop'undan gelir.
 *
 * Tek satır olması bilinçli: bu ekranın asıl işi ekstre, kimlik alanları ise
 * bağlam. Boş alan hiç render edilmez — tipik kayıtta altı alanın dördü boş
 * olduğu için `—` dolu bir tablo, ekstreden ~300 px çalıp karşılığında hiçbir
 * bilgi vermiyordu.
 */
import { computed } from "vue";
import { t } from "../../composables/i18n.js";

const props = defineProps({
	detail: { type: Object, default: null },
	fields: { type: Object, default: () => ({}) },
	labels: { type: Object, default: () => ({}) },
});

const rows = computed(() => {
	const d = props.detail;
	if (!d) return [];
	const out = [
		{
			key: "email",
			label: t("Email"),
			value: d.email_id || "",
			href: d.email_id ? `mailto:${d.email_id}` : "",
			icon: "ti ti-mail",
		},
		{
			key: "mobile",
			label: t("Mobile"),
			value: d.mobile_no || "",
			href: d.mobile_no ? `tel:${d.mobile_no}` : "",
			icon: "ti ti-phone",
		},
		{ key: "tax_id", label: t("Tax ID"), value: d.tax_id || "", mono: true, icon: "ti ti-receipt-tax" },
	];
	if (props.fields.group) {
		out.push({ key: "group", label: props.labels.groupLabel || t("Group"), value: d[props.fields.group] || "" });
	}
	if (props.fields.territory) {
		out.push({ key: "territory", label: t("Territory"), value: d[props.fields.territory] || "" });
	}
	out.push({ key: "currency", label: t("Default currency"), value: d.default_currency || "", mono: true });
	return out.filter((r) => r.value);
});
</script>

<template>
	<div v-if="rows.length" class="pc-meta">
		<template v-for="r in rows" :key="r.key">
			<a
				v-if="r.href"
				:href="r.href"
				class="pc-meta-item pc-link"
				:class="{ 'pc-mono': r.mono }"
				:title="`${r.label}: ${r.value}`"
				:aria-label="r.label"
			>
				<i v-if="r.icon" :class="r.icon" aria-hidden="true"></i>{{ r.value }}
			</a>
			<span
				v-else
				class="pc-meta-item"
				:class="{ 'pc-mono': r.mono }"
				:title="`${r.label}: ${r.value}`"
				:aria-label="r.label"
			>
				<i v-if="r.icon" :class="r.icon" aria-hidden="true"></i>{{ r.value }}
			</span>
		</template>
	</div>
</template>

<style scoped>
/* Gerçekten TEK satır: kimlik sütunu eylem düğmelerinin yanında ~224 px'e
   düşüyor, sarmaya izin verilince şerit üç satıra çıkıp başlığı 95 px'e
   şişiriyordu. Taşan alanlar kırpılır; tam değer `title` ile okunur. */
.pc-meta {
	display: flex;
	flex-wrap: nowrap;
	align-items: center;
	margin-top: 2px;
	font-size: 12.5px;
	color: var(--tblr-gray-600, #667382);
	min-width: 0;
	overflow: hidden;
	white-space: nowrap;
}
.pc-meta-item {
	display: inline-flex;
	flex: 0 1 auto;
	align-items: center;
	gap: 4px;
	min-width: 0;
	overflow: hidden;
	text-overflow: ellipsis;
}
/* Ayraç öğenin kendisine bağlı: şerit sarınca `·` ait olduğu değerle
   birlikte alt satıra iner, tek başına satır başına düşmez. */
.pc-meta-item + .pc-meta-item::before {
	content: "·";
	padding: 0 4px;
	color: var(--tblr-gray-500, #8a94a6);
}
.pc-meta-item i {
	font-size: 13px;
	color: var(--tblr-gray-500, #8a94a6);
}
.pc-mono {
	font-family: var(--ds-mono, monospace);
}
.pc-link {
	color: #206bc4;
	text-decoration: none;
}
.pc-link:hover {
	text-decoration: underline;
}
</style>
