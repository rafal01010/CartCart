from __future__ import annotations

import asyncio
import html
import importlib.metadata
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from app.providers.contracts import (
    ProviderCapabilityFlags,
    ProviderRunStatus,
    TranscriptAccessStrategy,
    TranscriptProviderOptions,
    TranscriptProviderResult,
)
from app.schemas.search_sources import (
    TranscriptAvailability,
    VideoSource,
    VideoTranscriptSegment,
)


YTDLP_VERSION = "2026.6.9"
YTDLP_EJS_VERSION = "0.8.0"
MINIMUM_DENO_VERSION = (2, 3, 0)

_YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VTT_TIMESTAMP_PATTERN = re.compile(
    r"^(?P<start>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3})(?:\s+.*)?$"
)
_VTT_TAG_PATTERN = re.compile(r"<[^>]+>")
_INLINE_TIMESTAMP_PATTERN = re.compile(r"<(?:\d{2}:)?\d{2}:\d{2}[.,]\d{3}>")
_DENO_VERSION_PATTERN = re.compile(r"^deno\s+(\d+)\.(\d+)\.(\d+)", re.MULTILINE)
_LANGUAGE_PATTERN = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")


@dataclass(frozen=True)
class TranscriptRuntimeIssue:
    code: str
    message: str


@dataclass(frozen=True)
class YtDlpCommandResult:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class YtDlpCommandRunner(Protocol):
    async def run(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        output_limit_bytes: int,
    ) -> YtDlpCommandResult:
        """Run one fixed yt-dlp command in an isolated working directory."""


class YtDlpCommandTimeout(RuntimeError):
    """Raised when the bounded yt-dlp subprocess exceeds its deadline."""


class YtDlpCommandOutputLimit(RuntimeError):
    """Raised when yt-dlp emits more process output than CartCart permits."""


@dataclass(frozen=True)
class SubprocessYtDlpCommandRunner:
    async def run(
        self,
        command: tuple[str, ...],
        *,
        cwd: Path,
        timeout_seconds: float,
        output_limit_bytes: int,
    ) -> YtDlpCommandResult:
        process = await asyncio.create_subprocess_exec(
            *command,
            cwd=cwd,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                asyncio.gather(
                    _read_stream(process.stdout, output_limit_bytes),
                    _read_stream(process.stderr, output_limit_bytes),
                ),
                timeout=timeout_seconds,
            )
            if len(stdout_bytes) + len(stderr_bytes) > output_limit_bytes:
                raise YtDlpCommandOutputLimit
            returncode = await asyncio.wait_for(
                process.wait(),
                timeout=max(1.0, timeout_seconds / 10),
            )
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            raise YtDlpCommandTimeout from exc
        except YtDlpCommandOutputLimit:
            process.kill()
            await process.wait()
            raise

        return YtDlpCommandResult(
            returncode=returncode,
            stdout=stdout_bytes.decode("utf-8", errors="replace"),
            stderr=stderr_bytes.decode("utf-8", errors="replace"),
        )


