from uuid import uuid4
import pytest
from app import keitaro


def current(client):
    return client.get('/api/v1/campaigns').json()[0]


def stream(client):
    return next(x for x in current(client)['streams'] if x['editable'])


def edit(client, s, suffix, body=None, method='POST', status=200):
    r = client.request(method, f"/api/v1/streams/{s['id']}{suffix}", json={"expected_revision": s['revision'], **(body or {})})
    assert r.status_code == status, r.text
    return r.json()


def push(client, s, key=None):
    r = client.post(f"/api/v1/streams/{s['id']}/push", json={"expected_revision": s['revision']}, headers={"Idempotency-Key": key or str(uuid4())})
    assert r.status_code == 202, r.text
    return r.json()


def test_add_is_draft_persists_cancel_and_revisions(client):
    s = stream(client)
    assert len(s['offers']) == 3
    changed = edit(client, s, '/offers', {'offer_id': 11112})
    assert changed['dirty'] and [x['share'] for x in changed['offers']] == [25]*4
    remote = client.get('/api/v1/demo/remote/93212').json()[1]
    assert len(remote['offers']) == 3
    assert len(stream(client)['offers']) == 4
    edit(client, s, '/cancel', status=409)
    r = client.post(f"/api/v1/campaigns/{current(client)['id']}/fetch")
    assert r.status_code == 409
    cancelled = edit(client, changed, '/cancel')
    assert len(cancelled['offers']) == 3 and not cancelled['dirty']


def test_archive_restore_and_pin_distribution(client):
    s = stream(client)
    s = edit(client, s, f"/offers/{s['offers'][0]['id']}", {'pinned': True, 'share': 25}, 'PATCH')
    assert [x['share'] for x in s['offers']] == [25,38,37]
    assert push(client, s)['status'] == 'succeeded'
    s = stream(client)
    oid = s['offers'][1]['id']
    s = edit(client, s, f'/offers/{oid}/remove')
    assert [x['share'] for x in s['offers']] == [25,0,75]
    assert push(client, s)['status'] == 'succeeded'
    s = stream(client)
    assert not s['dirty'] and not s['offers'][1]['active']
    remote = client.get('/api/v1/demo/remote/93212').json()[1]
    assert len(remote['offers']) == 2
    s = edit(client, s, f'/offers/{oid}/restore')
    assert [x['share'] for x in s['offers']] == [25,38,37]
    assert push(client, s)['status'] == 'succeeded'


def test_external_deletion_archived_and_cancel_restores_pin(client):
    s = stream(client)
    s = edit(client, s, f"/offers/{s['offers'][0]['id']}", {'pinned': True}, 'PATCH')
    push(client, s)
    s = stream(client)
    original = s['offers'][0]
    removed = edit(client, s, f"/offers/{original['id']}/remove")
    assert not removed['offers'][0]['pinned']
    restored = edit(client, removed, '/cancel')
    assert restored['offers'][0]['pinned']
    r = client.post(f"/api/v1/demo/streams/{s['remote_id']}/remove/{original['offer_id']}")
    assert r.status_code == 200
    c = current(client)
    assert client.post(f"/api/v1/campaigns/{c['id']}/fetch").status_code == 200
    s = stream(client)
    old = next(x for x in s['offers'] if x['offer_id'] == original['offer_id'])
    assert not old['active'] and old['share'] == 0 and not old['pinned'] and not s['dirty']


def test_push_conflict_does_not_overwrite_tracker(client):
    s = edit(client, stream(client), '/offers', {'offer_id': 11112})
    client.post(f"/api/v1/demo/streams/{s['remote_id']}/remove/3749")
    op = push(client, s)
    assert op['status'] == 'conflict'
    assert stream(client)['dirty']
    assert all(x['offer_id'] != 11112 for x in client.get('/api/v1/demo/remote/93212').json()[1]['offers'])


def test_invalid_commands_are_atomic(client):
    s = stream(client)
    edit(client, s, '/offers', {'offer_id': 3749}, status=409)
    s = edit(client, s, f"/offers/{s['offers'][0]['id']}", {'pinned': True, 'share': 90}, 'PATCH')
    edit(client, s, f"/offers/{s['offers'][1]['id']}", {'pinned': True, 'share': 20}, 'PATCH', status=422)
    assert stream(client)['revision'] == s['revision']
    assert sum(x['share'] for x in stream(client)['offers']) == 100
    s = edit(client, s, f"/offers/{s['offers'][1]['id']}/remove")
    edit(client, s, f"/offers/{s['offers'][2]['id']}/remove", status=422)
    assert stream(client)['revision'] == s['revision']


def test_last_offer_and_unpublished_add_remove(client):
    s = stream(client)
    s = edit(client, s, '/offers', {'offer_id': 11112})
    new = next(x for x in s['offers'] if x['offer_id'] == 11112)
    s = edit(client, s, f"/offers/{new['id']}/remove")
    assert len(s['offers']) == 3 and not s['dirty']
    s = edit(client, s, f"/offers/{s['offers'][0]['id']}/remove")
    s = edit(client, s, f"/offers/{s['offers'][1]['id']}/remove")
    remaining = next(x for x in s['offers'] if x['active'])
    edit(client, s, f"/offers/{remaining['id']}/remove", status=422)


