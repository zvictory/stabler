/**
 * Whether a Work Order's two shop-floor roles are in a state the backend accepts.
 *
 * One order is run by two people: the pouring operator answers for raw material,
 * the packing operator for film, labels and cartons. `stabler.api.manufacturing`
 * refuses to move material for an order that names one of them and leaves the
 * other empty (`_assert_roles_are_both_or_neither`), because the person who was
 * never named cannot open the order at all — `list_work_orders` filters by the
 * assignee columns — so they never write off their own materials and ERPNext's
 * Manufacture entry sweeps their lines onto whoever presses finish.
 *
 * An order with *neither* role filled is a different state and is allowed: that is
 * a site not using the split. Treating those as broken would mark every legacy
 * order red and dead-button every shop floor on the day this ships.
 *
 * Lives here rather than inside a component because two screens ask the question —
 * the manager's Work Orders list and the operator kiosk — and the backend guard is
 * a third copy of the same rule. Two of them can drift; three certainly would.
 */
export const halfAssigned = (row) => Boolean(row?.operator) !== Boolean(row?.packaging_operator);
