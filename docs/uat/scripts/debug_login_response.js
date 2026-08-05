const { chromium } = require('playwright');

(async () => {
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	console.log('Step 1: Logging in as logistics.mikas@erpstable.com...');
	await page.goto('https://mikas.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(1000);

	const emailInputLog = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
	await emailInputLog.fill('logistics.mikas@erpstable.com');
	await page.fill('input[type="password"]', 'MikasUAT2026!');

	const [response] = await Promise.all([
		page.waitForResponse(resp => resp.url().includes('/api/method/login')),
		page.click('button[type="submit"]')
	]);

	console.log('Login status code:', response.status());
	console.log('Login response body:', await response.text());

	await page.waitForTimeout(2000);
	console.log('Current URL after login:', page.url());

	await browser.close();
})();