@dataclass(frozen=True)
class YtDlpTranscriptProvider:
    deno_executable: str = "deno"
    languages: tuple[str, ...] = ("en",)
    timeout_seconds: float = 30.0
    output_limit_bytes: int = 64 * 1024
    temp_storage_limit_bytes: int = 5 * 1024 * 1024
    max_segments: int = 5000
    runner: YtDlpCommandRunner = field(default_factory=SubprocessYtDlpCommandRunner)
    check_runtime_dependencies: bool = True
    provider_name: str = "yt-dlp-transcript"

    def __post_init__(self) -> None:
        _validate_languages(self.languages)

    @property
    def capabilities(self) -> ProviderCapabilityFlags:
        return ProviderCapabilityFlags(
            provider_name=self.provider_name,
            enabled=True,
            uses_official_api=False,
            supports_transcripts=True,
            permits_transcript_text=True,
            transcript_access_strategy=TranscriptAccessStrategy.APPROVED_THIRD_PARTY,
            compliance_notes=(
                "Retrieves public YouTube captions through pinned yt-dlp and yt-dlp-ejs.",
                "Does not use cookies, accounts, remote EJS components, or media downloads.",
            ),
        )

    async def fetch_transcript(
        self,
        video: VideoSource,
        options: TranscriptProviderOptions | None = None,
    ) -> TranscriptProviderResult:
        video_id = validate_youtube_video_source(video)
        if video_id is None:
            return _gap_result(
                self.capabilities,
                video,
                availability=TranscriptAvailability.NOT_CHECKED,
                note="The video identifier or URL is not a valid YouTube video source.",
            )

        if self.check_runtime_dependencies:
            runtime_issues = inspect_ytdlp_transcript_runtime(self.deno_executable)
            if runtime_issues:
                return _gap_result(
                    self.capabilities,
                    video,
                    availability=TranscriptAvailability.NOT_CHECKED,
                    note=(
                        "The YouTube transcript runtime is not ready: "
                        + "; ".join(issue.message for issue in runtime_issues)
                    ),
                )

        languages = _requested_languages(options, self.languages)
        deno_path = _resolve_deno_executable(self.deno_executable)
        if deno_path is None:
            return _gap_result(
                self.capabilities,
                video,
                availability=TranscriptAvailability.NOT_CHECKED,
                note="Deno 2.3.0 or newer is not available for transcript retrieval.",
            )
        canonical_url = f"https://www.youtube.com/watch?v={video_id}"

        with tempfile.TemporaryDirectory(prefix="cartcart-ytdlp-") as temp_name:
            temp_dir = Path(temp_name)
            for automatic in (False, True):
                command = build_ytdlp_transcript_command(
                    video_url=canonical_url,
                    temp_dir=temp_dir,
                    deno_executable=deno_path,
                    languages=languages,
                    automatic=automatic,
                    socket_timeout_seconds=min(self.timeout_seconds, 60.0),
                )
                try:
                    result = await self.runner.run(
                        command,
                        cwd=temp_dir,
                        timeout_seconds=self.timeout_seconds,
                        output_limit_bytes=self.output_limit_bytes,
                    )
                except YtDlpCommandTimeout:
                    return _gap_result(
                        self.capabilities,
                        video,
                        availability=TranscriptAvailability.NOT_CHECKED,
                        note="YouTube transcript retrieval timed out.",
                    )
                except YtDlpCommandOutputLimit:
                    return _gap_result(
                        self.capabilities,
                        video,
                        availability=TranscriptAvailability.NOT_CHECKED,
                        note="YouTube transcript retrieval exceeded the process output limit.",
                    )
                except OSError:
                    return _gap_result(
                        self.capabilities,
                        video,
                        availability=TranscriptAvailability.NOT_CHECKED,
                        note="The YouTube transcript subprocess could not be started.",
                    )

                if _directory_size(temp_dir) > self.temp_storage_limit_bytes:
                    return _gap_result(
                        self.capabilities,
                        video,
                        availability=TranscriptAvailability.NOT_CHECKED,
                        note="YouTube transcript retrieval exceeded the temporary storage limit.",
                    )

                vtt_path = _select_vtt_path(temp_dir, video_id, languages)
                if vtt_path is not None:
                    if vtt_path.stat().st_size > self.temp_storage_limit_bytes:
                        return _gap_result(
                            self.capabilities,
                            video,
                            availability=TranscriptAvailability.NOT_CHECKED,
                            note="The YouTube caption track exceeded the allowed size.",
                        )
                    language = _language_from_vtt_filename(vtt_path, video_id)
                    try:
                        vtt_text = vtt_path.read_text(encoding="utf-8-sig")
                        segments = parse_webvtt_segments(
                            vtt_text,
                            video_id=video_id,
                            language=language,
                            max_segments=self.max_segments,
                        )
                    except (OSError, UnicodeError, ValueError):
                        return _gap_result(
                            self.capabilities,
                            video,
                            availability=TranscriptAvailability.NOT_CHECKED,
                            note="The retrieved YouTube caption track was invalid.",
                        )
                    if segments:
                        updated_video = video.model_copy(
                            update={
                                "transcript_availability": TranscriptAvailability.AVAILABLE
                            }
                        )
                        return TranscriptProviderResult(
                            status=ProviderRunStatus.SUCCEEDED,
                            capabilities=self.capabilities,
                            video=updated_video,
                            availability=TranscriptAvailability.AVAILABLE,
                            segments=segments,
                        )

                failure = classify_ytdlp_transcript_failure(
                    f"{result.stdout}\n{result.stderr}",
                    returncode=result.returncode,
                )
                if automatic or failure != "no_captions":
                    return _result_for_failure(self.capabilities, video, failure)

        return _result_for_failure(self.capabilities, video, "no_captions")


