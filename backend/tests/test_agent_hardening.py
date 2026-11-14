"""Real Agent loop under deterministic, offline provider responses."""
import copy
import json

import pytest

import agent2


def call(name, ident='c1', **args):
    return {'id': ident, 'type': 'function', 'function': {
        'name': name, 'arguments': json.dumps(args, ensure_ascii=False)}}


def events(chunks):
    return [(c.split('\n')[0][7:], json.loads(c.split('\ndata: ', 1)[1])) for c in chunks]


@pytest.fixture
def offline(monkeypatch):
    monkeypatch.setattr(agent2.llm, 'llm_available', lambda: True)
    monkeypatch.setattr(agent2.llm, 'chat', lambda *a, **k: {'content': '', 'tool_calls': []})
    monkeypatch.setattr(agent2.llm, 'stream_chat', lambda *a, **k: iter(['建议到门诊咨询。']))
    monkeypatch.setattr(agent2.ai_analysis, 'analyze_symptom',
                        lambda *a, **k: {'kind': 'symptom', 'dept': '全科', 'echo': '症状描述'})
    monkeypatch.setattr(agent2.rag, 'retrieve', lambda *a, **k: [])
    monkeypatch.setattr(agent2.records, 'save', lambda *a, **k: True)
    user = 'hardening_user'
    agent2.reset(user)
    yield user
    agent2.reset(user)


def test_first_decision_receives_system_and_masked_input(offline, monkeypatch):
    seen = []
    def respond(messages, **kw):
        seen.append(copy.deepcopy(messages))
        return {'content': '', 'tool_calls': []}
    monkeypatch.setattr(agent2.llm, 'chat', respond)
    list(agent2.stream(offline, '头晕，电话13900000000', None, 'image/jpeg'))
    assert seen[0][0] == {'role': 'system', 'content': agent2.system_prompt()}
    assert '13900000000' not in json.dumps(seen, ensure_ascii=False)
    assert '[手机号]' in json.dumps(seen, ensure_ascii=False)


@pytest.mark.parametrize('skip', [False, True])
def test_mixed_ask_batch_answers_every_tool_call(offline, monkeypatch, skip):
    seen = []
    batch = [call('ask_user', 'ask1', question='持续多久？', chips=['一天']),
             call('get_history', 'history1')]
    def respond(messages, **kw):
        seen.append(copy.deepcopy(messages))
        return {'content': '', 'tool_calls': batch if len(seen) == 1 else []}
    monkeypatch.setattr(agent2.llm, 'chat', respond)
    chunks = list(agent2.stream(offline, '头晕' + ('，跳过直接分析' if skip else ''), None, 'image/jpeg'))
    history = agent2.SESSIONS[offline]['messages']
    answered = [m['tool_call_id'] for m in history if m['role'] == 'tool']
    assert sorted(answered) == ['ask1', 'history1']
    assert sum(e == 'ask' for e, d in events(chunks)) == (0 if skip else 1)


def test_tool_start_arrives_before_tool_execution(offline, monkeypatch):
    executed = []
    monkeypatch.setattr(agent2.llm, 'chat', lambda *a, **k: {'tool_calls': [call('get_history')]})
    def execute(*a):
        executed.append(True)
        return {'name': 'get_history', 'result': '暂无历史', 'warn': False}
    monkeypatch.setattr(agent2, '_exec_tool', execute)
    stream = agent2.stream(offline, '头晕', None, 'image/jpeg')
    try:
        while True:
            ev, data = events([next(stream)])[0]
            if ev == 'tool_start':
                assert executed == []
                break
    finally:
        stream.close()


def test_unknown_tool_never_falls_through_to_risk_scoring():
    state = agent2._new()
    with pytest.raises(ValueError):
        agent2._exec_tool(call('invented_tool'), state, 'test')
    assert state['risk'] is None


def test_tool_failure_returns_observation_then_finishes(offline, monkeypatch):
    seen = []
    def respond(messages, **kw):
        seen.append(copy.deepcopy(messages))
        return {'tool_calls': [call('get_history')] if len(seen) == 1 else []}
    def broken(*a):
        raise OSError('temporary storage failure')
    monkeypatch.setattr(agent2.llm, 'chat', respond)
    monkeypatch.setattr(agent2, '_exec_tool', broken)
    result = events(list(agent2.stream(offline, '头晕', None, 'image/jpeg')))
    assert any(e == 'tool_result' and d.get('warn') for e, d in result)
    assert any(e == 'final' for e, d in result)
    assert any(m.get('tool_call_id') == 'c1' for m in seen[1])


def test_reset_cancels_already_running_state(offline):
    state = agent2._new()
    agent2.SESSIONS[offline] = state
    agent2.reset(offline)
    assert state['cancelled'] is True


def test_cancelled_session_can_start_again(offline):
    state = agent2._new()
    state['cancelled'] = True
    agent2.SESSIONS[offline] = state
    result = events(list(agent2.stream(offline, '新的问题', None, 'image/jpeg')))
    assert any(e == 'final' for e, d in result)
    assert agent2.SESSIONS[offline] is not state


