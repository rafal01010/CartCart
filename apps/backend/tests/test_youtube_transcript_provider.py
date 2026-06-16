from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.settings import Settings, TranscriptProviderName
from app.providers import (
    FakeTranscriptProvider,
    ProviderRunStatus,
    TranscriptProviderOptions,
    YTDLP_EJS_VERSION,
    YTDLP_VERSION,
    YtDlpCommandResult,
    YtDlpTranscriptProvider,
    build_transcript_provider,
    build_ytdlp_transcript_command,
    inspect_ytdlp_transcript_runtime,
    parse_webvtt_segments,
)
from app.schemas.search_sources import TranscriptAvailability, VideoSource


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "providers"
VIDEO_ID = "BaW_jenozKc"


class FixtureYtDlpRunner:
    def __init__(
        self,
        responses: list[YtDlpCommandResult],
        *,
        write_on_call: int | None = None,
    ) -> None:
        self.responses = responses
        self.write_on_call = write_on_call
        self.commands: list[tuple[str, ...]] = []
        self.working_directories: list[Path] = []

    async def run(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        output_limit_bytes: int,
    ) -> YtDlpCommandResult:
        del timeout_seconds, output_limit_bytes
        self.commands.append(command)
        self.working_directories.append(cwd)
        call_number = len(self.commands)
        if self.write_on_call == call_number:
            content = (FIXTURE_DIR / "youtube_transcript_en.vtt").read_text(
                encoding="utf-8"
            )
            (cwd / f"{VIDEO_ID}.en.vtt").write_text(content, encoding="utf-8")
        return self.responses[call_number - 1]


def _video(video_id: str = VIDEO_ID) -> VideoSource:
    return VideoSource(
        video_id=video_id,
        url=f"https://www.youtube.com/watch?v={video_id}",
        title="Fixture public-caption video",
    )


def test_webvtt_parser_normalizes_timestamps_tags_and_rolling_captions() -> None:
    content = (FIXTURE_DIR / "youtube_transcript_en.vtt").read_text(encoding="utf-8")

    segments = parse_webvtt_segments(
        content,
        video_id=VIDEO_ID,
        language="en",
    )

    assert [segment.text for segment in segments] == [
        "Hello & welcome",
        "to this review",
        "the screen is bright",
        "The stand feels stable.",
    ]
    assert segments[0].start_seconds == 0
    assert segments[0].end_seconds == 2
    assert segments[2].start_seconds == 3.5
    assert all(segment.language == "en" for segment in segments)


def test_webvtt_parser_rejects_non_vtt_and_segment_overflow() -> None:
    with pytest.raises(ValueError, match="not WebVTT"):
        parse_webvtt_segments("plain text", video_id=VIDEO_ID, language="en")

    content = (FIXTURE_DIR / "youtube_transcript_en.vtt").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="segment limit"):
        parse_webvtt_segments(
            content,
            video_id=VIDEO_ID,
            language="en",
            max_segments=2,
        )


def test_fixed_command_disables_config_plugins_remote_ejs_and_media_downloads(
    tmp_path: Path,
) -> None:
    command = build_ytdlp_transcript_command(
        video_url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
        temp_dir=tmp_path,
        deno_executable="/opt/deno/bin/deno",
        languages=("en", "en-US"),
        automatic=False,
        socket_timeout_seconds=12,
    )

    assert command[:3] == (command[0], "-m", "yt_dlp")
    assert "--ignore-config" in command
    assert "--no-plugin-dirs" in command
    assert "--no-remote-components" in command
    assert "--no-js-runtimes" in command
    assert command[command.index("--js-runtimes") + 1] == ("deno:/opt/deno/bin/deno")
    assert "--skip-download" in command
    assert "--no-playlist" in command
    assert "--write-subs" in command
    assert "--write-auto-subs" not in command
    assert command[-2:] == (
        "--",
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
    )
    assert not any("cookie" in argument for argument in command)
    assert not any("remote-components=" in argument for argument in command)

    with pytest.raises(ValueError, match="BCP 47"):
        build_ytdlp_transcript_command(
            video_url=f"https://www.youtube.com/watch?v={VIDEO_ID}",
            temp_dir=tmp_path,
            deno_executable="deno",
            languages=("en,--cookies-from-browser",),
            automatic=True,
            socket_timeout_seconds=12,
        )


