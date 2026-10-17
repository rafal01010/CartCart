import json

from app.agents.live_youtube_review_intelligence import _model_input
from test_task224_caption_focus import saved_caption_tools


def test_resumed_model_sees_saved_caption_status_and_consumed_operations():
    tools, _ = saved_caption_tools()
    before = tools.dump_state()
    payload = json.loads(_model_input(tools.input_data, tools))
    work = payload["saved_caption_work"]
    assert work["searches_consumed"] == 2
    assert work["caption_video_ids_consumed"] == ["Dk_FdSDiNeI", "WM9Vkls_8zI", "e9WGaciZgsc"]
    assert work["span_reads_consumed"] == 6
    assert work["metadata_video_ids_read"] == [
        "Dk_FdSDiNeI", "WM9Vkls_8zI", "e9WGaciZgsc", "ku7MWOaPz6k"
    ]
    assert work["caption_results"] == [
        {"video_id": "Dk_FdSDiNeI", "segment_count": 443, "status": "completed",
         "provider_status": "succeeded", "availability": "available"},
        {"video_id": "WM9Vkls_8zI", "segment_count": 0, "status": "technical_failure",
         "provider_status": "unavailable", "availability": "not_checked", "failure_code": "rate_limited"},
        {"video_id": "e9WGaciZgsc", "segment_count": 95, "status": "completed",
         "provider_status": "succeeded", "availability": "available"},
    ]
    assert "transcript_segments" not in payload
    assert tools.dump_state() == before
