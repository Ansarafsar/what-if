"""List currently available free models on OpenRouter.

Usage:
    python scripts/list_openrouter_models.py [filter]

Requires no API key. Run from repo root or scripts/ with any Python 3.10+.
"""

import json
import sys
import urllib.request

URL = "https://openrouter.ai/api/v1/models"


def main() -> int:
    query = sys.argv[1].lower() if len(sys.argv) > 1 else ":free"

    with urllib.request.urlopen(URL, timeout=30) as response:
        payload = json.load(response)

    models = payload.get("data", [])
    matches = [
        m for m in models
        if query in m.get("id", "").lower()
        or (query == ":free" and m.get("id", "").endswith(":free"))
    ]

    print(f"{len(matches)} free models matching '{query}':\n")
    for model in sorted(matches, key=lambda m: m["id"]):
        name = model.get("name", "")
        context = model.get("context_length", "?")
        print(f"  {model['id']:<55} ctx={context}")
        print(f"{'':<58}{name}")

    print("\nSet one via LLM_MODEL in .env, e.g. LLM_MODEL=" + (matches[0]["id"] if matches else "<model-id>"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