@pytest.mark.asyncio
async def test_provider_prefers_manual_subtitles_and_cleans_temp_directory() -> None:
    runner = FixtureYtDlpRunner(
        [YtDlpCommandResult(returncode=0)],
        write_on_call=1,
    )
    provider = YtDlpTranscriptProvider(
        runner=runner,
        check_runtime_dependencies=False,
    )

    result = await provider.fetch_transcript(_video())

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.availability == TranscriptAvailability.AVAILABLE
    assert result.segments
    assert len(runner.commands) == 1
    assert "--write-subs" in runner.commands[0]
    assert "--write-auto-subs" not in runner.commands[0]
    assert all(not directory.exists() for directory in runner.working_directories)


@pytest.mark.asyncio
async def test_provider_falls_back_to_automatic_captions_without_fixture_text() -> None:
    runner = FixtureYtDlpRunner(
        [
            YtDlpCommandResult(
                returncode=1,
                stderr="ERROR: no subtitles for the requested languages",
            ),
            YtDlpCommandResult(returncode=0),
        ],
        write_on_call=2,
    )
    provider = YtDlpTranscriptProvider(
        runner=runner,
        check_runtime_dependencies=False,
    )

    result = await provider.fetch_transcript(
        _video(),
        TranscriptProviderOptions(language="en"),
    )

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.availability == TranscriptAvailability.AVAILABLE
    assert len(runner.commands) == 2
    assert "--write-subs" in runner.commands[0]
    assert "--write-auto-subs" in runner.commands[1]
    assert all(
        segment.text != "Fixture transcript segment" for segment in result.segments
    )


@pytest.mark.asyncio
async def test_provider_rejects_unvalidated_video_without_starting_subprocess() -> None:
    runner = FixtureYtDlpRunner([YtDlpCommandResult(returncode=0)])
    provider = YtDlpTranscriptProvider(
        runner=runner,
        check_runtime_dependencies=False,
    )
    invalid_video = VideoSource(
        video_id="invalid;rm",
        url="https://www.youtube.com/watch?v=BaW_jenozKc",
    )

    result = await provider.fetch_transcript(invalid_video)

    assert result.status == ProviderRunStatus.UNAVAILABLE
    assert result.segments == ()
    assert result.gap_notes
    assert runner.commands == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("stderr", "availability", "expected_note"),
    (
        (
            "ERROR: This is a private video",
            TranscriptAvailability.RESTRICTED,
            "restricted",
        ),
        (
            "ERROR: HTTP Error 429: Too Many Requests",
            TranscriptAvailability.NOT_CHECKED,
            "rate-limited",
        ),
        (
            "ERROR: signature solving failed during challenge",
            TranscriptAvailability.NOT_CHECKED,
            "challenge",
        ),
    ),
)
async def test_provider_preserves_sanitized_access_failures(
    stderr: str,
    availability: TranscriptAvailability,
    expected_note: str,
) -> None:
    runner = FixtureYtDlpRunner([YtDlpCommandResult(returncode=1, stderr=stderr)])
    provider = YtDlpTranscriptProvider(
        runner=runner,
        check_runtime_dependencies=False,
    )

    result = await provider.fetch_transcript(_video())

    assert result.status == ProviderRunStatus.UNAVAILABLE
    assert result.availability == availability
    assert result.segments == ()
    assert expected_note in result.gap_notes[0]
    assert stderr not in result.gap_notes[0]


@pytest.mark.asyncio
async def test_provider_returns_explicit_no_caption_gap_after_both_attempts() -> None:
    runner = FixtureYtDlpRunner(
        [
            YtDlpCommandResult(returncode=0),
            YtDlpCommandResult(returncode=0),
        ]
    )
    provider = YtDlpTranscriptProvider(
        runner=runner,
        check_runtime_dependencies=False,
    )

    result = await provider.fetch_transcript(_video())

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.availability == TranscriptAvailability.UNAVAILABLE
    assert result.segments == ()
    assert "No public manual or automatic captions" in result.gap_notes[0]


