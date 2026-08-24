<script setup>
/* Tasarım kurulu kararının mockup'ı, uygulamanın içinden.
 *
 * Mockup tek bir kendine yeten HTML (kendi CSS'i, kendi sekmeleri, sıfır dış
 * kaynak). Uygulamanın içine GÖMMEK yerine iframe'e alıyoruz: mockup'ın stili
 * Tabler ile çakışır, ve bir tasarım kaydının uygulama temasıyla boyanması onu
 * yapılmış bir ekran gibi gösterir — tam olarak kaçındığımız şey.
 *
 * Dosya `stabler/public/mockups/` altında, çünkü `docs/` ve `stabler/docs/`
 * ikisi de `.rsync-exclude`'da: oradan prod'a hiç gitmez. `public/` bench
 * tarafından `sites/assets/stabler`'a bağlanıyor, dolayısıyla aşağıdaki yol
 * dev'de de prod'da da aynı.
 */
import { t } from "../../composables/i18n.js";
import TenderPage from "./TenderPage.vue";

const MOCKUP_URL = "/assets/stabler/mockups/mikas-tender-workflow.html";
</script>

<template>
	<TenderPage :label="`${t('Tender')} · ${t('Design view')}`" :title="t('Workflow mockup')">
		<template #meta>
			<span>{{ t("Nothing on this page is read from a record") }}</span>
			<span>{{
				t("The strip at the top says which parts are built and which are still drawings")
			}}</span>
		</template>

		<template #actions>
			<a class="ds-btn" :href="MOCKUP_URL" target="_blank" rel="noopener">{{
				t("Open in a new tab")
			}}</a>
		</template>

		<iframe
			class="mockup-frame"
			:src="MOCKUP_URL"
			:title="t('Workflow mockup')"
			loading="lazy"
		></iframe>
	</TenderPage>
</template>

<style scoped>
/* Mockup kendi genişliğini yönetiyor; burada yalnız yüksekliği veriyoruz.
 * Sabit bir yükseklik yerine görünüm yüksekliğinden türetiliyor, yoksa uzun
 * sekmelerde iki kaydırma çubuğu üst üste biniyor. */
.mockup-frame {
	display: block;
	width: 100%;
	height: calc(100vh - 230px);
	min-height: 520px;
	border: 1px solid var(--ds-ln);
	border-radius: var(--ds-radius);
	background: #fff;
}
</style>