def inspect_ytdlp_transcript_runtime(
    deno_executable: str = "deno",
) -> tuple[TranscriptRuntimeIssue, ...]:
    issues: list[TranscriptRuntimeIssue] = []
    for package_name, expected_version in (
        ("yt-dlp", YTDLP_VERSION),
        ("yt-dlp-ejs", YTDLP_EJS_VERSION),
    ):
        try:
            installed_version = importlib.metadata.version(package_name)
        except importlib.metadata.PackageNotFoundError:
            issues.append(
                TranscriptRuntimeIssue(
                    code=f"missing_{package_name.replace('-', '_')}",
                    message=f"{package_name} {expected_version} is not installed.",
                )
            )
            continue
        if installed_version != expected_version:
            issues.append(
                TranscriptRuntimeIssue(
                    code=f"incompatible_{package_name.replace('-', '_')}",
                    message=(
                        f"{package_name} {installed_version} is installed; "
                        f"version {expected_version} is required."
                    ),
                )
            )

    deno_path = _resolve_deno_executable(deno_executable)
    if deno_path is None:
        issues.append(
            TranscriptRuntimeIssue(
                code="missing_deno",
                message="Deno 2.3.0 or newer is not available on PATH.",
            )
        )
        return tuple(issues)

    try:
        completed = subprocess.run(
            (deno_path, "--version"),
            check=False,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        issues.append(
            TranscriptRuntimeIssue(
                code="unreadable_deno_version",
                message="Deno is present, but its version could not be read.",
            )
        )
        return tuple(issues)

    match = _DENO_VERSION_PATTERN.search(completed.stdout)
    if completed.returncode != 0 or match is None:
        issues.append(
            TranscriptRuntimeIssue(
                code="unreadable_deno_version",
                message="Deno is present, but its version could not be read.",
            )
        )
    elif tuple(int(part) for part in match.groups()) < MINIMUM_DENO_VERSION:
        issues.append(
            TranscriptRuntimeIssue(
                code="incompatible_deno",
                message="Deno 2.3.0 or newer is required for YouTube transcripts.",
            )
        )
    return tuple(issues)


def validate_youtube_video_source(video: VideoSource) -> str | None:
    if not _YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video.video_id):
        return None

    parsed = urlparse(str(video.url))
    host = (parsed.hostname or "").casefold()
    url_video_id: str | None = None
    if host in {"youtu.be", "www.youtu.be"}:
        url_video_id = parsed.path.strip("/").split("/", maxsplit=1)[0]
    elif host in {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
    }:
        if parsed.path == "/watch":
            url_video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/", "/live/")):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                url_video_id = parts[1]
    if url_video_id != video.video_id:
        return None
    return video.video_id


def build_ytdlp_transcript_command(
    *,
    video_url: str,
    temp_dir: Path,
    deno_executable: str,
    languages: tuple[str, ...],
    automatic: bool,
    socket_timeout_seconds: float,
) -> tuple[str, ...]:
    _validate_languages(languages)
    language_selector = ",".join(f"{language}.*" for language in languages)
    subtitle_flag = "--write-auto-subs" if automatic else "--write-subs"
    return (
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-plugin-dirs",
        "--no-remote-components",
        "--no-js-runtimes",
        "--js-runtimes",
        f"deno:{deno_executable}",
        "--skip-download",
        "--no-playlist",
        "--no-progress",
        "--cache-dir",
        str(temp_dir / "cache"),
        "--paths",
        str(temp_dir),
        "--paths",
        f"temp:{temp_dir / 'temp'}",
        "--output",
        "subtitle:%(id)s.%(ext)s",
        "--sub-format",
        "vtt",
        "--sub-langs",
        language_selector,
        "--socket-timeout",
        f"{socket_timeout_seconds:g}",
        "--retries",
        "1",
        subtitle_flag,
        "--",
        video_url,
    )


