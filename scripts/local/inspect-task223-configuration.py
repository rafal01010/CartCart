"""Print nonsecret effective settings without provider calls. Run from apps/backend."""

import json
from hashlib import sha256
from pathlib import Path

from app.agents.context_management import ContextLimits
from app.agents.openai_config import build_openai_agent_run_configuration
from app.agents.token_policy import OWNER_START_TOKENS, SOURCE_START_TOKENS
from app.core.settings import Settings

settings = Settings()
profiles = {}
for name in (
    "GeneralShoppingAgent",
    "TechnologyDomainAnalystAgent",
    "SmartphoneSpecialistAgent",
    "SourceIntelligenceManagerAgent",
    "YouTubeReviewIntelligenceAgent",
    "VerifierCriticAgent",
):
    config = build_openai_agent_run_configuration(settings, agent_name=name)
    profiles[name] = {
        key: getattr(config, key)
        for key in ("model", "reasoning_effort", "timeout_seconds", "max_turns")
    }
print(
    json.dumps(
        {
            "kind": "local configuration inspection; no calls",
            "context_limits": ContextLimits().__dict__,
            "owner_start": OWNER_START_TOKENS,
            "source_start": SOURCE_START_TOKENS,
            "profiles": profiles,
            "providers": {
                key: getattr(settings, key)
                for key in (
                    "search_provider",
                    "extraction_provider",
                    "video_search_provider",
                    "transcript_provider",
                    "transcript_provider_enabled",
                    "amazon_product_intelligence_provider_enabled",
                    "ikea_store_intelligence_provider_enabled",
                )
            },
            "caption_bounds": {
                key: getattr(settings, key)
                for key in (
                    "youtube_transcript_languages",
                    "youtube_transcript_timeout_seconds",
                    "youtube_transcript_output_limit_bytes",
                    "youtube_transcript_temp_storage_limit_bytes",
                    "youtube_transcript_max_segments",
                )
            },
            "environment_file_sha256": sha256(Path(".env").read_bytes()).hexdigest()
            if Path(".env").exists()
            else None,
        },
        indent=2,
        default=str,
    )
)
