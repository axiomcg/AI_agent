from pathlib import Path
lines = Path(".venv/Lib/site-packages/browser_use/agent/views.py").read_text(encoding="utf-8").splitlines()
for i in range(1, 60):
    print(f"{i}: {lines[i-1].encode('unicode_escape').decode()}")
