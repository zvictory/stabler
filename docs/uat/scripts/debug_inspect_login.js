const { chromium } = require('playwright');

(async () => {
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await context.newPage();

	console.log('Navigating to /stabler#/login...');
	await page.goto('https://mikas.erpstable.com/stabler#/login', { waitUntil: 'domcontentloaded' });
	await page.waitForTimeout(2000);

	const inputs = await page.evaluate(() => {
		return Array.from(document.querySelectorAll('input, button')).map(el => ({
			tag: el.tagName,
			type: el.type,
			name: el.name,
			id: el.id,
			class: el.className,
			text: el.innerText
		}));
	});

	console.log('Form elements found on login page:', inputs);

	await browser.close();
})();
