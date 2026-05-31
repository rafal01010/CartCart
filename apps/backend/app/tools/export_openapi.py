from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from app.core.settings import Settings
from app.main import create_app


def export_openapi(output_path: Path) -> dict[str, Any]:
    app = create_app(Settings(_env_file=None))  # type: ignore[call-arg]
    spec = app.openapi()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(spec, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return spec


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print("Usage: python -m app.tools.export_openapi OUTPUT_PATH", file=sys.stderr)
        return 2

    output_path = Path(args[0]).expanduser().resolve()
    spec = export_openapi(output_path)
    print(
        f"Wrote OpenAPI {spec['openapi']} spec with "
        f"{len(spec.get('paths', {}))} paths to {output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
