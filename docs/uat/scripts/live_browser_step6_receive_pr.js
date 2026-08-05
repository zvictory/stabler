const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

(async () => {
	console.log('Launching browser for UAT Step 6...');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	page.on('console', msg => console.log('BROWSER LOG:', msg.text()));

	console.log('Logging in as director.mikas@erpstable.com...');
	await page.goto('https://mikas.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', 'director.mikas@erpstable.com');
	await page.fill('#login-pass', 'MikasUAT2026!');
	await page.click('button.login-submit');
	await page.waitForTimeout(3000);

	console.log('Navigating to /tender/logistics as director...');
	await page.goto('https://mikas.erpstable.com/stabler#/tender/logistics', { waitUntil: 'networkidle' });
	await page.waitForTimeout(4000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '16_logist_board_accepted.png'), fullPage: true });

	console.log('Navigating to /tender/customs as director...');
	await page.goto('https://mikas.erpstable.com/stabler#/tender/customs', { waitUntil: 'networkidle' });
	await page.waitForTimeout(4000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, '17_declarant_customs_released.png'), fullPage: true });

	await browser.close();
})();
