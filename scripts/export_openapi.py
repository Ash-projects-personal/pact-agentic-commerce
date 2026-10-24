"""Export Pact's OpenAPI spec for the APIMatic SDK step (queue item K).

Builds the spec from the FastAPI app object directly, so the export
never depends on a running server. The file this writes,
sdk/pact-openapi.json, is what gets imported into APIMatic to generate
the SDK and the developer portal.

Run with: .venv/bin/python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pact.main import app  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "sdk" / "pact-openapi.json"


def main():
    spec = app.openapi()
    missing = []
    for path, ops in sorted(spec["paths"].items()):
        for method, op in ops.items():
            if not op.get("description"):
                missing.append(f"{method.upper()} {path}")
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(spec, indent=2))
    print(f"Wrote {OUT} ({len(spec['paths'])} paths)")
    if missing:
        print("WARNING: operations still missing a description:")
        for m in missing:
            print(f"  {m}")
        sys.exit(1)
    print("All operations carry a description.")


if __name__ == "__main__":
    main()
