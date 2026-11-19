import httpx
import pytest
from app.keitaro import KeitaroClient
from app.errors import AppError


def mock_http(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    client = KeitaroClient()
    client.url, client.key = 'https://tracker.test', 'test-secret'
    return client


async def test_offer_update_only_changes_offers(monkeypatch):
    import json
    def handler(request):
        assert request.method == 'PUT'
        assert str(request.url) == 'https://tracker.test/admin_api/v1/streams/42'
        assert request.headers['Api-Key'] == 'test-secret'
        body = json.loads(request.content)
        assert set(body) == {'offers'}
        return httpx.Response(200, json={'id':42, **body})
    client = mock_http(monkeypatch, handler)
    assert (await client.update_offers(42, [{'offer_id':7, 'share':100, 'state':'active'}]))['id'] == 42


async def test_campaign_pagination_and_group_type(monkeypatch):
    offsets = []
    def handler(request):
        if request.url.path.endswith('/groups'):
            assert request.url.params['type'] == 'campaigns'
            return httpx.Response(200, json=[{'id':1, 'name':'Group'}])
        offset = int(request.url.params['offset'])
        offsets.append(offset)
        return httpx.Response(200, json=[{'id':x} for x in range(offset, min(offset + 200, 203))])
    client = mock_http(monkeypatch, handler)
    assert len(await client.campaigns()) == 203
    assert offsets == [0,200]
    assert len(await client.items('/groups', type='campaigns')) == 1


async def test_wrong_response_and_secret_redaction(monkeypatch):
    client = mock_http(monkeypatch, lambda request: httpx.Response(401, text='secret=test-secret'))
    with pytest.raises(AppError) as error:
        await client.campaign(42)
    assert error.value.code == 'KEITARO_ERROR' and 'test-secret' not in str(error.value)


async def test_post_timeout_not_retried(monkeypatch):
    calls = []
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('Timeout', request=request)
    client = mock_http(monkeypatch, handler)
    with pytest.raises(AppError) as error:
        await client.create_campaign({'name':'Test','alias':'test'})
    assert error.value.status == 504 and len(calls) == 1


async def test_repeated_campaign_pages_rejected(monkeypatch):
    client = mock_http(monkeypatch, lambda request: httpx.Response(200, json=[{'id':x} for x in range(200)]))
    with pytest.raises(AppError) as error:
        await client.campaigns()
    assert error.value.code == 'KEITARO_PAGINATION'
