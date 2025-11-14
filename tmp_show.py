from pathlib import Path
lines = Path("src/utils/llm_provider.py").read_text(encoding="utf-8").splitlines()
for i in range(150, 190):
    print(f"{i+1}: {lines[i].encode('unicode_escape').decode()}")
