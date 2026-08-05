const { chromium } = require('playwright');

(async () => {
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	page.on('console', msg => console.log('BROWSER LOG:', msg.text()));

	console.log('Step 1: Logging in as logistics.mikas@erpstable.com...');
	await page.goto('https://mikas.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2000);

	const emailInputLog = page.locator('input[type="email"], input[name="login_id"], input[type="text"]').first();
	if (await emailInputLog.count() > 0 && await emailInputLog.isVisible()) {
		await emailInputLog.fill('logistics.mikas@erpstable.com');
		await page.fill('input[type="password"]', 'MikasUAT2026!');
		await page.click('button[type="submit"]');
		await page.waitForTimeout(3000);
	}

	await page.goto('https://mikas.erpstable.com/stabler#/tender/logistics', { waitUntil: 'networkidle' });
	await page.waitForTimeout(3000);

	const res = await page.evaluate(async () => {
		const csrf = window.__STABLER__?.csrfToken || '';
		const r = await fetch('/api/method/stabler.api.tender.logist_board?company=Mikas', {
			headers: { 'X-Frappe-CSRF-Token': csrf }
		});
		return await r.json();
	});

	console.log('Evaluated API response:', JSON.stringify(res));

	await browser.close();
})();
