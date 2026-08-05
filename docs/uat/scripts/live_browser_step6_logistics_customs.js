const { chromium } = require('playwright');
const path = require('path');

const ARTIFACTS_DIR = '/Users/zafar/.gemini/antigravity/brain/0e9acec9-ee6b-4ab3-870f-d78d657ba3e5';

(async () => {
	console.log('Launching browser for UAT Step 6 (Logistics & Customs Queue Verification)...');
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	try {
		console.log('Step 1: Logging in as logistics.mikas@erpstable.com...');
		await page.goto('https://mikas.erpstable.com/stabler#/', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		const emailInput = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
		if (await emailInput.count() > 0 && await emailInput.isVisible()) {
			await emailInput.fill('logistics.mikas@erpstable.com');
			await page.fill('input[type="password"]', 'MikasUAT2026!');
			await page.click('button[type="submit"]');
			await page.waitForTimeout(3000);
		}

		console.log('Step 2: Navigating to Logistics Board (/tender/logistics)...');
		await page.goto('https://mikas.erpstable.com/stabler#/tender/logistics', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		await page.screenshot({ path: path.join(ARTIFACTS_DIR, '14_logist_board_queue.png'), fullPage: true });
		console.log('Screenshot saved: 14_logist_board_queue.png');

		console.log('Step 3: Logging in as declarant.mikas@erpstable.com...');
		await page.goto('https://mikas.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(2000);

		const emailInput2 = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
		if (await emailInput2.count() > 0 && await emailInput2.isVisible()) {
			await emailInput2.fill('declarant.mikas@erpstable.com');
			await page.fill('input[type="password"]', 'MikasUAT2026!');
			await page.click('button[type="submit"]');
			await page.waitForTimeout(3000);
		}

		console.log('Step 4: Navigating to Customs Queue (/tender/customs)...');
		await page.goto('https://mikas.erpstable.com/stabler#/tender/customs', { waitUntil: 'domcontentloaded' });
		await page.waitForTimeout(4000);
		await page.screenshot({ path: path.join(ARTIFACTS_DIR, '15_declarant_customs_queue.png'), fullPage: true });
		console.log('Screenshot saved: 15_declarant_customs_queue.png');

		console.log('\n--- UAT STEP 6 EXECUTION COMPLETE ---');
	} catch (err) {
		console.error('Fatal error in UAT Step 6:', err);
	} finally {
		await browser.close();
	}
})();
