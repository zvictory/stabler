export const meta = {
  name: 'qa-forms',
  description: 'QA sweep of Stabler SPA forms: lint CLAUDE.md rule violations, prove the bundle builds, smoke-test routes in the live browser',
  whenToUse: 'Before shipping form changes — catches null-doc render crashes, bare money/date inputs, raw ISO dates, and Desk links across every page module; then builds and smoke-tests routes.',
  phases: [
    { title: 'Lint', detail: 'one sonnet agent per page-module dir, structured findings' },
    { title: 'Build', detail: 'bench build --app stabler' },
    { title: 'Smoke', detail: 'sequential chrome-devtools reload of each route (single shared browser)' },
    { title: 'Report', detail: 'plain-JS synthesis of lint+build+smoke' },
  ],
}

// ── Config ──────────────────────────────────────────────────────────────────
const BENCH = '/Users/zafar/frappe-bench-local'
const APP = `${BENCH}/apps/stabler`
const JS = `${APP}/stabler/public/js`
const BASE_URL = 'http://localhost:8000/stabler#'

// Lint groups: each page-module dir (recursive), the loose top-level pages
// (non-recursive), and shared components (recursive — money/date violations
// can live in form widgets too).
const LINT_GROUPS = [
  { label: 'pages/admin', path: `${JS}/pages/admin`, recursive: true },
  { label: 'pages/hr', path: `${JS}/pages/hr`, recursive: true },
  { label: 'pages/installment', path: `${JS}/pages/installment`, recursive: true },
  { label: 'pages/inventory', path: `${JS}/pages/inventory`, recursive: true },
  { label: 'pages/manufacturing', path: `${JS}/pages/manufacturing`, recursive: true },
  { label: 'pages/marketing', path: `${JS}/pages/marketing`, recursive: true },
  { label: 'pages/money', path: `${JS}/pages/money`, recursive: true },
  { label: 'pages/purchasing', path: `${JS}/pages/purchasing`, recursive: true },
  { label: 'pages/remittance', path: `${JS}/pages/remittance`, recursive: true },
  { label: 'pages/sales', path: `${JS}/pages/sales`, recursive: true },
  { label: 'pages/sfa', path: `${JS}/pages/sfa`, recursive: true },
  { label: 'pages (root)', path: `${JS}/pages`, recursive: false },
  { label: 'components', path: `${JS}/components`, recursive: true },
]

// Default smoke routes: every module-home route. Detail-form routes that need a
// record name are added below from args (skipped-with-notice if absent).
const DEFAULT_HOME_ROUTES = [
  '/dashboard', '/money', '/sales', '/purchasing', '/inventory',
  '/manufacturing', '/hr', '/sfa', '/marketing', '/remittance',
  '/installment', '/admin',
]

// ── Schemas ─────────────────────────────────────────────────────────────────
const LINT_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['file', 'line', 'rule', 'severity', 'snippet'],
        properties: {
          file: { type: 'string', description: 'absolute path' },
          line: { type: 'integer' },
          rule: {
            type: 'string',
            enum: ['null-doc-deref', 'money-bare-input', 'date-bare-input', 'raw-iso-date', 'desk-link'],
          },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          snippet: { type: 'string', description: 'the offending line, trimmed' },
        },
      },
    },
  },
}

const BUILD_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['ok', 'summary'],
  properties: {
    ok: { type: 'boolean' },
    summary: { type: 'string', description: 'one line + error tail if failed' },
  },
}

const SMOKE_SCHEMA = {
  type: 'object',
  additionalProperties: false,
  required: ['routes'],
  properties: {
    routes: {
      type: 'array',
      items: {
        type: 'object',
        additionalProperties: false,
        required: ['route', 'ok', 'consoleErrors'],
        properties: {
          route: { type: 'string' },
          ok: { type: 'boolean', description: 'true if #app .page-body present after reload' },
          consoleErrors: {
            type: 'array',
            items: { type: 'string' },
            description:
              'GENUINE app errors only: JS exceptions (TypeError/ReferenceError/Uncaught) or failed /api/method/… XHRs. EXCLUDE broken static media (/files/, /private/files/, gravatar, cdn, image/font assets) — those are dev-bench data gaps, not code defects.',
          },
        },
      },
    },
  },
}

