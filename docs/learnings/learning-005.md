# Learning 005: A browser used for visual tests must be the one CI uses

- **Date:** 2026-10-10
- **Source:** system-feedback
- **Work item:** issue-3

## What happened

The shadcn rebuild of the web renderer crashed the renderer process of the system
Chromium 152 under Playwright's launch flags, with no console output. The same build
rendered the page correctly when launched by hand, and every suspect CSS feature was
fine in isolation; the bisect cost an hour. Playwright's own Chromium (the build CI
installs) rendered it at once.

## Learning

A visual or accessibility suite is only as reproducible as its browser. Pointing
Playwright at a distribution's Chromium saves a download and nothing else; a crash in
that combination is not a defect in the page.

## Action

The local runs use `bun x playwright install chromium` like CI; `TINY_HARNESS_CHROMIUM`
stays as an escape hatch and the evidence names the browser build it was made with.
