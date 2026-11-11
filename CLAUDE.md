# Maple Assistant

Windows overlay that lets the player ask Claude questions about MapleStory Classic World while playing.

Status and open items: `PROJECT_STATUS.md`. Decision history: `DECISIONS.md`.

## Layout
- `app/` - Python package (PySide6 UI, Anthropic SDK). Entry: `run.py`.
- `knowledge/` - game knowledge base (Markdown + `manifest.json`). Fetched by the app at startup from `main` on GitHub, so knowledge edits ship without a new .exe.
- `tests/` - `python -m pytest -q` (set `QT_QPA_PLATFORM=offscreen` on headless machines).
- `web/` - phone chat page published as a claude.ai Artifact (https://claude.ai/artifact/7feWPHvPdEgDvjpsG9fKQq). Edit `web/template.html`, run `python tools/build_web.py`, republish `web/maple-chat.html` (capability: `sample`). Rebuild after every knowledge change.
- `.github/workflows/build.yml` - builds `MapleAssistant.exe` on Windows; publishes a Release on `main`.

## Rules
- Never commit an API key. Keys live only in Windows Credential Manager on the player's PC.
- Advice only: the app must never send input to, read memory of, or inject into the game process.
- Conversation history is append-only and the system prompt is fixed per conversation (prompt caching + the API's history-editing check on thinking blocks). Changing model or tools means a new conversation.
- Keep `app/prompts.py` byte-stable unless intentionally changing behavior.
- Knowledge files: only verified facts, each with confidence; mark unverified files `Status: STUB`. Bump `version` in `knowledge/manifest.json` on every knowledge change.
- Bump `app/__init__.py` `__version__` for every app release (the Release tag comes from it).
- User-facing text is Hebrew; in-game names stay in English.
