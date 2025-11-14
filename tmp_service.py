from pathlib import Path
lines = Path(".venv/Lib/site-packages/browser_use/agent/service.py").read_text(encoding="utf-8").splitlines()
for i in range(1324,1365):
    print(f"{i+1}: {lines[i].encode('unicode_escape').decode()}")
