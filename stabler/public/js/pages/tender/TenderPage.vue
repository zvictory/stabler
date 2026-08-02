<script setup>
// Her /tender/* ekranının kabuğu: modül çubuğu + sayfa başlığı, tek yerde.
//
// Neden bileşen: on tender ekranı kabuğu kendi eliyle kuruyordu ve on kopya
// birbirinden ayrı düştü. Dördü tasarım katmanındaydı (`stbl-ds` + `ds-page-head`),
// altısı Bootstrap'te (`container-xl py-3` + `<h2>`); tasarım katmanındaki
// dördün ikisi de (flow, crm) üst dolgusu 0 olan `max-width: 1240px` kutu
// kullanıyordu, o yüzden TenderNav'ın negatif üst kenarı çubuğu içerik
// alanının 16px yukarısına çekiyordu — ölçüldü 2026-08-02: flow ve crm'de
// çubuğun tepesi -16, /tender/desk'te 0. Ekran değiştirdikçe menü kayıyordu.
//
// Kabuk artık burada: `padding: 1rem` (desk'in ölçüsü) ve tam genişlik. Bir
// ekranı taşımak = kökünü <TenderPage> yapmak; katmanın kendi kuralı da bu
// (stabler-modernist.css:900 "Bir form ekranını taşımak = kök elemana
// class='stbl-ds' eklemek").
import { storeToRefs } from "pinia";
import { useSession } from "../../stores/session.js";
import TenderNav from "./TenderNav.vue";

defineProps({
	// Başlığın üstündeki mono etiket. Şirket adını KABUK ekler — on ekranda
	// on kez "· {{ activeCompany }}" yazılınca biri eksik kalıyordu.
	label: { type: String, default: "" },
	title: { type: String, default: "" },
});

const { activeCompany } = storeToRefs(useSession());
</script>

<template>
	<div class="tender-page stbl-ds">
		<TenderNav />
		<header class="ds-page-head">
			<div class="ds-label">{{ label }} · {{ activeCompany || "—" }}</div>
			<h1>{{ title }}</h1>
			<div v-if="$slots.meta" class="ds-meta"><slot name="meta" /></div>
			<div v-if="$slots.actions" class="ds-actions"><slot name="actions" /></div>
		</header>
		<slot />
	</div>
</template>

<style scoped>
.tender-page {
	padding: 1rem;
}
</style>
