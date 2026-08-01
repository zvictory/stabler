<script setup>
/* Satış Siparişi formu iki varyant hâlinde yaşıyor ve seçim burada yapılıyor.
 *
 * Klasik form (Tabler kartı, iki sütunlu `so-grid`, sağ ray) varsayılan; yedi
 * kiracının hepsi onu görür. `a0c9457`'nin tek sütunlu / yapışkan-alt-çubuklu
 * yeniden tasarımı `Stabler Company Modules → modern_sales_order` bayrağının
 * arkasında, varsayılan KAPALI. Bir izin değil, bir tercih — bu yüzden
 * `_MODULE_ROLES`'e girmiyor ve rota `meta.module` taşımıyor.
 *
 * Seçim rota katmanında değil burada yapılıyor: `router.js`'teki 205 rotanın
 * tamamı statik `component:` taşıyor, SPA'da hiç `defineAsyncComponent` yok.
 * İnce sarmalayıcı o değişmezi bozmuyor — rota hâlâ tek bir bileşene bakıyor.
 * Her iki varyant da rotayı ve `useDocumentForm`'u kendi içinde okuduğu için
 * prop geçmeye gerek yok. */
import { computed } from "vue";
import { useSession } from "../../stores/session.js";
import SalesOrderFormClassic from "./SalesOrderFormClassic.vue";
import SalesOrderFormModern from "./SalesOrderFormModern.vue";

const session = useSession();
const modern = computed(() => Boolean(session.modules?.modern_sales_order));
</script>

<template>
	<SalesOrderFormModern v-if="modern" />
	<SalesOrderFormClassic v-else />
</template>
