import asyncio
import sqlite3
from pathlib import Path
from uuid import UUID

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
import pytest

from app.services.guided_intake import _fixture_sessions
import test_guided_intake_api as fixtures


guided_api_client = fixtures.guided_api_client


def _cold(session_id: str) -> None:
    _fixture_sessions.pop(UUID(session_id), None)


def _answer(client: TestClient, session_id: str, question_id: str, text: str) -> dict:
    response = fixtures._answer_guided_question(client, session_id, question_id, text)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize('budget', ['$1200', 'Budget is not a constraint.'])
@pytest.mark.parametrize('region_status', ['provided', 'refused'])
def test_cold_skip_and_region_preserve_saved_details(
    guided_api_client: TestClient, budget: str, region_status: str,
) -> None:
    client = guided_api_client
    original = 'https://shop.example/items/original'
    session_id = fixtures._create_guided_session(client, original)['session_id']
    setup = {'status': region_status}
    if region_status == 'provided':
        setup['region'] = {'country_code': 'US', 'currency': 'USD'}
    assert client.post(f'/api/sessions/{session_id}/guide/region', json=setup).status_code == 200
    _answer(client, session_id, 'shopping-goal', 'Choose a laptop for homework')
    _answer(client, session_id, 'budget', budget)
    _answer(client, session_id, 'considered-products', 'ThinkPad X1 Carbon and https://shop.example/items/x1')
    before = client.get(f'/api/sessions/{session_id}').json()
    _cold(session_id)
    loaded = client.get(f'/api/sessions/{session_id}/guide')
    assert loaded.status_code == 200
    assert loaded.json()['region_setup']['status'] == region_status
    skipped = client.post(f'/api/sessions/{session_id}/guide/skip-all')
    assert skipped.status_code == 200
    assert skipped.json()['ready_brief'] == before['current_brief']
    after = client.get(f'/api/sessions/{session_id}').json()
    assert after['original_input']['query'] == original
    assert after['user_added_products'] == before['user_added_products']
    assert after['current_brief'] == before['current_brief']
    changed = client.post(f'/api/sessions/{session_id}/guide/region', json={
        'status': 'provided', 'region': {'country_code': 'PH', 'currency': 'PHP'},
    })
    assert changed.status_code == 200
    ready = client.post(f'/api/sessions/{session_id}/guide/skip-all').json()['ready_brief']
    assert ready['region']['region']['country_code'] == 'PH'
    assert ready['budget'] == before['current_brief']['budget']
    assert ready['preferences'] == before['current_brief']['preferences']
    assert client.get(f'/api/sessions/{session_id}').json()['user_added_products'] == before['user_added_products']
    run = client.post(f'/api/sessions/{session_id}/runs')
    assert run.status_code == 201
    assert client.get(f'/api/sessions/{session_id}').json()['current_brief']['region']['region']['country_code'] == 'PH'


def test_cold_unanswered_prompt_skip_keeps_candidates_and_allows_deliberate_budget_revision(
    guided_api_client: TestClient,
) -> None:
    client = guided_api_client
    other = fixtures._create_guided_session(client, 'Which laptop?')['session_id']
    _answer(client, other, 'budget', '$1200')
    _answer(client, other, 'considered-products', 'ThinkPad X1 Carbon')
    _cold(other)
    before = client.get(f'/api/sessions/{other}').json()
    assert client.post(f'/api/sessions/{other}/guide/skip-all').status_code == 200
    assert client.get(f'/api/sessions/{other}').json()['user_added_products'] == before['user_added_products']
    assert client.post(f'/api/sessions/{other}/guide/reanswer', json={'question_id': 'budget'}).status_code == 200
    revised = _answer(client, other, 'budget', '$900')
    assert revised['ready_brief']['budget']['amount'] == {'amount': '900', 'currency': 'USD'}
    _cold(other)
    assert client.post(f'/api/sessions/{other}/guide/skip-all').json()['ready_brief']['budget']['amount']['amount'] == '900'


def test_region_migration_is_nullable_and_preserves_existing_session(tmp_path: Path, monkeypatch) -> None:
    database_path = tmp_path / 'migration.sqlite3'
    monkeypatch.setenv('CARTCART_DATABASE_PATH', str(database_path))
    config = Config(str(Path(__file__).parents[1] / 'alembic.ini'))
    command.upgrade(config, '0005')
    with sqlite3.connect(database_path) as db:
        db.execute("INSERT INTO shopping_sessions VALUES (?, ?, ?, ?, ?, ?)", (
            'old-session', 'Original question', '{"query":"Original question"}',
            '{"original_query":"Original question"}', '2026-10-19', '2026-10-19',
        ))
        before = db.execute('SELECT * FROM shopping_sessions').fetchall()
    command.upgrade(config, 'head')
    with sqlite3.connect(database_path) as db:
        after = db.execute('SELECT * FROM shopping_sessions').fetchall()
        assert after == [(*before[0], None, None)]
        assert db.execute('SELECT version_num FROM alembic_version').fetchone() == ('0006',)