def parse_webvtt_segments(
    content: str,
    *,
    video_id: str,
    language: str | None,
    max_segments: int = 5000,
) -> tuple[VideoTranscriptSegment, ...]:
    if not content.lstrip("\ufeff").startswith("WEBVTT"):
        raise ValueError("caption content is not WebVTT")

    cues: list[tuple[float, float, str]] = []
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    for block in blocks[1:]:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_index = next(
            (index for index, line in enumerate(lines) if "-->" in line),
            None,
        )
        if timing_index is None:
            continue
        match = _VTT_TIMESTAMP_PATTERN.match(lines[timing_index])
        if match is None:
            continue
        text = _normalize_vtt_text(" ".join(lines[timing_index + 1 :]))
        if not text:
            continue
        start = _parse_vtt_timestamp(match.group("start"))
        end = _parse_vtt_timestamp(match.group("end"))
        if end < start:
            raise ValueError("caption end precedes start")
        cues.append((start, end, text))
        if len(cues) > max_segments * 4:
            raise ValueError("caption cue limit exceeded")

    segments: list[VideoTranscriptSegment] = []
    previous_text = ""
    for start, end, text in cues:
        deduplicated = _remove_rolling_caption_overlap(previous_text, text)
        previous_text = text
        if not deduplicated:
            continue
        segments.append(
            VideoTranscriptSegment(
                video_id=video_id,
                start_seconds=start,
                end_seconds=end,
                language=language,
                text=deduplicated,
            )
        )
        if len(segments) > max_segments:
            raise ValueError("caption segment limit exceeded")
    return tuple(segments)


def classify_ytdlp_transcript_failure(output: str, *, returncode: int) -> str:
    normalized = " ".join(output.casefold().split())
    if any(token in normalized for token in ("429", "too many requests", "rate limit")):
        return "rate_limited"
    if any(
        token in normalized
        for token in (
            "private video",
            "members-only",
            "members only",
            "sign in to confirm your age",
            "login required",
            "not available in your country",
            "copyright claim",
        )
    ):
        return "restricted"
    if any(
        token in normalized
        for token in (
            "challenge",
            "signature solving failed",
            "n-sig",
            "javascript runtime",
            "yt-dlp-ejs",
        )
    ):
        return "challenge_failed"
    if any(
        token in normalized
        for token in (
            "no subtitles",
            "no automatic captions",
            "did not get any subtitles",
            "requested subtitles are not available",
        )
    ):
        return "no_captions"
    if returncode == 0:
        return "no_captions"
    return "unavailable"


async def _read_stream(
    stream: asyncio.StreamReader | None,
    limit: int,
) -> bytes:
    if stream is None:
        return b""
    chunks: list[bytes] = []
    size = 0
    while chunk := await stream.read(4096):
        size += len(chunk)
        if size > limit:
            raise YtDlpCommandOutputLimit
        chunks.append(chunk)
    return b"".join(chunks)


def _requested_languages(
    options: TranscriptProviderOptions | None,
    defaults: tuple[str, ...],
) -> tuple[str, ...]:
    if options is not None and options.language is not None:
        return (options.language,)
    return defaults


def _resolve_deno_executable(executable: str) -> str | None:
    located = shutil.which(executable)
    if located is not None:
        return located
    if Path(executable).name != executable:
        return None
    scripts_dir = "Scripts" if sys.platform == "win32" else "bin"
    environment_candidate = Path(sys.prefix) / scripts_dir / executable
    if environment_candidate.is_file():
        return str(environment_candidate)
    return None


def _validate_languages(languages: tuple[str, ...]) -> None:
    if not languages or len(languages) > 10:
        raise ValueError("one to ten transcript languages are required")
    if any(_LANGUAGE_PATTERN.fullmatch(language) is None for language in languages):
        raise ValueError("transcript languages must be plain BCP 47 language tags")