def test_partial_final_stream_is_reported_as_error(offline, monkeypatch):
    def broken(*a, **kw):
        yield '已完成一部分。'
        raise OSError('connection lost')
    monkeypatch.setattr(agent2.llm, 'stream_chat', broken)
    result = events(list(agent2.stream(offline, '头晕', None, 'image/jpeg')))
    assert any(e == 'error' for e, d in result)
    assert not any(e == 'final' for e, d in result)


def test_navigation_request_does_not_invent_symptom_analysis(offline, monkeypatch):
    state = agent2._new()
    state['hospital'] = {'dept': '眼科', 'result': '示例医院，无距离信息'}
    state['messages'].append({'role': 'user', 'content': '去哪里挂眼科'})
    def forbidden(*a, **kw):
        pytest.fail('navigation must not call symptom diagnosis')
    monkeypatch.setattr(agent2.ai_analysis, 'analyze_symptom', forbidden)
    list(agent2._stream_final(state, offline))


def test_navigation_with_symptoms_still_runs_symptom_analysis(offline, monkeypatch):
    state = agent2._new()
    state['hospital'] = {'dept': '眼科', 'result': '示例医院'}
    state['messages'].append({'role': 'user', 'content': '突然视力下降，附近哪里能看'})
    seen = []
    def analyze(text, user):
        seen.append(text)
        return {'kind': 'symptom', 'dept': '眼科'}
    monkeypatch.setattr(agent2.ai_analysis, 'analyze_symptom', analyze)
    list(agent2._stream_final(state, offline))
    assert seen == ['突然视力下降，附近哪里能看']


def test_retrieval_query_preserves_negated_symptoms():
    state = agent2._new()
    state['messages'].append({'role': 'user', 'content': '没有胸痛，只有干咳'})
    assert '没有胸痛' in agent2._retrieval_query(state)


@pytest.mark.parametrize('text', ['1', '你好', 'hello', '谢谢'])
def test_smalltalk_does_not_generate_a_medical_report(offline, monkeypatch, text):
    def forbidden(*a, **kw):
        pytest.fail('smalltalk must not run medical analysis or model decisions')
    monkeypatch.setattr(agent2.llm, 'chat', forbidden)
    monkeypatch.setattr(agent2.ai_analysis, 'analyze_symptom', forbidden)
    result = events(list(agent2.stream(offline, text, None, 'image/jpeg')))
    assert [event for event, _ in result] == ['final']
    assert result[0][1]['kind'] == 'chat'
    assert not result[0][1].get('data')


def test_decision_content_is_not_rendered_as_reasoning(offline, monkeypatch):
    monkeypatch.setattr(agent2.llm, 'chat', lambda *a, **kw: {'content': '**面向用户的回答**'})
    result = events(list(agent2.stream(offline, '头晕三天', None, 'image/jpeg')))
    assert not any('面向用户的回答' in data.get('text', '') for event, data in result if event == 'thought')


def test_active_stream_cannot_be_overwritten_and_reset_is_identity_safe(offline, monkeypatch):
    monkeypatch.setattr(agent2.llm, 'chat', lambda *a, **k: {'tool_calls': [call('get_history')]})
    first = agent2.stream(offline, '头晕', b'image', 'image/jpeg')
    next(first)
    old = agent2.SESSIONS[offline]
    blocked = events(list(agent2.stream(offline, '另一条请求', None, 'image/jpeg')))
    assert blocked[0][0] == 'error'
    assert agent2.SESSIONS[offline] is old
    agent2.reset(offline)
    second = agent2.stream(offline, '重置后的问题', None, 'image/jpeg')
    next(second)
    current = agent2.SESSIONS[offline]
    first.close()
    assert old['cancelled'] and old['image'] is None
    assert not current['cancelled']
    assert events(list(agent2.stream(offline, '不能覆盖', None, 'image/jpeg')))[0][0] == 'error'
    second.close()
    assert current['cancelled']


def test_rag_tool_passes_medical_evidence_to_final_model(offline, monkeypatch):
    hit = {'entry': {'category': '测试类目', 'dept': '全科', 'urgency': 'green',
                    'diseases': [{'name': '测试方向', 'feature': '独特特征哨兵'}],
                    'tests': ['独特检查哨兵'], 'reds': ['独特红旗哨兵']},
           'matched': ['测试'], 'score': 1}
    monkeypatch.setattr(agent2.rag, 'retrieve', lambda *a, **k: [hit])
    state = agent2._new()
    state['analysis'] = {'kind': 'symptom', 'dept': '全科'}
    result = agent2.agent._run_tool(state, offline, 'search_kb', {'query': '测试'})
    captured = []
    def final(messages, **kw):
        captured.append(copy.deepcopy(messages))
        yield '结论'
    monkeypatch.setattr(agent2.llm, 'stream_chat', final)
    list(agent2._stream_final(state, offline))
    for sentinel in ('独特特征哨兵', '独特检查哨兵', '独特红旗哨兵'):
        assert sentinel in result['result']
        assert sentinel in captured[0][-1]['content']
    json.dumps(agent2._final_data(state), ensure_ascii=False)

