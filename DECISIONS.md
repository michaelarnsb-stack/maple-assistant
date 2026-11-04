# Decisions

## 2026-11-04 - Initial architecture
- **Separate public repo**, not the portfolio site repo: GitHub Pages would publish everything, and it mixes concerns. Public (not private) so the app can check Releases and fetch knowledge without a GitHub token. Safe because no secret is ever in the repo.
- **Python + PySide6, packaged by PyInstaller on GitHub Actions** (windows-latest). Qt chosen over tkinter for proper Hebrew RTL/bidi rendering. Player gets a single .exe; trade-off: unsigned exe triggers SmartScreen once.
- **Hotkey via Win32 `RegisterHotKey`**, not keyboard hooks: works when the game is focused/elevated and does not touch game input (anti-cheat risk).
- **Screenshot via `mss` (GDI)** of the foreground window at hotkey time, downscaled to 1600px long edge, JPEG. Requires windowed/borderless game mode.
- **Models**: fast = `claude-haiku-5-5` (effort low, no tools); deep = `claude-sonnet-5-5` (effort medium, web search limited to MapleStory sites, `fallbacks: "default"` for false-positive refusals). Chosen by the user on cost grounds (~$2-5/month expected).
- **Mode switch starts a new conversation** to avoid mixing models/tool sets in one history.
- **Auto new conversation above 80K prompt tokens** (Haiku's price doubles above 100K).
- **Knowledge loading**: GitHub raw (main) -> local cache -> bundled copy. Frozen per conversation.
- **Updates**: app shows a banner linking to the latest Release; it does not self-replace the exe.
