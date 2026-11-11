"""Build web/maple-chat.html (the phone chat artifact) from web/template.html
and the current knowledge base. Run: python tools/build_web.py"""

import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
kb_dir = root / "knowledge"
manifest = json.loads((kb_dir / "manifest.json").read_text(encoding="utf-8"))

parts = [f'<knowledge_base version="{manifest["version"]}">']
for name in manifest["files"]:
    body = (kb_dir / name).read_text(encoding="utf-8").strip()
    parts.append(f'<file name="{name}">\n{body}\n</file>')
parts.append("</knowledge_base>")
kb_text = "\n\n".join(parts)

# JSON-encode for a JS string literal; keep "</script" from closing the tag.
kb_json = json.dumps(kb_text, ensure_ascii=False).replace("</", "<\\/")
html = (root / "web" / "template.html").read_text(encoding="utf-8")
html = html.replace("__KNOWLEDGE_JSON__", kb_json).replace("__KB_VERSION__", manifest["version"])
out = root / "web" / "maple-chat.html"
out.write_text(html, encoding="utf-8")
print(out, len(html))
