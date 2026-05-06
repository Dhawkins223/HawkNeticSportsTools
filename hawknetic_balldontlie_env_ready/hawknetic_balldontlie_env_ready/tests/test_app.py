from __future__ import annotations

from app.repositories import CanonicalRepository, RawBallDontLieRepository
from app.services.balldontlie import BallDontLieSyncResult



def register(client, email: str = 'user@example.com'):
    return client.post(
        '/register',
        data={
            'full_name': 'Test User',
            'email': email,
            'password': 'strong-password',
            'company': 'HawkNetic Labs',
        },
        follow_redirects=False,
    )



def test_landing_page_renders(client):
    response = client.get('/')
    assert response.status_code == 200
    assert 'HawkNetic' in response.text



def test_lead_capture_api(client):
    response = client.post('/api/leads', json={'email': 'lead@example.com', 'source_page': '/', 'consent_marketing': True})
    assert response.status_code == 200
    assert response.json()['ok'] is True



def test_register_login_and_dashboard(client):
    response = register(client)
    assert response.status_code == 303
    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    assert 'Welcome back' in dashboard.text



def test_checkout_and_cancel_subscription(client):
    register(client)
    checkout = client.post('/checkout/pro', follow_redirects=False)
    assert checkout.status_code == 303
    account = client.get('/account?billing=active')
    assert 'Plan activated' in account.text
    cancel = client.post('/account/cancel', follow_redirects=False)
    assert cancel.status_code == 303
    canceled = client.get('/account?canceled=1')
    assert 'Subscription canceled' in canceled.text



def test_ai_chat_requires_opt_in_then_returns_answer(client):
    register(client)
    blocked = client.post('/api/ai/chat', json={'prompt': 'Explain this finding'})
    assert blocked.status_code == 403
    client.post('/account/ai-opt-in', data={'enabled': 'true'}, follow_redirects=False)
    allowed = client.post('/api/ai/chat', json={'prompt': 'Explain this finding'})
    assert allowed.status_code == 200
    assert allowed.json()['ok'] is True
    assert allowed.json()['content']



def test_balldontlie_health_endpoint(client):
    response = client.get('/api/providers/balldontlie/health')
    assert response.status_code == 200
    payload = response.json()
    assert payload['provider'] == 'balldontlie'
    assert 'configured' in payload



def test_balldontlie_teams_endpoint_uses_service(monkeypatch, client):
    class StubClient:
        async def get_teams(self):
            return {'data': [{'id': 1, 'full_name': 'Atlanta Hawks', 'abbreviation': 'ATL'}]}

    monkeypatch.setattr('app.services.balldontlie.BallDontLieService.client', lambda: StubClient())
    response = client.get('/api/providers/balldontlie/teams')
    assert response.status_code == 200
    assert response.json()['data'][0]['full_name'] == 'Atlanta Hawks'



def test_balldontlie_sync_games_persists_raw_and_canonical_rows(monkeypatch, client):
    async def fake_sync_games(date_str: str, user_id=None):
        RawBallDontLieRepository.upsert_teams([
            {
                'id': 6,
                'conference': 'East',
                'division': 'Central',
                'city': 'Cleveland',
                'name': 'Cavaliers',
                'full_name': 'Cleveland Cavaliers',
                'abbreviation': 'CLE',
            },
            {
                'id': 4,
                'conference': 'East',
                'division': 'Southeast',
                'city': 'Charlotte',
                'name': 'Hornets',
                'full_name': 'Charlotte Hornets',
                'abbreviation': 'CHA',
            },
        ])
        CanonicalRepository.normalize_teams_from_raw()
        RawBallDontLieRepository.upsert_games([
            {
                'id': 15907925,
                'date': date_str,
                'season': 2024,
                'status': 'Final',
                'period': 4,
                'time': 'Final',
                'postseason': False,
                'postponed': False,
                'home_team_score': 115,
                'visitor_team_score': 105,
                'home_team_id': 6,
                'visitor_team_id': 4,
                'datetime': '2025-01-05T23:00:00.000Z',
            }
        ])
        canonical_written = CanonicalRepository.normalize_games_from_raw()
        return BallDontLieSyncResult(resource='games', raw_records_written=1, canonical_records_written=canonical_written, source_count=1)

    monkeypatch.setattr('app.services.balldontlie.BallDontLieService.sync_games', fake_sync_games)
    response = client.post('/api/providers/balldontlie/sync/games?date=2026-01-27')
    assert response.status_code == 200
    payload = response.json()
    assert payload['raw_records_written'] == 1
    assert payload['canonical_records_written'] == 1

    summary = client.get('/api/providers/balldontlie/storage-summary')
    assert summary.status_code == 200
    summary_payload = summary.json()
    assert summary_payload['raw']['games'] >= 1
    assert summary_payload['canonical']['games'] >= 1
