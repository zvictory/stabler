<script setup>
/* Tender modülünün üst gezinme çubuğu.
 *
 * Stabler'da modül gezinmesi iki katmanlı: kenar çubuğu MODÜLÜ gösterir
 * (Satış, Satınalma, İthalat, Tender…), modülün kendi ekranları o sayfanın
 * üstündeki çubukta yaşar. On beş modülün on beşi bu şekilde çalışıyor —
 * her birinin bir `*Home.vue` hub'ı var ve kenar çubuğunda tek maddesi.
 *
 * Tender tek istisnaydı: sekiz alt yolu kenar çubuğuna dökülmüştü, üstüne bir
 * de bu düğme şeridi vardı. İki yer aynı şeyi farklı söyleyince kullanıcı
 * hangisine bakacağını bilemiyordu — Direktör panosu tam olarak bu yüzden
 * kayboldu: kenar çubuğunda hiç yoktu, yalnız buradaydı, buradaki de yalnız
 * başka bir tender sayfasındayken görünüyordu.
 *
 * Çubuk artık tasarımın `ds-modnav`'ı. Rol kapıları aynen korundu: her bağlantı
 * kullanıcının tender görünümlerine (`director` / `sourcing` / `declarant` /
 * `logist`) bakıyor, `ensureTenderViews()` bir kez çekiyor.
 */
import { onMounted } from "vue";
import { useSession } from "../../stores/session.js";
import { t } from "../../composables/i18n.js";

const session = useSession();
const can = (view) => session.tenderViews.includes(view);
onMounted(() => session.ensureTenderViews());
</script>

<template>
	<nav class="stbl-ds tender-modnav">
		<div class="ds-modnav">
			<span class="ds-modnav-brand">{{ t("Tender") }}</span>

			<router-link v-if="can('director')" to="/tender/portfolio" active-class="active">
				{{ t("Director board") }}
			</router-link>

			<!-- Panoya dönüş burada duruyor çünkü pano tender'ın da özeti:
			     Operasyon Masası oraya gömülü. Konumu değil VARLIĞI garanti. -->
			<router-link to="/dashboard" active-class="active">{{ t("Overview") }}</router-link>

			<router-link v-if="session.tenderViews.length > 0" to="/tender/desk" active-class="active">
				{{ t("Operations desk") }}
			</router-link>
			<router-link v-if="can('director')" to="/tender/flow" active-class="active">
				{{ t("Process flow") }}
			</router-link>
			<router-link to="/tender/board" active-class="active">{{ t("Contract board") }}</router-link>
			<router-link v-if="can('director') || can('sourcing')" to="/tender/crm" active-class="active">
				{{ t("Tender CRM") }}
			</router-link>
			<router-link v-if="can('sourcing')" to="/tender/my-tenders" active-class="active">
				{{ t("My tenders") }}
			</router-link>
			<router-link v-if="can('sourcing')" to="/tender/po-control" active-class="active">
				{{ t("Tender PO control") }}
			</router-link>
			<router-link v-if="can('declarant')" to="/tender/customs" active-class="active">
				{{ t("Customs queue") }}
			</router-link>
			<router-link v-if="can('logist')" to="/tender/logistics" active-class="active">
				{{ t("Logistics") }}
			</router-link>
		</div>
	</nav>
</template>

<style scoped>
/* Çubuk sayfanın iç kenar boşluğunu taşırıp tam genişliğe oturuyor: tasarımda
 * modül navı içerik sütununun değil, EKRANIN üstünde duruyor. */
.tender-modnav {
	margin: -12px -12px 16px;
}

@media (min-width: 992px) {
	.tender-modnav {
		margin: -16px -20px 18px;
	}
}
</style>
