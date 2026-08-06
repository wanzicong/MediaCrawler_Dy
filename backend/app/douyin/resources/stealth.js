// Minimal CDP init script. The attached browser remains a real Chrome/Edge
// session; this only removes the automation flag exposed by Playwright.
Object.defineProperty(navigator, "webdriver", {
  configurable: true,
  get: () => undefined,
});