// ── Phase 1: Lint (parallel sonnet, one agent per group) ────────────────────
phase('Lint')
const lintPrompt = (g) => `You are a static linter for the Stabler Vue 3 SPA. Scan every \`.vue\` and \`.js\` file in \`${g.path}\`${g.recursive ? ' (recurse into subdirectories)' : ' (this directory ONLY — do NOT recurse into subdirectories)'} and report violations of these project rules. Use Read/Grep/Glob. Report ONLY real violations — if a file is clean, return nothing for it.

Rules (return rule key + severity):

1. \`null-doc-deref\` (HIGH) — a template expression that dereferences a loaded-document ref (a \`ref(null)\` that is filled by an async load, typically named \`doc\`, \`detail\`, \`record\`, \`entry\`) via dot or bracket access (e.g. \`doc.currency\`, \`detail.items\`) where the access is gated ONLY by an edit-mode flag (\`!editable\`, \`v-else\` of an edit cell, \`mode==='view'\`) and NOT by any of: a \`v-if="<docref>"\` / \`v-if="<docref> && …"\` on the element or an ancestor, optional chaining (\`doc?.currency\`), or a \`<template v-if="<docref>">\` wrapper around the body. This is the render-time crash class. To confirm: trace whether that docref can be null at first paint (it can if the component's \`loading\` ref starts \`false\` in view mode, OR the surrounding block isn't doc-guarded). When unsure whether an ancestor guards it, INCLUDE it as severity medium and say so in the snippet.

2. \`money-bare-input\` (HIGH) — a bare \`<input type="number">\` bound to a MONETARY field (name/label contains rate, amount, paid, price, balance, limit, total, cost, fee). Money inputs MUST use the shared \`MoneyInput\` component. EXCLUDE quantity fields (qty) that carry \`inputmode="decimal"\`, and EXCLUDE percentages and GPS/lat/lng coordinates — those legitimately stay bare.

3. \`date-bare-input\` (MEDIUM) — a bare \`<input type="date">\`. Must use the \`DateInput\` component.

4. \`raw-iso-date\` (MEDIUM) — raw ISO date interpolation in a template, e.g. \`{{ r.posting_date }}\`, \`{{ row.creation }}\`, \`{{ x.modified }}\`, \`{{ d.transaction_date }}\` rendered directly instead of through \`formatDate()\` / \`formatDateTime()\`. Flag interpolations of fields that are clearly dates (posting_date, transaction_date, due_date, *_date, creation, modified, start/end date) NOT wrapped in formatDate/formatDateTime.

5. \`desk-link\` (HIGH) — any link OUT to the Frappe Desk: an \`href\` / \`window.open\` / \`router\` target containing \`/app/\`. The SPA must never link to the Desk.

Return ALL findings via the StructuredOutput tool. \`file\` = absolute path, \`line\` = line number, \`snippet\` = the offending line trimmed (for null-doc-deref, note the docref and why it may be null).`

const lintResults = await parallel(
  LINT_GROUPS.map((g) => () =>
    agent(lintPrompt(g), { label: `lint:${g.label}`, phase: 'Lint', model: 'claude-sonnet-4-6', schema: LINT_SCHEMA })
  )
)
const findings = lintResults.filter(Boolean).flatMap((r) => r.findings || [])
log(`Lint: ${findings.length} finding(s) across ${LINT_GROUPS.length} groups`)

// ── Phase 2: Build ──────────────────────────────────────────────────────────
phase('Build')
const build = await agent(
  `Run the Stabler frontend build and report whether it compiles. Execute exactly:\n\n  cd ${BENCH} && bench build --app stabler 2>&1 | tail -40\n\nReturn ok=true ONLY if the build completed with no errors (look for "DONE" / no "error"/"Build failed"). If it failed, set ok=false and put the last ~15 lines of error output in summary. Use the Bash tool.`,
  { label: 'build:stabler', phase: 'Build', schema: BUILD_SCHEMA }
)
log(`Build: ${build?.ok ? 'PASS' : 'FAIL'}`)

