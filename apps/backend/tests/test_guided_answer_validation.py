import pytest
from fastapi.testclient import TestClient

import test_guided_intake_api as fixtures


guided_api_client = fixtures.guided_api_client


@pytest.mark.parametrize(
    ('query', 'question_id', 'answer'),
    [
        ('Need a monitor', 'monitor-connection', {'answer_type': 'choice', 'choice_id': 'not-offered'}),
        ('Need a monitor', 'monitor-connection', {'answer_type': 'natural_language', 'text': 'Yes and https://shop.example/invalid'}),
        ('Need a monitor', 'monitor-connection', {'answer_type': 'choice_with_text', 'text': 'Yes'}),
        ('Need a laptop', 'budget', {'answer_type': 'yes_no', 'value': True}),
        ('Need a laptop', 'budget', {'answer_type': 'choice', 'choice_id': 'yes'}),
        ('Need a laptop', 'budget', {'answer_type': 'choice_with_text', 'text': '$1200'}),
        ('Between two laptops', 'comparison-priority', {'answer_type': 'yes_no', 'value': True}),
        ('Between two laptops', 'comparison-priority', {'answer_type': 'choice', 'choice_id': 'not-offered'}),
        ('Between two laptops', 'comparison-priority', {'answer_type': 'choice_with_text', 'choice_id': 'not-offered', 'text': 'Battery'}),
    ],
)
def test_answer_rejection_preserves_guide_brief_and_candidates(
    guided_api_client: TestClient, query: str, question_id: str, answer: dict
) -> None:
    client = guided_api_client
    session_id = fixtures._create_guided_session(client, query)['session_id']
    before_guide = client.get(f'/api/sessions/{session_id}/guide').json()
    before_session = client.get(f'/api/sessions/{session_id}').json()
    response = client.post(f'/api/sessions/{session_id}/answers', json={
        'question_id': question_id, 'answer': answer,
    })
    assert response.status_code == 422
    error = response.json()['error']
    assert error['code'] == 'guided_answer_not_supported'
    assert error['details'] == {'question_id': question_id}
    assert error['request_id']
    assert client.get(f'/api/sessions/{session_id}/guide').json() == before_guide
    assert client.get(f'/api/sessions/{session_id}').json() == before_session


@pytest.mark.parametrize('answer', [
    {'answer_type': 'choice', 'choice_id': 'everyday-use'},
    {'answer_type': 'choice', 'choice_id': 'best-value'},
    {'answer_type': 'choice_with_text', 'choice_id': 'something-else', 'text': 'Battery life'},
    {'answer_type': 'choice_with_text', 'choice_id': None, 'text': 'Battery life'},
    {'answer_type': 'choice_with_text', 'choice_id': 'best-value', 'text': 'Battery life'},
    {'answer_type': 'natural_language', 'text': 'Battery life'},
])
def test_offered_choices_and_available_custom_text_advance(
    guided_api_client: TestClient, answer: dict,
) -> None:
    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Between two laptops')['session_id']
    response = client.post(f'/api/sessions/{session_id}/answers', json={
        'question_id': 'comparison-priority', 'answer': answer,
    })
    assert response.status_code == 200
    assert response.json()['current_question']['question_id'] == 'budget'


@pytest.mark.parametrize('answer', [
    {'answer_type': 'yes_no', 'value': True},
    {'answer_type': 'yes_no', 'value': False},
    {'answer_type': 'choice', 'choice_id': 'yes'},
    {'answer_type': 'choice', 'choice_id': 'no'},
])
def test_offered_yes_no_forms_advance(guided_api_client: TestClient, answer: dict) -> None:
    client = guided_api_client
    session_id = fixtures._create_guided_session(client, 'Need a monitor')['session_id']
    response = client.post(f'/api/sessions/{session_id}/answers', json={
        'question_id': 'monitor-connection', 'answer': answer,
    })
    assert response.status_code == 200
    assert response.json()['current_question']['question_id'] == 'budget'
