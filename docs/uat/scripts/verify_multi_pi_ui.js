const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

async function verifyMultiPiUI() {
	console.log('=== VERIFYING MULTI-PI INVOICES IN LIVE BROWSER ===');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	await page.goto('https://msa.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');
	
	// Wait specifically for successful auth navigation out of /login
	await page.waitForURL('**/stabler#/**', { timeout: 10000 });
	await page.waitForTimeout(2000);

	await page.evaluate(() => {
		localStorage.setItem('stabler.activeCompany', 'MSA');
	});

	// 1. MH/1244/2025-26 (CI-2026-03774 - 5 PIs)
	await page.goto('https://msa.erpstable.com/stabler#/imports/commercial-invoices/CI-2026-03774', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(4000);
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '32_multi_pi_5pis_MH1244.png'), fullPage: false });
	console.log('Screenshot 32_multi_pi_5pis_MH1244.png saved.');

	// 2. MH/1310/2025-26 (CI-2026-03785 - 2 CUBE ROLLs from different PIs)
	await page.goto('https://msa.erpstable.com/stabler#/imports/commercial-invoices/CI-2026-03785', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(4000);
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '33_multi_pi_cuberoll_MH1310.png'), fullPage: false });
	console.log('Screenshot 33_multi_pi_cuberoll_MH1310.png saved.');

	// 3. Discrepancies page
	await page.goto('https://msa.erpstable.com/stabler#/imports/discrepancies', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(4000);
	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '34_discrepancies_final.png'), fullPage: false });
	console.log('Screenshot 34_discrepancies_final.png saved.');

	await browser.close();
}

verifyMultiPiUI().catch(console.error);
