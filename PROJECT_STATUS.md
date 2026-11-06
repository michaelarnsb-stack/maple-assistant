# Project status

_Last updated: 2026-11-06_

## Done
- App v0.1.0: overlay, hotkey, screenshot, fast/deep modes, streaming answers, cost display + monthly ledger, settings dialog (API key, hotkey, opacity, budget warning), tray icon, update banner.
- Tests (15) pass on Linux, including an offscreen UI smoke test.
- Windows build workflow. Release v0.1.0 published from `main`.
- Knowledge base v2026-11-06: overview/rules, patch history to v1.1.0, jobs comparison + builds, training by level, quests/KPQ, economy. Sources: MSCWHub (terms allow personal non-commercial use with attribution), metaroad.gg and classicmaplewiki.com patch summaries.

## Not yet verified
- Real API calls (no key in the dev environment): request shape for `fallbacks="default"` + web search on Sonnet 5.5, Haiku 5.5 with screenshot.
- Behaviour on a real Windows PC: hotkey while the game is focused, focus restore, screenshot of the game in borderless mode, anti-cheat reaction.

## Open
- meowdb.com: robots.txt asks for permission before crawling or bulk reuse - do NOT scrape it into `knowledge/`. Live web-search citations from the app are fine (they allow search/citation bots).
- Knowledge gaps: per-map EXP data (MSCWHub best-leveling-maps body is client-loaded), 1st-job skill details, item/monster stats. Forgotten Hollow open status needs re-checking.
- Player has not chosen a job yet; deepen `10-jobs.md` for the chosen class once known.
- Later: optional weekly scheduled task to refresh knowledge from patch notes.
