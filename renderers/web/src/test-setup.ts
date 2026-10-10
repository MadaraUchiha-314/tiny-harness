import "@testing-library/jest-dom/vitest";

// jsdom lacks constructable stylesheets, which the A2UI basic catalog's custom elements
// adopt on connect; a no-op keeps them mountable in unit tests (the visual tests run in
// a real browser).
if (typeof CSSStyleSheet !== "undefined" && !("replaceSync" in CSSStyleSheet.prototype)) {
  Object.defineProperty(CSSStyleSheet.prototype, "replaceSync", { value: () => undefined });
}
if (typeof document !== "undefined" && !("adoptedStyleSheets" in document)) {
  Object.defineProperty(document, "adoptedStyleSheets", { value: [], writable: true });
}
