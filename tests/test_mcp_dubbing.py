import asyncio
import json

import pytest
from fastapi import FastAPI, Request, HTTPException

import mcp_server


def call(server, name, **arguments):
    reply = asyncio.run(server.call_tool(name, arguments))
    blocks = reply[0] if isinstance(reply, tuple) else reply
    return json.loads(blocks[0].text)


@pytest.fixture
def dubbing_tools(monkeypatch):
    backend = FastAPI()
    requests = []

    @backend.post('/dub/generate/source-1')
    async def generate(request: Request):
        requests.append(await request.json())
        return {'task_id': 'dub_source-1_42'}

    @backend.get('/jobs/dub_source-1_42')
    async def status():
        return {'id': 'dub_source-1_42', 'status': 'done', 'project_id': 'source-1'}

    @backend.get('/jobs/foreign-task')
    async def forbidden():
        raise HTTPException(status_code=403, detail='This task is not available to this caller.')

    monkeypatch.delenv('OMNIVOICE_API_URL', raising=False)
    return mcp_server.create_mcp_server(app=backend), requests


def test_mcp_dubbing_passes_each_speakers_real_policy_and_resume_ids(dubbing_tools):
    server, requests = dubbing_tools
    result = call(server, 'generate_dub', job_id='source-1', language_code='es',
        segment_ids=['alice-1', 'bob-1'], regen_only=['alice-1'], segments=[
            {'start': 0, 'end': 3, 'text': 'Hola', 'profile_id': 'auto:alice', 'speaker_similarity': 'consistent'},
            {'start': 3, 'end': 6, 'text': 'Buenos días', 'profile_id': 'auto:bob', 'speaker_similarity': 'per_line'},
        ])
    assert result == {'task_id': 'dub_source-1_42'}
    assert requests[0]['segment_ids'] == ['alice-1', 'bob-1']
    assert requests[0]['regen_only'] == ['alice-1']
    assert [(s['profile_id'], s['speaker_similarity']) for s in requests[0]['segments']] == [
        ('auto:alice', 'consistent'), ('auto:bob', 'per_line')]
    assert requests[0]['timing_strategy'] == 'smart_fit'


def test_mcp_dubbing_rejects_a_fake_similarity_percentage_before_submission(dubbing_tools):
    server, requests = dubbing_tools
    result = call(server, 'generate_dub', job_id='source-1', language_code='es',
        segments=[{'start': 0, 'end': 3, 'text': 'Hola', 'speaker_similarity': 85}])
    assert requests == []
    assert 'speaker_similarity' in result['error']


def test_mcp_dubbing_status_reads_persisted_completion(dubbing_tools):
    server, requests = dubbing_tools
    assert call(server, 'get_dubbing_task', task_id='dub_source-1_42') == {
        'id': 'dub_source-1_42', 'status': 'done', 'project_id': 'source-1'}
    assert requests == []


def test_mcp_dubbing_does_not_retry_a_denied_task(dubbing_tools):
    server, requests = dubbing_tools
    result = call(server, 'get_dubbing_task', task_id='foreign-task')
    assert 'not available to this caller' in result['error']
    assert requests == []


@pytest.mark.parametrize('task_id', ['..', '../profiles', 'a/b', 'a?b', '', 'x' * 161])
def test_mcp_dubbing_refuses_ids_that_can_change_the_api_route(dubbing_tools, task_id):
    server, requests = dubbing_tools
    result = call(server, 'get_dubbing_task', task_id=task_id)
    assert 'Use the task_id' in result['error']
    assert requests == []