@pytest.mark.parametrize('initial,revised', [
    ('Must have a matte screen', 'Must have a glossy screen'),
    ('Prefer quiet operation', 'Prefer portability'),
])
def test_cold_reanswer_replaces_owned_preferences_and_constraints(
    guided_api_client: TestClient, initial: str, revised: str,
) -> None:
    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Between two laptops')['session_id']
    _answer(client, session_id, 'comparison-priority', initial)
    _cold(session_id)
    assert client.post(f'/api/sessions/{session_id}/guide/reanswer', json={
        'question_id': 'comparison-priority',
    }).status_code == 200
    changed = _answer(client, session_id, 'comparison-priority', revised)
    texts = [item['text'] for item in changed['ready_brief']['preferences'] + changed['ready_brief']['constraints']]
    assert revised in texts
    assert initial not in texts


@pytest.mark.parametrize('cold', [False, True])
@pytest.mark.parametrize('country,currency,budget,new_country,new_currency', [
    ('US', 'USD', 'USD 1200', 'PH', 'PHP'),
    ('PH', 'PHP', 'PHP 40000', 'US', 'USD'),
    ('PH', 'PHP', 'php 40000', 'US', 'USD'),
])
def test_region_edit_keeps_explicit_budget_currency_and_captured_candidates(
    guided_api_client: TestClient, cold: bool, country: str, currency: str,
    budget: str, new_country: str, new_currency: str,
) -> None:
    client = guided_api_client
    created = client.post('/api/sessions/guided', json={
        'query': 'Which laptop?',
        'region_setup': {'status': 'provided', 'region': {'country_code': country, 'currency': currency}},
    }).json()
    session_id = created['session_id']
    _answer(client, session_id, 'budget', budget)
    _answer(client, session_id, 'considered-products', 'ThinkPad X1 Carbon')
    before = client.get(f'/api/sessions/{session_id}').json()
    if cold:
        _cold(session_id)
    changed = client.post(f'/api/sessions/{session_id}/guide/region', json={
        'status': 'provided', 'region': {'country_code': new_country, 'currency': new_currency},
    })
    assert changed.status_code == 200
    after = client.get(f'/api/sessions/{session_id}').json()
    assert after['current_brief']['region']['region']['country_code'] == new_country
    assert after['current_brief']['budget'] == before['current_brief']['budget']
    assert after['user_added_products'] == before['user_added_products']
    assert after['original_input'] == before['original_input']
    assert client.post(f'/api/sessions/{session_id}/guide/region', json={'status': 'refused'}).status_code == 200
    _cold(session_id)
    guide = client.get(f'/api/sessions/{session_id}/guide').json()
    assert guide['region_setup']['status'] == 'refused'
    assert client.post(f'/api/sessions/{session_id}/guide/skip-all').json()['ready_brief']['budget'] == before['current_brief']['budget']


def test_cold_recovery_preserves_saved_brief_corrections(guided_api_client: TestClient) -> None:
    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Which laptop?')['session_id']
    _answer(client, session_id, 'budget', '$1200')
    patched = client.patch(f'/api/sessions/{session_id}/brief', json={
        'category': 'portable computer', 'category_source': 'user_provided',
        'preferences': [{'text': 'Prefer repairability', 'mode': 'soft', 'source': 'user_provided'}],
        'budget': {'amount': {'amount': '900', 'currency': 'USD'}, 'mode': 'hard_cap', 'source': 'user_provided'},
    })
    assert patched.status_code == 200, patched.text
    before = client.get(f'/api/sessions/{session_id}').json()['current_brief']
    _cold(session_id)
    ready = client.post(f'/api/sessions/{session_id}/guide/skip-all').json()['ready_brief']
    assert ready['budget'] == before['budget']
    assert ready['category'] == 'portable computer'
    assert ready['category_source'] == 'user_provided'
    assert ready['preferences'] == before['preferences']
    assert ready['constraints'] == before['constraints']


def test_initial_query_budget_survives_cold_skip(guided_api_client: TestClient) -> None:
    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Which laptop under USD 1200?')['session_id']
    _cold(session_id)
    ready = client.post(f'/api/sessions/{session_id}/guide/skip-all').json()['ready_brief']
    assert ready['budget']['amount'] == {'amount': '1200', 'currency': 'USD'}


def test_legacy_without_answer_snapshot_preserves_saved_brief_and_products(
    guided_api_client: TestClient,
) -> None:
    from app.db.models.sessions import ShoppingSessionRecord
    from app.db.session import get_db_session

    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Which laptop?')['session_id']
    _answer(client, session_id, 'budget', '$1200')
    _answer(client, session_id, 'considered-products', 'ThinkPad X1 Carbon')
    before = client.get(f'/api/sessions/{session_id}').json()

    async def erase_legacy_metadata() -> None:
        async for db in client.app.dependency_overrides[get_db_session]():
            record = await db.get(ShoppingSessionRecord, session_id)
            assert record is not None
            record.guided_answers = None
            await db.commit()

    asyncio.run(erase_legacy_metadata())
    _cold(session_id)
    assert client.get(f'/api/sessions/{session_id}/guide').status_code == 200
    assert client.post(f'/api/sessions/{session_id}/guide/skip').status_code == 200
    after = client.get(f'/api/sessions/{session_id}').json()
    assert after['current_brief'] == before['current_brief']
    assert after['user_added_products'] == before['user_added_products']


