<script setup>
/**
 * The transfer list lives in two variants and the choice is made here.
 *
 * They read two different records. The legacy variant calls
 * `stabler.api.remittance.list_remittances`, which queries `tabJournal Entry` for
 * the `Rem-%` stage entries the legacy register wrote. The V1 variant calls
 * `remittance_queries.transfers`, which lists the `Remittance Transfer` doctype.
 * A legacy remittance has no Remittance Transfer behind it — `api/remittance.py`
 * says so on its own face — so pointing a Legacy company at the V1 list does not
 * show it less data, it shows it an empty page where its history used to be, with
 * no error to explain the disappearance.
 *
 * That is what this wrapper prevents: the V1 list was dropped onto this route,
 * which is in the LEGACY tab strip. Its row links are a second reason — they
 * address `/remittance/transfers/<id>`, whose route name is in the router's
 * `REMITTANCE_V1_ROUTES`, so on a Legacy company every row bounced to New Transfer.
 *
 * Same pattern and same reasoning as `NewRemittance.vue` and, before both,
 * `SalesOrderForm.vue`: the route keeps one static component, and the variant that
 * is not rendering never runs its `onMounted` and never issues its requests.
 */
import { useSession } from "../../stores/session.js";
import RemittanceTransfersLegacy from "./RemittanceTransfersLegacy.vue";
import RemittanceTransfersV1 from "./RemittanceTransfersV1.vue";

const session = useSession();
</script>

<template>
	<RemittanceTransfersV1 v-if="session.isRemittanceV1" />
	<RemittanceTransfersLegacy v-else />
</template>
