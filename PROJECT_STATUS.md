# Project status

_Last updated: 2026-11-04_

## Done
- App v0.1.0: overlay, hotkey, screenshot, fast/deep modes, streaming answers, cost display + monthly ledger, settings dialog (API key, hotkey, opacity, budget warning), tray icon, update banner.
- Tests (15) pass on Linux, including an offscreen UI smoke test.
- Windows build workflow.

## Not yet verified
- Real API calls (no key in the dev environment): request shape for `fallbacks="default"` + web search on Sonnet 5.5, Haiku 5.5 with screenshot.
- Behaviour on a real Windows PC: hotkey while the game is focused, focus restore, screenshot of the game in borderless mode, anti-cheat reaction.

## Open
- Knowledge base is mostly stubs: the dev environment's network policy blocked meowdb.com, massivelyop.com, digitaltq.com. Needs those hosts allowed, then fill `knowledge/` (jobs comparison first - player has not chosen a job).
- Merge to `main` so Releases and remote knowledge work (app fetches knowledge from `main`).
- Later: optional weekly scheduled task to refresh knowledge from patch notes.