// ── Phase 3: Smoke (sequential — single shared chrome-devtools browser) ──────
phase('Smoke')
let smoke = { routes: [] }
if (args?.skipSmoke) {
  log('Smoke: skipped (args.skipSmoke set)')
} else {
  const sampleSO = args?.salesOrder || 'SAL-ORD-2026-05882'
  const homeRoutes = Array.isArray(args?.routes) ? args.routes : DEFAULT_HOME_ROUTES
  const detailRoutes = sampleSO ? [`/sales/orders/${sampleSO}`] : []
  const routes = [...homeRoutes, ...detailRoutes]
  log(`Smoke: ${routes.length} route(s), SEQUENTIAL (one shared browser). Detail-form routes without a sample name are skipped-with-notice.`)
  smoke = await agent(
    `You are smoke-testing the live Stabler SPA in a SHARED Chrome instance via the chrome-devtools MCP tools. The browser is already authenticated. Because there is ONE shared browser, do every route STRICTLY SEQUENTIALLY — never in parallel.

First load the chrome-devtools tools you need with ToolSearch, e.g. query "select:mcp__plugin_chrome-devtools-mcp_chrome-devtools__navigate_page,mcp__plugin_chrome-devtools-mcp_chrome-devtools__list_console_messages,mcp__plugin_chrome-devtools-mcp_chrome-devtools__evaluate_script,mcp__plugin_chrome-devtools-mcp_chrome-devtools__wait_for".

For EACH route in this list, in order:
${routes.map((r) => `  - ${r}`).join('\n')}

Do:
  1. navigate_page to \`${BASE_URL}<route>\` (hash route — the full URL is the base + the route path).
  2. Reload it (navigate again to the same URL, or use the reload — force a fresh render).
  3. wait briefly for the SPA to render (wait_for a visible element, or a short timeout).
  4. evaluate_script: \`document.querySelector('#app .page-body') !== null\` — this is the route's \`ok\`. (If a route legitimately renders no \`.page-body\`, also accept \`#app .card\`; note that in the result.)
  5. list_console_messages (level \`error\`) AND list_network_requests. Build \`consoleErrors[]\` from GENUINE APP errors only:
       INCLUDE: JS exceptions (\`TypeError\`/\`ReferenceError\`/\`SyntaxError\`/\`Uncaught …\`) — the Vue render-crash class prints a \`TypeError\` here and blanks the page-body, so empty page-body + TypeError is the signal we care about most — AND any failed XHR to an \`/api/method/…\` endpoint (status ≥ 400 in the network log).
       EXCLUDE (do NOT report): broken static media. A bare "Failed to load resource: …" line carries no URL, so attribute it via the network log — if the only failed (status ≥ 400) requests are static assets (URL contains \`/files/\`, \`/private/files/\`, \`secure.gravatar.com\`, \`cdn.jsdelivr.net\`, or ends in an image/font extension like .jpg/.png/.svg/.woff2), they are missing-data/asset gaps on the dev bench, NOT code defects — drop them. A route with a rendered \`.page-body\` and only broken-avatar 404/500s is \`ok:true\` with an empty \`consoleErrors\`.

Return one entry per route via StructuredOutput: { route, ok, consoleErrors[] }. Do not invent routes; test exactly the list above.`,
    { label: 'smoke:routes', phase: 'Smoke', schema: SMOKE_SCHEMA }
  )
  log(`Smoke: ${(smoke?.routes || []).filter((r) => r.ok).length}/${(smoke?.routes || []).length} routes ok`)
}

// ── Phase 4: Report (plain JS, no agent) ────────────────────────────────────
phase('Report')
const bySeverity = (sev) => findings.filter((f) => f.severity === sev).length
const smokeRoutes = smoke?.routes || []
const smokeFailures = smokeRoutes.filter((r) => !r.ok || (r.consoleErrors || []).length)

const report = {
  lint: {
    pass: findings.length === 0,
    total: findings.length,
    high: bySeverity('high'),
    medium: bySeverity('medium'),
    low: bySeverity('low'),
    findings,
  },
  build: {
    pass: Boolean(build?.ok),
    summary: build?.summary || '(no build output)',
  },
  smoke: {
    skipped: Boolean(args?.skipSmoke),
    pass: !args?.skipSmoke && smokeRoutes.length > 0 && smokeFailures.length === 0,
    tested: smokeRoutes.length,
    failures: smokeFailures,
    routes: smokeRoutes,
  },
}
report.overall = report.lint.pass && report.build.pass && (report.smoke.skipped || report.smoke.pass)
log(`QA ${report.overall ? 'GREEN ✓' : 'RED ✗'} — lint ${report.lint.total}, build ${report.build.pass ? 'ok' : 'FAIL'}, smoke ${report.smoke.skipped ? 'skipped' : `${smokeRoutes.length - smokeFailures.length}/${smokeRoutes.length}`}`)
return report
