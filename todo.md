# Stabler System Alignment Task List

## Phase 1: Lockfile & Pipeline Safety
- [x] **Enforce single lockfile policy:** Audit `package.json` against `package-lock.json`; identify loose ranges such as `^` or `~`, especially for `@vue-flow/*`, `apexcharts`, and `apextree`.
- [x] **Lockfile isolation:** Remove `yarn.lock` from git tracking to eliminate multi-tool execution risks.
- [x] **Yarn prevention:** Add the npm-only `preinstall` containment check in `package.json`.

## Phase 2: Routing & SPA Security Audit
- [x] **Desk leak scan:** Scan `stabler/public/js` for Frappe Desk leaks, including `/app/...`, `window.open`, and explicit Desk anchors. Result: no matches found.
- [x] **Contract mapping:** Map the current `stabler/public/js/router.js` pattern for future query-parameter-based filtering.

## Audit Findings
- Desk leak scan command: `rg -n "(/app/|window\\.open|href=[\\\"'][^\\\"']*/app)" stabler/public/js`
- Desk leak scan result: no hardcoded Frappe Desk escapes found in `stabler/public/js`.
- SPA routing contract: `stabler/public/js/router.js` imports page components, registers a single `routes` array, uses `createRouter({ history: createWebHashHistory(), routes })`, nests module child routes under parent module shells, and gates module access centrally with `router.beforeEach`.
- Future query-parameter filters should be implemented on the relevant unified SPA route and read from Vue Router route query state instead of creating duplicate listing routes.
