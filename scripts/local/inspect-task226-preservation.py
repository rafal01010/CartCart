import json
from hashlib import sha256
from pathlib import Path


root = Path(__file__).resolve().parents[2]
folder = root / "data/artifacts/task226"
before = json.loads((folder / "preservation-before.json").read_text())
changed = [
    name for name, digest in before.items()
    if not (root / name).is_file()
    or sha256((root / name).read_bytes()).hexdigest() != digest
]
assert not changed, changed
checkpoint_path = root / (
    "data/artifacts/source-consultations/37da9a8b-1641-456c-94b4-bcd652c03346/"
    "3bcd0244df8066db5d02113f43ff0dbf6f224548a9eb09de0e4cd84e5c744cb0.json"
)
checkpoint = json.loads(checkpoint_path.read_text())
state = checkpoint["tool_states"]["video_review"]
assert state["searched"] == 2
assert len(state["transcripts_read"]) == 3
assert state["span_reads"] == 10
assert len(checkpoint["attempt_usage"]) == 4
assert len(checkpoint["validated_bundles"]["video_review"]["evidence"]) == 3
assert checkpoint_path.read_bytes() == (
    root / "apps/backend/tests/fixtures/providers/task225_saved_caption_checkpoint.json"
).read_bytes()
segments = {key: len(value["transcript_segments"]) for key, value in state["transcripts"].items()}
assert segments == {"e9WGaciZgsc": 95, "WM9Vkls_8zI": 0, "Dk_FdSDiNeI": 443}
report = {
    "unchanged_files": len(before), "changed": changed,
    "searches": state["searched"], "caption_ids": len(state["transcripts_read"]),
    "span_reads": state["span_reads"], "prior_usage_entries": len(checkpoint["attempt_usage"]),
    "accepted_claims": 3, "caption_segments": segments,
}
(folder / "preservation-after.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