def test_uppercase_budget_words_are_not_currency_codes(guided_api_client: TestClient) -> None:
    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Need a laptop, MAX 1200')['session_id']
    ready = client.post(f'/api/sessions/{session_id}/guide/skip-all').json()['ready_brief']
    assert ready['budget'] is None


def test_legacy_budget_revision_replaces_standalone_old_constraint(
    guided_api_client: TestClient,
) -> None:
    from app.db.models.sessions import ShoppingSessionRecord
    from app.db.session import get_db_session

    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Which laptop?')['session_id']
    _answer(client, session_id, 'budget', 'Must be under USD 1200')

    async def erase_answer_snapshot() -> None:
        async for db in client.app.dependency_overrides[get_db_session]():
            record = await db.get(ShoppingSessionRecord, session_id)
            assert record is not None
            record.guided_answers = None
            await db.commit()

    asyncio.run(erase_answer_snapshot())
    _cold(session_id)
    assert client.post(f'/api/sessions/{session_id}/guide/reanswer', json={
        'question_id': 'budget',
    }).status_code == 200
    ready = _answer(client, session_id, 'budget', 'USD 900')['ready_brief']
    assert ready['budget']['amount'] == {'amount': '900', 'currency': 'USD'}
    assert ready['constraints'] == []
    assert ready['preferences'] == [{
        'text': 'USD 900', 'mode': 'soft', 'source': 'user_provided',
    }]


def test_cold_corrected_goal_reaches_scope_check_before_readiness(
    guided_api_client: TestClient,
) -> None:
    from app.agents.contracts import ShoppingScopeGuardrailInput
    from app.api.routes.guided_intake import DbSession, _guided_service
    from app.db.repositories.sessions import SessionRepository
    from app.db.session import get_db_session
    from app.schemas.guided_intake import ShoppingGuardrailResult
    from app.services.guided_intake import GuidedIntakeService

    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Which laptop for travel?')['session_id']
    _answer(client, session_id, 'budget', '$1200')
    corrected_goal = 'Which camera for family photos?'

    async def correct_saved_goal() -> None:
        async for db in client.app.dependency_overrides[get_db_session]():
            repository = SessionRepository(db)
            saved = await repository.get(UUID(session_id))
            assert saved is not None
            await repository.update_current_brief(
                UUID(session_id), saved.current_brief.model_copy(update={'original_query': corrected_goal}),
            )
            await db.commit()

    asyncio.run(correct_saved_goal())
    _cold(session_id)
    inputs: list[ShoppingScopeGuardrailInput] = []

    class RecordingGuardrail:
        async def run(self, input_data: ShoppingScopeGuardrailInput) -> ShoppingGuardrailResult:
            inputs.append(input_data)
            return ShoppingGuardrailResult(decision='allowed')

    def recording_service(db_session: DbSession) -> GuidedIntakeService:
        return GuidedIntakeService(db_session, guardrail=RecordingGuardrail())

    client.app.dependency_overrides[_guided_service] = recording_service
    loaded = client.get(f'/api/sessions/{session_id}/guide')
    assert loaded.status_code == 200
    assert inputs[0].user_input == corrected_goal
    ready = client.post(f'/api/sessions/{session_id}/guide/skip-all')
    assert ready.status_code == 200
    assert ready.json()['ready_brief']['original_query'] == corrected_goal
    assert len(inputs) == 1
    assert client.get(f'/api/sessions/{session_id}').json()['original_input']['query'] == 'Which laptop for travel?'


@pytest.mark.parametrize('unlimited', [False, True])
def test_legacy_missing_budget_uses_original_cap_unless_explicitly_unlimited(
    guided_api_client: TestClient, unlimited: bool,
) -> None:
    from app.db.models.sessions import ShoppingSessionRecord
    from app.db.session import get_db_session

    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Which laptop under USD 1200?')['session_id']

    async def restore_legacy_missing_budget() -> None:
        async for db in client.app.dependency_overrides[get_db_session]():
            record = await db.get(ShoppingSessionRecord, session_id)
            assert record is not None
            record.guided_answers = None
            record.current_brief = {
                **record.current_brief,
                'budget': None,
                'preferences': [{'text': 'Budget is not a constraint.', 'mode': 'soft', 'source': 'user_provided'}] if unlimited else [],
            }
            await db.commit()

    asyncio.run(restore_legacy_missing_budget())
    _cold(session_id)
    ready = client.post(f'/api/sessions/{session_id}/guide/skip-all').json()['ready_brief']
    if unlimited:
        assert ready['budget'] is None
    else:
        assert ready['budget']['amount'] == {'amount': '1200', 'currency': 'USD'}