def test_transcript_runtime_builds_fixture_disabled_and_live_modes() -> None:
    default_provider = build_transcript_provider(Settings(_env_file=None))  # type: ignore[call-arg]
    disabled_provider = build_transcript_provider(  # type: ignore[call-arg]
        Settings(
            _env_file=None,
            transcript_provider=TranscriptProviderName.DISABLED,
        )
    )
    live_provider = build_transcript_provider(  # type: ignore[call-arg]
        Settings(
            _env_file=None,
            transcript_provider=TranscriptProviderName.YT_DLP,
            transcript_provider_enabled=True,
            youtube_transcript_languages=("en", "ja"),
        )
    )

    assert isinstance(default_provider, FakeTranscriptProvider)
    assert isinstance(disabled_provider, FakeTranscriptProvider)
    assert disabled_provider.disabled is True
    assert isinstance(live_provider, YtDlpTranscriptProvider)
    assert live_provider.languages == ("en", "ja")


def test_runtime_readiness_checks_pinned_packages_and_minimum_deno(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = {"yt-dlp": YTDLP_VERSION, "yt-dlp-ejs": YTDLP_EJS_VERSION}
    monkeypatch.setattr(
        "app.providers.youtube_transcript.importlib.metadata.version",
        versions.__getitem__,
    )
    monkeypatch.setattr(
        "app.providers.youtube_transcript.shutil.which",
        lambda executable: f"/opt/bin/{executable}",
    )
    monkeypatch.setattr(
        "app.providers.youtube_transcript.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="deno 2.3.0 (stable)\n",
            stderr="",
        ),
    )

    assert inspect_ytdlp_transcript_runtime() == ()


def test_runtime_readiness_finds_deno_in_active_python_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    versions = {"yt-dlp": YTDLP_VERSION, "yt-dlp-ejs": YTDLP_EJS_VERSION}
    deno_path = tmp_path / "bin" / "deno"
    deno_path.parent.mkdir()
    deno_path.write_text("fixture", encoding="utf-8")
    monkeypatch.setattr(
        "app.providers.youtube_transcript.importlib.metadata.version",
        versions.__getitem__,
    )
    monkeypatch.setattr(
        "app.providers.youtube_transcript.shutil.which",
        lambda executable: None,
    )
    monkeypatch.setattr("app.providers.youtube_transcript.sys.prefix", str(tmp_path))
    monkeypatch.setattr(
        "app.providers.youtube_transcript.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="deno 2.8.1 (stable)\n",
            stderr="",
        ),
    )

    assert inspect_ytdlp_transcript_runtime() == ()


def test_runtime_readiness_reports_incompatible_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    versions = {"yt-dlp": "2025.1.1", "yt-dlp-ejs": YTDLP_EJS_VERSION}
    monkeypatch.setattr(
        "app.providers.youtube_transcript.importlib.metadata.version",
        versions.__getitem__,
    )
    monkeypatch.setattr(
        "app.providers.youtube_transcript.shutil.which",
        lambda executable: f"/opt/bin/{executable}",
    )
    monkeypatch.setattr(
        "app.providers.youtube_transcript.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="deno 2.2.9 (stable)\n",
            stderr="",
        ),
    )

    issues = inspect_ytdlp_transcript_runtime()

    assert {issue.code for issue in issues} == {
        "incompatible_yt_dlp",
        "incompatible_deno",
    }


def test_transcript_language_option_rejects_yt_dlp_argument_content() -> None:
    with pytest.raises(ValidationError):
        TranscriptProviderOptions(language="en,--cookies-from-browser")


@pytest.mark.live_provider
@pytest.mark.asyncio
async def test_live_ytdlp_transcript_provider_is_explicitly_opt_in() -> None:
    if os.getenv("CARTCART_RUN_LIVE_PROVIDER_TESTS") != "1":
        pytest.skip("live provider tests require explicit opt-in")
    video_id = os.getenv("CARTCART_YOUTUBE_TRANSCRIPT_LIVE_VIDEO_ID")
    if not video_id:
        pytest.skip("set a public captioned video ID for the live transcript test")

    provider = YtDlpTranscriptProvider()
    result = await provider.fetch_transcript(_video(video_id))

    assert result.status == ProviderRunStatus.SUCCEEDED
    assert result.availability == TranscriptAvailability.AVAILABLE
    assert result.segments
