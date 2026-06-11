# Stabler App Governance & Agent Rules

## Critical Lifecycle Context
- This file works in conjunction with `AGENTS.md`. `AGENTS.md` remains the supreme source of local instruction. Do not overwrite or degrade it.
- If you are an LLM or agentic workflow reading this repository, you are bound by these rules. Zero deviations are permitted.

## 1. Environment & Dependency Constraints
- **Authoritative package manager:** `npm` only. `package-lock.json` is the sole source of truth.
- **Banned tooling:** Do not use `yarn` or touch `yarn.lock`. Treat `yarn.lock` as a legacy, frozen artifact. Never run `yarn install` or `yarn add`.
- **Frontend core matrix:** Do not introduce syntax, features, composables, or properties requiring versions newer than:
  - `vue`: `3.3.9`
  - `@vue/compiler-sfc`: `3.3.9`
  - `vue-router`: `4.2.5`
  - `pinia`: `2.1.7`
- **Backend environment:** Frappe is bench-managed globally (`frappe~=16.0.0`). Do not add local pip requirements, app-local Frappe dependency pins, or modify Poetry or `pyproject.toml` environments without explicit user approval.

## 2. Architecture & Routing Boundaries
- **SPA engine:** This is a native Vue/Frappe Single Page Application.
- **Routing source of truth:** All routing configuration must live exclusively within `stabler/public/js/router.js`.
- **View layer:** All core interactive interfaces must live under `stabler/public/js/pages/**`.
- **Banned architectures:** Do not introduce Next.js file-system routing, React components, Vite standalone configs, or Tailwind build steps unless explicitly detailed in an approved spec.
- **Frappe Desk containment:** Adhere to the `AGENTS.md` boundary. Do not inject redirect sequences to Frappe Desk (`/app/...`). Missing CRUD, ledgers, or actions must be built inside the Stabler SPA view layer.

## 3. Future Entity Filtering & Catalog Constraint
- There is currently no active `/shop` or catalog domain inside Stabler.
- **Rule of singularity:** If a future spec mandates entity filtering, such as filtering items, partners, or assets by brands, perfumers, notes, or categories, do not create multiple independent listing layouts or duplicate database views.
- Define a single, unified SPA route within `stabler/public/js/router.js` and use URL query parameters, such as `?entity=id`, to drive state.

## 4. UI Frame & Visual Hierarchy
- **Global shell:** Sidebar grouping and module header patterns are shared frame concerns. Keep module home pages aligned to `ModuleHeader.vue` instead of hand-rolling separate header/tab structures.
- **Button hierarchy:** Use at most one `.btn-primary` action per visual region. Secondary actions must use outline, ghost, link, or icon-only treatments so enterprise screens stay scannable under fatigue.
- **Money semantics:** Monetary balances must preserve semantic direction. Use `balanceState()` / `BalanceChip.vue` for customer and supplier balances instead of showing unsigned numbers without context.
- **Dense text:** Use `.stbl-subtext` for quiet supporting metadata and `.stbl-amount` for aligned currency values. Do not let money cells wrap or truncate in ways that hide the amount.
- **Party identity:** Use `PartyAvatar.vue` where customer/supplier/person names need a compact identity anchor in list rows or drawers.