def test_create_two_streams_and_idempotency(client):
    body = {'name': 'Australia launch', 'geo_code': 'au', 'offer_id': 4821, 'domain_id': 1, 'group_id': 1, 'traffic_source_id': 1}
    key = str(uuid4())
    r = client.post('/api/v1/campaigns', json=body, headers={'Idempotency-Key': key})
    assert r.status_code == 202, r.text
    op = r.json()
    assert op['status'] == 'succeeded', op
    repeat = client.post('/api/v1/campaigns', json=body, headers={'Idempotency-Key': key}).json()
    assert repeat['id'] == op['id'] and len(client.get('/api/v1/campaigns').json()) == 2
    remote = client.get(f"/api/v1/demo/remote/{op['data']['remote_id']}").json()
    assert len(remote) == 2 and remote[0]['filters'][0]['payload'] == ['AU']
    assert remote[0]['action_payload'] == 'https://google.com/'
    assert remote[1]['offers'] == [{'offer_id': 4821, 'share': 100, 'state': 'active'}]
    body['name'] = 'Another name'
    assert client.post('/api/v1/campaigns', json=body, headers={'Idempotency-Key': key}).status_code == 409


@pytest.mark.parametrize('field,value', [('geo_code','XX'), ('name','  '), ('offer_id',0)])
def test_invalid_creation(client, field, value):
    body = {'name': 'Test', 'geo_code': 'AU', 'offer_id': 4821, 'domain_id': 1, 'group_id': 1, 'traffic_source_id': 1, field: value}
    assert client.post('/api/v1/campaigns', json=body, headers={'Idempotency-Key': str(uuid4())}).status_code == 422
    assert len(client.get('/api/v1/campaigns').json()) == 1


def test_uncertain_push_reconciles_after_applied_write(client, monkeypatch):
    original = keitaro.DemoKeitaro.update_offers
    async def applied_then_timeout(self, remote_id, offers):
        await original(self, remote_id, offers)
        raise TimeoutError('Lost response')
    monkeypatch.setattr(keitaro.DemoKeitaro, 'update_offers', applied_then_timeout)
    s = edit(client, stream(client), '/offers', {'offer_id': 11112})
    op = push(client, s)
    assert op['status'] == 'unknown'
    assert stream(client)['busy_operation'] == op['id']
    r = client.post(f"/api/v1/operations/{op['id']}/reconcile")
    assert r.status_code == 200 and r.json()['status'] == 'succeeded', r.text
    assert not stream(client)['dirty'] and stream(client)['busy_operation'] is None


def test_cancel_and_import_errors_do_not_clear_data(client, monkeypatch):
    async def broken(self, remote_id):
        raise keitaro.AppError('UNAVAILABLE', 'Unavailable', 503)
    before = current(client)
    monkeypatch.setattr(keitaro.DemoKeitaro, 'streams', broken)
    assert client.post(f"/api/v1/campaigns/{before['id']}/fetch").status_code == 503
    after = current(client)
    assert before == after


def test_create_lost_response_recovers_by_alias_without_duplicate(client, monkeypatch):
    original = keitaro.DemoKeitaro.create_campaign
    async def created_then_timeout(self, payload):
        await original(self, payload)
        raise TimeoutError('Lost create response')
    monkeypatch.setattr(keitaro.DemoKeitaro, 'create_campaign', created_then_timeout)
    body = {'name':'Recovery test','geo_code':'MX','offer_id':4822,'domain_id':1,'group_id':1,'traffic_source_id':1}
    result = client.post('/api/v1/campaigns', json=body, headers={'Idempotency-Key':str(uuid4())}).json()
    assert result['status'] == 'unknown'
    reconciled = client.post(f"/api/v1/operations/{result['id']}/reconcile").json()
    assert reconciled['status'] == 'succeeded', reconciled
    assert len(client.get('/api/v1/campaigns').json()) == 2
    assert len(client.get(f"/api/v1/demo/remote/{reconciled['data']['remote_id']}").json()) == 2


def test_auth_and_csrf(client, monkeypatch):
    assert client.post('/api/v1/campaigns/import', json={'remote_id': 93212}, headers={'Origin':'http://127.0.0.1:5173'}).status_code == 200
    assert client.post('/api/v1/campaigns/import', json={'remote_id': 93212}, headers={'Origin':'https://evil.test'}).status_code == 403
    monkeypatch.setattr(keitaro.settings(), 'operator_password', 'test-password-1234')
    assert client.get('/api/v1/campaigns').status_code == 401
    assert client.post('/api/v1/auth/login', json={'password':'bad'}).status_code == 401
    assert client.post('/api/v1/auth/login', json={'password':'test-password-1234'}).status_code == 200
    assert client.get('/api/v1/campaigns').status_code == 200
    assert client.post('/api/v1/auth/logout').status_code == 200
    assert client.get('/api/v1/campaigns').status_code == 401
