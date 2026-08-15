// Post-wipe verification: confirm all mikas transaction/CRM lists are empty.
// Run: node docs/uat/scripts/live_mikas_wipe_verify.js
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const BASE_URL = 'https://mikas.erpstable.com';
const OUT_DIR = '/Users/zafar/frappe-bench-local/apps/stabler/docs/uat/evidence/2026-08-15-mikas-transaction-wipe';
const SCREENSHOT_DIR = path.join(OUT_DIR, 'screenshots');

function loadSecrets() {
	const envFile = '/Users/zafar/frappe-bench-local/.uat_secrets.env';
	if (fs.existsSync(envFile)) {
		for (const line of fs.readFileSync(envFile, 'utf8').split('\n')) {
			const trimmed = line.trim();
			if (trimmed && trimmed.includes('=')) {
				const idx = trimmed.indexOf('=');
				process.env[trimmed.substring(0, idx)] = trimmed.substring(idx + 1);
			}
		}
	}
	const adminPass = process.env.STABLER_UAT_ADMIN_PASS;
	if (!adminPass) throw new Error('Missing STABLER_UAT_ADMIN_PASS secret.');
	return { adminPass };
}

// [route, label, expected-zero list rows]
const PAGES = [
	['/crm/leads', 'CRM Leads'],
	['/crm/deals', 'CRM Deals'],
	['/tender/my-tenders', 'Tender Master records'],
	['/sales/orders', 'Sales Orders'],
	['/sales/invoices', 'Sales Invoices'],
	['/purchasing/invoices', 'Purchase Invoices'],
	['/purchasing/receipts', 'Purchase Receipts'],
	['/money/payments', 'Payment Entries'],
	['/money/journals', 'Journal Entries'],
	['/tender/rfq', 'Request for Quotations']
];

async function main() {
	const { adminPass } = loadSecrets();
	fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	const loginResp = await page.request.post(`${BASE_URL}/api/method/login`, {
		data: { usr: 'Administrator', pwd: adminPass }
	});
	if (loginResp.status() !== 200) throw new Error(`Login failed: ${loginResp.status()}`);

	const results = { timestamp: new Date().toISOString(), site: BASE_URL, pages: [] };

	for (const [route, label] of PAGES) {
		await page.goto(`${BASE_URL}/stabler#${route}`, { timeout: 60000, waitUntil: 'commit' });
		await page.waitForTimeout(4000);
		const bodyText = (await page.locator('body').innerText()).trim();

		// list rows = table rows excluding header; an empty-state row rendered
		// inside tbody (e.g. "No journal entries in this range") also counts as empty
		const rowCount = await page.locator('table tbody tr').count();
		const rowTexts = await page.locator('table tbody tr').allTextContents();
		const dataRows = rowTexts.filter((txt) => !/no .*(records|data|results|items|leads|deals|invoices|orders|entries|tenders|payments|quotations|range)|kayıt yok|veri yok/i.test(txt));
		const hasEmptyState = rowTexts.some((txt) => /no .*(records|data|results|items|leads|deals|invoices|orders|entries|tenders|payments|quotations|range)|kayıt yok|veri yok/i.test(txt));
		const pass = dataRows.length === 0;
		const shot = path.join(SCREENSHOT_DIR, route.replace(/\//g, '_').replace(/^_/, '') + '.png');
		await page.screenshot({ path: shot, fullPage: false });
		results.pages.push({ route, label, table_rows: dataRows.length, empty_state_shown: hasEmptyState, status: pass ? 'PASS' : 'FAIL' });
		console.log(`[${pass ? 'PASS' : 'FAIL'}] ${label} (${route}): dataRows=${dataRows.length} emptyState=${hasEmptyState}`);
	}

	await browser.close();
	fs.writeFileSync(path.join(OUT_DIR, 'mikas_wipe_verify_results.json'), JSON.stringify(results, null, 1));
	const failed = results.pages.filter((p) => p.status === 'FAIL').length;
	console.log(failed === 0 ? 'ALL PAGES EMPTY ✓' : `${failed} PAGES STILL HAVE ROWS!`);
	process.exit(failed === 0 ? 0 : 1);
}

main().catch((e) => { console.error(e); process.exit(1); });
