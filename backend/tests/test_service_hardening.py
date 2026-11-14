"""Service boundary regressions; no external APIs or real patient data."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

import auth
import db
import records


def test_optional_torch_missing_still_supports_demo():
    code = '''
import builtins, io
original = builtins.__import__
def without_torch(name, *args, **kwargs):
    if name.split('.')[0] in ('torch', 'torchvision'):
        raise ImportError('optional dependency absent')
    return original(name, *args, **kwargs)
builtins.__import__ = without_torch
import fundus
from PIL import Image
assert fundus.analyzer.is_demo
b = io.BytesIO()
Image.new('RGB', (64, 64), (120, 40, 40)).save(b, format='PNG')
a = fundus.analyzer.analyze(b.getvalue())
assert len(a['probabilities']) == 5
assert abs(sum(a['probabilities']) - 1) < 1e-6
assert a == fundus.analyzer.analyze(b.getvalue())
assert fundus.analyzer.make_heatmap(b.getvalue(), a['level'])
'''
    result = subprocess.run([sys.executable, '-c', code],
                            cwd=Path(__file__).resolve().parents[1],
                            capture_output=True, text=True, encoding='utf-8', timeout=30,
                            env={**os.environ, 'PYTHONIOENCODING': 'utf-8'})
    assert result.returncode == 0, result.stderr
    assert not result.stdout.strip(), "模型初始化日志不能污染 MCP stdio 的 JSON-RPC 通道"


def test_record_write_masks_generated_personal_details():
    user = 'private_record_probe'
    assert records.save(user, {'kind': 'symptom', 'echo': '手机号13900000000，邮箱demo@example.com'})
    row = records.recent(user)[0]
    assert '13900000000' not in row['summary']
    assert 'demo@example.com' not in row['summary']
    assert '[手机号]' in row['summary']


def test_usage_only_includes_authenticated_user(client, token):
    username = auth.decode_token(token)['sub']
    with db.get_conn() as conn:
        conn.executemany(
            'INSERT INTO llm_usage (model,prompt_tokens,completion_tokens,total_tokens,created_at,username) VALUES (?,?,?,?,?,?)',
            [('test', 10, 20, 30, db.now(), username),
             ('test', 1000, 2000, 3000, db.now(), 'different_user')])
    result = client.get('/api/usage', headers={'Authorization': f'Bearer {token}'}).json()
    assert result['calls'] == 1
    assert result['total_tokens'] == 30


def test_streamed_agent_has_rate_limit(client, token, monkeypatch):
    import agent2
    import llm
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    monkeypatch.setattr(agent2, 'stream', lambda *a: iter(['event: final\ndata: {}\n\n']))
    headers = {'Authorization': f'Bearer {token}'}
    first = client.post('/api/agent/chat/stream', data={'text': '头晕'}, headers=headers)
    second = client.post('/api/agent/chat/stream', data={'text': '头晕'}, headers=headers)
    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers.get('Retry-After')


def test_streamed_agent_rejects_unbounded_text(client, token, monkeypatch):
    import agent2
    import llm
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    monkeypatch.setattr(agent2, 'stream', lambda *a: iter(['event: final\ndata: {}\n\n']))
    result = client.post('/api/agent/chat/stream', data={'text': '字' * 20001},
                         headers={'Authorization': f'Bearer {token}'})
    assert result.status_code == 400


def test_heatmap_failure_preserves_analysis_without_fake_map(client, token, monkeypatch):
    import io

    from PIL import Image

    import screening
    class Analyzer:
        is_demo = False
        def analyze(self, data):
            return {'probabilities': [0.8, 0.1, 0.05, 0.03, 0.02], 'level': 0}
        def make_heatmap(self, *args):
            raise RuntimeError('CAM unavailable')
    monkeypatch.setattr(screening, 'analyzer', Analyzer())
    buf = io.BytesIO()
    Image.new('RGB', (64, 64), (120, 40, 40)).save(buf, format='PNG')
    result = client.post('/api/fundus/analyze',
                         files={'file': ('fundus.png', buf.getvalue(), 'image/png')},
                         headers={'Authorization': f'Bearer {token}'})
    assert result.status_code == 200
    assert result.json()['heatmap'] == ''
    assert result.json()['heatmap_status'] == 'unavailable'
    assert result.json()['level'] == 0


def test_real_heatmap_error_never_falls_back_to_synthetic(monkeypatch):
    import threading

    import fundus
    a = fundus.FundusAnalyzer.__new__(fundus.FundusAnalyzer)
    a.model, a._model_lock, a._grad = object(), threading.RLock(), {'old': 'data'}
    seen = []
    def broken(data, level):
        seen.append(level)
        a._grad['acts'] = 'temporary'
        raise ValueError('CAM failed')
    monkeypatch.setattr(a, '_gradcam_layers', broken)
    import pytest
    with pytest.raises(RuntimeError):
        a.make_heatmap(b'image', 3)
    assert seen == [3] and a._grad == {}


@pytest.mark.parametrize('spec', ['2.0', '2.4'])
def test_http_disconnect_closes_exact_agent_generator(monkeypatch, spec):
    import asyncio

    from starlette.requests import ClientDisconnect

    import agent2
    import llm
    from api.routes import assistant
    monkeypatch.setattr(llm, 'llm_available', lambda: True)
    closed = []
    def source(*args):
        try:
            yield 'event: token\ndata: {"text":"部分"}\n\n'
            yield 'event: final\ndata: {}\n\n'
        finally:
            closed.append(True)
    monkeypatch.setattr(agent2, 'stream', source)
    async def run():
        response = await assistant.agent_chat_stream('症状', None, 'disconnect_' + spec)
        sent = asyncio.Event()
        async def receive():
            await sent.wait()
            return {'type': 'http.disconnect'}
        async def send(message):
            if message['type'] == 'http.response.body':
                sent.set()
                if spec == '2.4':
                    raise OSError('peer disconnected')
                await asyncio.sleep(0)
        try:
            await response({'type': 'http', 'asgi': {'spec_version': spec}}, receive, send)
        except ClientDisconnect:
            pass
        assert closed == [True]
    asyncio.run(run())

