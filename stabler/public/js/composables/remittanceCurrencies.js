/**
 * The currencies that cross a remittance corridor — one list, two screens.
 *
 * ADR-003: only hard currencies cross a corridor. UZS/TRY/AED/RUB never enter
 * this module; local cash exchange is a different product. A remittance cash
 * desk may still hold an account in one of them (the Currency select on the
 * settings screen is fed from every enabled Currency, not from this list), and
 * such an account is simply not usable for a transfer.
 *
 * Lives here rather than as a `<script setup>` local because two screens have to
 * agree on it and `<script setup>` bindings are not importable. New Transfer
 * gates its send/receive selects on this set; Remittance Settings answers "can
 * this desk serve a transfer at all" against the same set. When the two were a
 * private constant and a copy of it, adding a fourth currency would have offered
 * it on the form while the settings screen went on reporting a desk that cannot
 * serve it as ready.
 */
export const CORRIDOR_CURRENCIES = ["USD", "EUR", "USDT"];
