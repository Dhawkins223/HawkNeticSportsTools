from __future__ import annotations

from dataclasses import replace
import re

from app import database
from app.repositories import CanonicalRepository, RawBallDontLieRepository
from app.services.balldontlie import BallDontLieProviderError, BallDontLieSyncResult


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


def test_public_pages_render(client):
    for path in ['/', '/pricing', '/contact', '/refund-policy', '/cancellation-policy', '/terms', '/privacy']:
        response = client.get(path)
        assert response.status_code == 200


def test_postgres_schema_excludes_sqlite_only_pragmas(monkeypatch):
    postgres_settings = replace(database.settings, database_url='postgresql://example/test')
    monkeypatch.setattr(database, 'settings', postgres_settings)

    schema = database._schema_sql()

    assert 'PRAGMA' not in schema
    assert 'AUTOINCREMENT' not in schema
    assert 'SERIAL PRIMARY KEY' in schema
    assert 'password_reset_tokens' in schema
    assert 'created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP' in schema
    assert 'expires_at TIMESTAMPTZ NOT NULL' in schema


def test_footer_contains_legal_and_support_links(client):
    response = client.get('/')
    assert response.status_code == 200
    for link in ['href="/pricing"', 'href="/contact"', 'href="/refund-policy"', 'href="/cancellation-policy"', 'href="/terms"', 'href="/privacy"']:
        assert link in response.text
    assert 'HawkNetic@gmail.com' in response.text
    assert 'DavidHawkins@Hawknetic.com' in response.text


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


def test_seeded_free_account_can_login(client):
    response = client.post(
        '/login',
        data={'email': 'free@hawknetic.local', 'password': 'free-access'},
        follow_redirects=False,
    )
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


def test_balldontlie_provider_errors_return_json_detail(monkeypatch, client):
    class StubClient:
        async def get_teams(self):
            raise BallDontLieProviderError('provider unavailable', status_code=502)

    monkeypatch.setattr('app.services.balldontlie.BallDontLieService.client', lambda: StubClient())
    response = client.get('/api/providers/balldontlie/teams')
    assert response.status_code == 502
    assert response.json()['detail'] == 'provider unavailable'


def test_dashboard_sync_action_populates_canonical_teams(monkeypatch, client):
    async def fake_sync_teams(user_id=None):
        RawBallDontLieRepository.upsert_teams([
            {
                'id': 1,
                'conference': 'East',
                'division': 'Southeast',
                'city': 'Atlanta',
                'name': 'Hawks',
                'full_name': 'Atlanta Hawks',
                'abbreviation': 'ATL',
            }
        ])
        canonical_written = CanonicalRepository.normalize_teams_from_raw()
        return BallDontLieSyncResult(resource='teams', raw_records_written=1, canonical_records_written=canonical_written, source_count=1)

    monkeypatch.setattr('app.services.balldontlie.BallDontLieService.sync_teams', fake_sync_teams)
    register(client, email='sync@example.com')
    response = client.post('/dashboard/sync', data={'sync_type': 'teams'}, follow_redirects=False)
    assert response.status_code == 303

    teams = client.get('/teams')
    assert teams.status_code == 200
    assert 'Atlanta Hawks' in teams.text


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


def test_platform_routes_require_login(client):
    for path in ['/games','/teams','/players','/edges','/upgrade']:
        r=client.get(path, follow_redirects=False)
        assert r.status_code==303


def test_free_user_can_access_shell_and_sees_upgrade_locks(client):
    client.post('/login', data={'email':'free@hawknetic.local','password':'free-access'}, follow_redirects=False)
    for path in ['/dashboard','/games','/teams','/players','/edges','/upgrade','/account']:
        r=client.get(path)
        assert r.status_code==200
    edges=client.get('/edges')
    assert 'Upgrade to Unlock' in edges.text


def test_logged_in_nav_has_platform_sections(client):
    register(client, email='nav@example.com')
    page=client.get('/dashboard')
    for label in ['Dashboard','Games','Teams','Players','Edges','Account','Upgrade']:
        assert label in page.text


def test_password_reset_flow_updates_stored_account(client):
    register(client, email='recover@example.com')
    client.post('/logout', follow_redirects=False)

    requested = client.post('/forgot-password', data={'email': 'recover@example.com'})
    assert requested.status_code == 200
    match = re.search(r'token=([^"<]+)', requested.text)
    assert match, requested.text
    token = match.group(1)

    reset_page = client.get(f'/reset-password?token={token}')
    assert reset_page.status_code == 200
    assert 'recover@example.com' in reset_page.text

    reset = client.post(
        '/reset-password',
        data={'token': token, 'password': 'new-strong-password', 'confirm_password': 'new-strong-password'},
        follow_redirects=False,
    )
    assert reset.status_code == 303

    old_login = client.post('/login', data={'email': 'recover@example.com', 'password': 'strong-password'}, follow_redirects=False)
    assert old_login.status_code == 200
    assert 'Invalid credentials' in old_login.text

    new_login = client.post('/login', data={'email': 'recover@example.com', 'password': 'new-strong-password'}, follow_redirects=False)
    assert new_login.status_code == 303


def test_unknown_recovery_email_does_not_expose_token(client):
    response = client.post('/forgot-password', data={'email': 'missing@example.com'})
    assert response.status_code == 200
    assert 'If that email is in HawkNetic' in response.text
    assert 'token=' not in response.text


def test_login_remember_me_sets_persistent_cookie(client):
    response = client.post(
        '/login',
        data={'email': 'free@hawknetic.local', 'password': 'free-access', 'remember_me': '1'},
        follow_redirects=False,
    )
    assert response.status_code == 303
    set_cookie = response.headers.get('set-cookie', '')
    assert 'hawknetic_session=' in set_cookie
    assert 'Max-Age=2592000' in set_cookie


def test_dashboard_surfaces_backend_platform_data(client):
    client.post('/login', data={'email': 'free@hawknetic.local', 'password': 'free-access'}, follow_redirects=False)
    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    for label in ['Data pipeline', 'Latest provider runs', 'Recent teams', 'Recent players']:
        assert label in dashboard.text


def test_seeded_beta_master_account_has_full_access(client):
    response = client.post(
        '/login',
        data={'email': 'beta.master@hawknetic.local', 'password': 'HawkNeticBeta!2026'},
        follow_redirects=False,
    )
    assert response.status_code == 303

    dashboard = client.get('/dashboard')
    assert dashboard.status_code == 200
    assert 'Welcome back' in dashboard.text

    edges = client.get('/edges')
    assert edges.status_code == 200
    assert 'Market Edge Scanner' in edges.text
    assert 'Upgrade to Unlock' not in edges.text


def test_plan_seed_preserves_existing_subscription_links(client):
    from app.database import init_db

    register(client, email='persisted-plan@example.com')
    checkout = client.post('/checkout/pro', follow_redirects=False)
    assert checkout.status_code == 303

    init_db()

    account = client.get('/account')
    assert account.status_code == 200
    assert 'Pro' in account.text
    assert 'is active' in account.text
