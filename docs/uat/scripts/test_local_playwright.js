const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

async function runStepForUser(email, routePath, screenshotName) {
	console.log(`Logging in as ${email} on http://127.0.0.1:8000...`);
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	await page.goto('http://127.0.0.1:8000/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	await page.fill('#login-user', email);
	await page.fill('#login-pass', 'MikasUAT2026!');
	await page.click('button.login-submit');
	await page.waitForTimeout(2000);

	// Set localStorage activeCompany to Mikas and refresh session
	await page.evaluate(() => {
		localStorage.setItem('stabler.activeCompany', 'Mikas');
	});

	console.log(`Navigating to ${routePath}...`);
	await page.goto(`http://127.0.0.1:8000/stabler#${routePath}`, { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(3000);

	await page.screenshot({ path: path.join(ARTIFACTS_DIR, screenshotName), fullPage: false, timeout: 5000 });
	console.log(`Screenshot saved: ${screenshotName}`);

	await browser.close();
}

(async () => {
	console.log('Testing local bench 127.0.0.1:8000 for Step 6...');
	try {
		await runStepForUser('logistics.mikas@erpstable.com', '/tender/logistics', '16_logist_board_accepted.png');
		await runStepForUser('declarant.mikas@erpstable.com', '/tender/customs', '17_declarant_customs_released.png');
		console.log('\n--- LOCAL UAT STEP 6 COMPLETE ---');
	} catch (err) {
		console.error('Error in local UAT script:', err);
	}
})();
