import json
from hashlib import sha256
from pathlib import Path

root = Path(__file__).resolve().parents[2]
folder = root / 'data/artifacts/task225'
before = json.loads((folder / 'preservation-before.json').read_text())
changed = [name for name, digest in before.items() if not (root / name).is_file() or sha256((root / name).read_bytes()).hexdigest() != digest]
checkpoint = json.loads((root / 'data/artifacts/source-consultations/37da9a8b-1641-456c-94b4-bcd652c03346/3bcd0244df8066db5d02113f43ff0dbf6f224548a9eb09de0e4cd84e5c744cb0.json').read_text())
fixture = root / 'apps/backend/tests/fixtures/providers/task225_saved_caption_checkpoint.json'
actual = root / 'data/artifacts/source-consultations/37da9a8b-1641-456c-94b4-bcd652c03346/3bcd0244df8066db5d02113f43ff0dbf6f224548a9eb09de0e4cd84e5c744cb0.json'
assert fixture.read_bytes() == actual.read_bytes()
state = checkpoint['tool_states']['video_review']
assert state['searched'] == 2
assert len(state['transcripts_read']) == 3
assert state['span_reads'] == 10
assert len(checkpoint['attempt_usage']) == 4
assert len(checkpoint['validated_bundles']['video_review']['evidence']) == 3
assert {key: len(value['transcript_segments']) for key, value in state['transcripts'].items()} == {'e9WGaciZgsc': 95, 'WM9Vkls_8zI': 0, 'Dk_FdSDiNeI': 443}
assert not changed, changed
caption_text = {identity: '\n'.join(segment.get('text') or '' for segment in value['transcript_segments']) for identity, value in state['transcripts'].items()}
caption_sizes = {identity: {'characters': len(value), 'utf8_bytes': len(value.encode()), 'local_estimated_tokens': (len(value.encode()) + 2) // 3} for identity, value in caption_text.items()}
report = {'frozen_caption_fixture_exact': True, 'raw_caption_text_sizes': caption_sizes, 'unchanged_files': len(before), 'changed': changed, 'searches': 2, 'caption_ids': 3, 'span_reads': 10, 'prior_usage_entries': 4, 'accepted_claims': 3, 'raw_caption_segments': {'e9WGaciZgsc': 95, 'WM9Vkls_8zI': 0, 'Dk_FdSDiNeI': 443}}
(folder / 'preservation-after.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report))
