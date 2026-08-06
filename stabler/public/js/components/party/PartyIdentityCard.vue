<script setup>
/**
 * Party Center — kimlik kartı.
 *
 * Detay endpoint'i zaten `email_id`, `mobile_no`, `tax_id`, grup, bölge ve
 * `default_currency` döndürüyor (bkz. `customer_detail` / `supplier_detail`);
 * bu kart onları tek yerde toplar. Alan adları partiye göre değiştiği için
 * (`customer_group` ↔ `supplier_group`) eşleme `fields` prop'undan gelir.
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
		{ key: "email", label: t("Email"), value: d.email_id || "", href: d.email_id ? `mailto:${d.email_id}` : "" },
		{ key: "mobile", label: t("Mobile"), value: d.mobile_no || "", href: d.mobile_no ? `tel:${d.mobile_no}` : "" },
		{ key: "tax_id", label: t("Tax ID"), value: d.tax_id || "", mono: true },
	];
	if (props.fields.group) {
		out.push({ key: "group", label: props.labels.groupLabel || t("Group"), value: d[props.fields.group] || "" });
	}
	if (props.fields.territory) {
		out.push({ key: "territory", label: t("Territory"), value: d[props.fields.territory] || "" });
	}
	out.push({ key: "currency", label: t("Default currency"), value: d.default_currency || "", mono: true });
	return out;
});

const hasAny = computed(() => rows.value.some((r) => r.value));
</script>

<template>
	<div v-if="props.detail" class="ds-panel pc-card">
		<div class="ds-panel-head">
			<span class="pc-label">{{ t("Contact") }}</span>
		</div>
		<dl class="pc-grid">
			<template v-for="r in rows" :key="r.key">
				<dt class="pc-label">{{ r.label }}</dt>
				<dd class="pc-val" :class="{ 'pc-mono': r.mono }">
					<a v-if="r.value && r.href" :href="r.href" class="pc-link">{{ r.value }}</a>
					<span v-else-if="r.value">{{ r.value }}</span>
					<span v-else class="pc-empty">—</span>
				</dd>
			</template>
		</dl>
		<div v-if="!hasAny" class="pc-none">{{ t("No contact details recorded.") }}</div>
	</div>
</template>

<style scoped>
.pc-card {
	background: #fff;
}
.pc-grid {
	display: grid;
	grid-template-columns: 9rem 1fr;
	gap: 0;
	margin: 0;
	padding: 4px 0;
}
.pc-grid dt {
	padding: 8px 16px;
	border-bottom: 1px solid #e3e5e8;
	align-self: center;
}
.pc-grid dd {
	margin: 0;
	padding: 8px 16px;
	border-bottom: 1px solid #e3e5e8;
	font-size: 13.5px;
	color: #1d273b;
	overflow-wrap: anywhere;
}
.pc-grid dt:nth-last-of-type(1),
.pc-grid dd:nth-last-of-type(1) {
	border-bottom: 0;
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
.pc-empty {
	color: var(--tblr-gray-600, #667382);
}
.pc-none {
	padding: 10px 16px;
	font-size: 12.5px;
	color: var(--tblr-gray-600, #667382);
}

@media (max-width: 575.98px) {
	.pc-grid {
		grid-template-columns: 1fr;
	}
	.pc-grid dt {
		border-bottom: 0;
		padding-bottom: 0;
	}
}

/* Mikro etiket — `.ds-label` çevrilmeyen teknik kimliklere ayrılmıştır;
   çevrili etiketler tipografiyi buradan alır, tonu AA'ya çekilir. */
.pc-label {
	font-family: var(--ds-mono);
	font-size: 10px;
	letter-spacing: 0.14em;
	text-transform: uppercase;
	color: var(--tblr-gray-600, #667382);
}
</style>