def _select_vtt_path(
    temp_dir: Path,
    video_id: str,
    languages: tuple[str, ...],
) -> Path | None:
    paths = [path for path in temp_dir.glob(f"{video_id}*.vtt") if path.is_file()]
    if not paths:
        return None

    def rank(path: Path) -> tuple[int, str]:
        language = _language_from_vtt_filename(path, video_id) or ""
        for index, requested in enumerate(languages):
            if language == requested or language.startswith(f"{requested}-"):
                return index, path.name
        return len(languages), path.name

    return min(paths, key=rank)


def _language_from_vtt_filename(path: Path, video_id: str) -> str | None:
    name = path.name
    prefix = f"{video_id}."
    if not name.startswith(prefix) or not name.endswith(".vtt"):
        return None
    language = name[len(prefix) : -len(".vtt")]
    return language or None


def _directory_size(directory: Path) -> int:
    size = 0
    for path in directory.rglob("*"):
        if path.is_file() and not path.is_symlink():
            size += path.stat().st_size
    return size


def _normalize_vtt_text(value: str) -> str:
    without_timestamps = _INLINE_TIMESTAMP_PATTERN.sub("", value)
    without_tags = _VTT_TAG_PATTERN.sub("", without_timestamps)
    return " ".join(html.unescape(without_tags).replace("\u200b", "").split())


def _parse_vtt_timestamp(value: str) -> float:
    fields = value.replace(",", ".").split(":")
    if len(fields) == 2:
        hours = 0
        minutes, seconds = fields
    elif len(fields) == 3:
        hours, minutes, seconds = fields
    else:
        raise ValueError("invalid WebVTT timestamp")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _remove_rolling_caption_overlap(previous: str, current: str) -> str:
    if not previous:
        return current
    if current.casefold() == previous.casefold():
        return ""

    previous_words = previous.split()
    current_words = current.split()
    max_overlap = min(len(previous_words), len(current_words))
    for size in range(max_overlap, 0, -1):
        previous_suffix = [word.casefold() for word in previous_words[-size:]]
        current_prefix = [word.casefold() for word in current_words[:size]]
        if previous_suffix != current_prefix:
            continue
        if size == len(current_words):
            return ""
        if size >= 3 or size == len(previous_words):
            return " ".join(current_words[size:])
    return current


def _result_for_failure(
    capabilities: ProviderCapabilityFlags,
    video: VideoSource,
    failure: str,
) -> TranscriptProviderResult:
    if failure == "no_captions":
        return _gap_result(
            capabilities,
            video,
            status=ProviderRunStatus.SUCCEEDED,
            availability=TranscriptAvailability.UNAVAILABLE,
            note="No public manual or automatic captions were available for this video.",
        )
    if failure == "restricted":
        return _gap_result(
            capabilities,
            video,
            availability=TranscriptAvailability.RESTRICTED,
            note="Public captions were restricted or the video required authentication.",
        )
    if failure == "rate_limited":
        return _gap_result(
            capabilities,
            video,
            availability=TranscriptAvailability.NOT_CHECKED,
            note="YouTube rate-limited public caption retrieval.",
        )
    if failure == "challenge_failed":
        return _gap_result(
            capabilities,
            video,
            availability=TranscriptAvailability.NOT_CHECKED,
            note="YouTube caption retrieval failed during the public access challenge.",
        )
    return _gap_result(
        capabilities,
        video,
        availability=TranscriptAvailability.NOT_CHECKED,
        note="Public YouTube captions could not be retrieved.",
    )


def _gap_result(
    capabilities: ProviderCapabilityFlags,
    video: VideoSource,
    *,
    availability: TranscriptAvailability,
    note: str,
    status: ProviderRunStatus = ProviderRunStatus.UNAVAILABLE,
) -> TranscriptProviderResult:
    return TranscriptProviderResult(
        status=status,
        capabilities=capabilities,
        video=video.model_copy(update={"transcript_availability": availability}),
        availability=availability,
        gap_notes=(note,),
    )
