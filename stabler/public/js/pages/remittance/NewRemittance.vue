<script setup>
/**
 * New Transfer lives in two variants and the choice is made here.
 *
 * The legacy variant posts a Journal Entry through
 * `stabler.api.remittance.create_remittance` and picks its own cash, payout and
 * commission accounts. It is what all seven tenants run: `remittance_engine`
 * ships as `Legacy` and is opted OUT of, never into by accident. The V1 variant
 * registers a `Remittance Transfer` through
 * `remittance_commands.register_remittance` and reads its accounts from
 * Remittance Settings.
 *
 * This wrapper exists because of a regression, not for symmetry. The V1 form was
 * dropped straight onto this route, which is in the LEGACY tab strip — so a
 * cashier on a Legacy company opened New Transfer, the form asked Remittance
 * Settings for cash desks that a Legacy company has never configured, and the
 * screen refused to register anything. The old form worked before that change.
 * The engine decides which one renders, and neither variant's `<script setup>`
 * runs unless it is the one rendering — that is the whole point of putting the
 * branch out here instead of inside one of them, where `onMounted` would fire V1
 * requests on a Legacy company.
 *
 * The pattern is `SalesOrderForm.vue`'s, deliberately: the route still points at
 * one static component, so the SPA keeps its "no `defineAsyncComponent` anywhere"
 * invariant, and both variants read the route and the session themselves so
 * nothing has to be passed down.
 *
 * `isRemittanceV1` is resolved before this mounts — the router guard awaits
 * `session.ensureRemittanceEngine()` on every `/remittance/*` navigation — and it
 * reads false for unknown, so a failed read shows the form the company already had.
 */
import { useSession } from "../../stores/session.js";
import NewRemittanceLegacy from "./NewRemittanceLegacy.vue";
import NewRemittanceV1 from "./NewRemittanceV1.vue";

const session = useSession();
</script>

<template>
	<NewRemittanceV1 v-if="session.isRemittanceV1" />
	<NewRemittanceLegacy v-else />
</template>
