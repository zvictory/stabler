<script setup>
/* ⚠️ GEÇİCİ KARŞILAŞTIRMA EKRANI — kalıcı değil, menüde yok.
 *
 * Tek işi var: huninin `2d6ff37` ("migrate the tender funnel to the Modernist
 * Tabler layer", 2026-07-31) ÖNCESİ ve SONRASI hallerini aynı veriyle, aynı
 * anda göstermek. İkisi de `stabler.api.tender.tender_funnel`'i çağırıyor —
 * fark yalnız çizimde, sayılarda değil.
 *
 * Eski bileşen Bootstrap/Tabler sınıfları taşıyor; `stbl-ds` kabuğunun İÇİNE
 * konursa katman onu yeniden boyar ve karşılaştırma yalan söyler. O yüzden
 * eski panel çıplak `container`'da, yeni panel kendi `.stbl-ds` sarmalında.
 *
 * Karar verilince bu dosya + `TenderFunnelLegacy.vue` + rotası SİLİNİR.
 */
import { ref } from "vue";
import { t } from "../../composables/i18n.js";
import TenderFunnel from "./TenderFunnel.vue";
import TenderFunnelLegacy from "./TenderFunnelLegacy.vue";

// Paneller geniş; yan yana sıkışıyorlar. Varsayılan alt alta, tek tıkla yan yana.
const layout = ref("stack"); // 'stack' | 'split'
const days = ref(90);
</script>

<template>
	<div class="fc-page">
		<header class="fc-head">
			<div>
				<div class="fc-pretitle">{{ t("Tender") }} · {{ t("Temporary comparison") }}</div>
				<h2 class="fc-title">{{ t("Conversion funnel — old vs new") }}</h2>
				<p class="fc-sub">
					{{
						t(
							"Same endpoint, same numbers — only the drawing differs. Pick one and the loser gets deleted."
						)
					}}
				</p>
			</div>
			<div class="fc-controls">
				<div class="btn-group btn-group-sm" role="group">
					<button
						type="button"
						class="btn"
						:class="layout === 'stack' ? 'btn-primary' : 'btn-outline-secondary'"
						@click="layout = 'stack'"
					>
						{{ t("Stacked") }}
					</button>
					<button
						type="button"
						class="btn"
						:class="layout === 'split' ? 'btn-primary' : 'btn-outline-secondary'"
						@click="layout = 'split'"
					>
						{{ t("Side by side") }}
					</button>
				</div>
				<select v-model.number="days" class="form-select form-select-sm fc-days">
					<option :value="30">30 {{ t("days") }}</option>
					<option :value="90">90 {{ t("days") }}</option>
					<option :value="180">180 {{ t("days") }}</option>
				</select>
			</div>
		</header>

		<div class="fc-grid" :data-layout="layout">
			<section class="fc-pane">
				<div class="fc-tag fc-tag--old">
					<span class="fc-tag-n">A</span>
					<div>
						<strong>{{ t("Old — trapezoid funnel") }}</strong>
						<code class="fc-code">2d6ff37^ · TenderFunnel.vue · 2026-07-31 öncesi</code>
					</div>
				</div>
				<!-- Kasıtlı olarak `stbl-ds` DIŞINDA: bileşen Tabler sınıflarıyla
				     yazıldı, kendi bağlamında görülsün. -->
				<TenderFunnelLegacy mode="full" :days="days" />
			</section>

			<section class="fc-pane">
				<div class="fc-tag fc-tag--new">
					<span class="fc-tag-n">B</span>
					<div>
						<strong>{{ t("Current — bar funnel, Modernist layer") }}</strong>
						<code class="fc-code">HEAD · TenderFunnel.vue · /tender/portfolio + /tender/overview</code>
					</div>
				</div>
				<div class="stbl-ds fc-ds">
					<TenderFunnel mode="full" :days="days" />
				</div>
			</section>
		</div>
	</div>
</template>

<style scoped>
.fc-page {
	padding: 1rem;
}

.fc-head {
	display: flex;
	align-items: flex-start;
	justify-content: space-between;
	gap: 16px;
	flex-wrap: wrap;
	margin-bottom: 18px;
}

.fc-pretitle {
	font-size: 11px;
	letter-spacing: 0.08em;
	text-transform: uppercase;
	color: var(--tblr-secondary, #626976);
}

.fc-title {
	margin: 2px 0 4px;
}

.fc-sub {
	margin: 0;
	font-size: 13px;
	color: var(--tblr-secondary, #626976);
	max-width: 62ch;
}

.fc-controls {
	display: flex;
	align-items: center;
	gap: 8px;
}

.fc-days {
	width: auto;
}

.fc-grid {
	display: grid;
	gap: 24px;
}

.fc-grid[data-layout="split"] {
	grid-template-columns: repeat(2, minmax(0, 1fr));
}

@media (max-width: 1400px) {
	.fc-grid[data-layout="split"] {
		grid-template-columns: minmax(0, 1fr);
	}
}

.fc-pane {
	min-width: 0;
}

/* Etiket şeridi: hangi panelin hangi sürüm olduğu, kaydırırken de görünür. */
.fc-tag {
	display: flex;
	align-items: center;
	gap: 10px;
	padding: 8px 12px;
	margin-bottom: 10px;
	border-radius: 6px;
	border-left: 3px solid;
	background: rgba(120, 120, 130, 0.07);
}

.fc-tag--old {
	border-left-color: #d97706;
}

.fc-tag--new {
	border-left-color: #206bc4;
}

.fc-tag-n {
	display: inline-flex;
	align-items: center;
	justify-content: center;
	width: 24px;
	height: 24px;
	border-radius: 50%;
	background: #1f2937;
	color: #fff;
	font-size: 12px;
	font-weight: 700;
	flex: 0 0 auto;
}

.fc-code {
	display: block;
	font-size: 11px;
	color: var(--tblr-secondary, #626976);
}

/* Yeni panel kendi katmanını içeride kuruyor; sayfa dolgusunu tekrarlamasın. */
.fc-ds {
	padding: 0;
}
</style>
