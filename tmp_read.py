from pathlib import Path
text = Path("src/utils/llm_provider.py").read_text(encoding="utf-8")
parts = text.split("elif provider == \"openrouter\":")
if len(parts) > 1:
    segment = parts[1]
    print(segment.split("elif", 1)[0])
else:
    print("not found")
