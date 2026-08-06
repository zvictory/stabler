const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

async function verifyPilotCi() {
	console.log('=== VERIFYING PILOT COMMERCIAL INVOICE CI-2026-03615 ===');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	await page.goto('https://msa.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'zafar@stable.uz');
	await page.fill('#login-pass', 'MsaUAT2026!');
	await page.click('button.login-submit');
	await page.waitForTimeout(2000);

	await page.evaluate(() => {
		localStorage.setItem('stabler.activeCompany', 'MSA');
	});

	await page.goto('https://msa.erpstable.com/stabler#/imports/commercial-invoices/CI-2026-03615', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '30_pilot_ci_repaired.png'), fullPage: false, timeout: 5000 });
	console.log('Screenshot 30_pilot_ci_repaired.png saved.');

	await browser.close();
}

verifyPilotCi().catch(console.error);
