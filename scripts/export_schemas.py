"""Export the stable tool boundary: uv run python scripts/export_schemas.py."""

import json
from pathlib import Path

from donewise_harness.contracts import TOOL_SPECS


def export_schemas(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for spec in TOOL_SPECS:
        for direction, model in (("input", spec.input_model), ("output", spec.output_model)):
            path = directory / f"{spec.name}.{direction}.json"
            path.write_text(
                json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
                newline="\n",
            )


if __name__ == "__main__":
    export_schemas(Path(__file__).resolve().parents[1] / "docs" / "schemas")
