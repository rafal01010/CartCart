from app.agents.live_verifier_critic import verify_recommendation_guardrails
from test_live_verifier_critic_agent import _verification_input


def test_optional_sources_and_qualifications_do_not_block_model_advice() -> None:
    request = _verification_input(
        final_rationale="Consider this model. Confirm local warranty; counterfeit listings may be a concern."
    )
    request = request.model_copy(
        update={
            "evidence": (),
            "recommendation_bundle": request.recommendation_bundle.model_copy(
                update={"evidence_ids": (), "mode_results": ()}
            ),
        }
    )
    report = verify_recommendation_guardrails(request)
    assert report.approved is True
    assert report.blocking_issues == ()
    assert report.recommendation_bundle == request.recommendation_bundle
