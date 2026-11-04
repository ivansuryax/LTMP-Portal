"""Render + Neon deployment safety: code paths without external hosting."""
import os
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy.engine import URL
from app.db import User, database_url, engine_for, session_factory, setup_engine
from app.security import hash_password
from app.main import create_app


def test_require_neon_database_url(monkeypatch):
    monkeypatch.delenv('POSTGRES_PASSWORD', raising=False)
    monkeypatch.delenv('DATABASE_URL', raising=False)
    monkeypatch.setenv('REQUIRE_DATABASE_URL', 'true')
    import pytest
    with pytest.raises(RuntimeError, match='DATABASE_URL'):
        database_url()


def test_psycopg3_compatibility_for_neon_url():
    # No real network required. Verify driver is selected before SQLALchemy
    # could try to import psycopg2 (which is absent from requirements).
    from unittest.mock import patch
    with patch('app.db.create_engine') as patched:
        url='postgresql://user:pass%40word@ep-sample.neon.tech/neondb?sslmode=require'
        engine_for(url)
        target=patched.call_args.args[0]
        assert isinstance(target, URL)
        assert target.drivername == 'postgresql+psycopg'
        assert target.password == 'pass@word'
        assert target.query['sslmode'] == 'require'


def test_secure_cookie_and_origin_protection(monkeypatch, tmp_path):
    monkeypatch.setenv('COOKIE_SECURE', 'true')
    monkeypatch.setenv('SERVE_FRONTEND', 'true')
    monkeypatch.delenv('FRONTEND_ORIGIN', raising=False)
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<title>LTMP Render UI</title>')
    monkeypatch.setenv('FRONTEND_DIST_DIR', str(dist))
    app = create_app('sqlite+pysqlite:///' + str(tmp_path / 'render-test.db'))
    with TestClient(app, base_url='https://ltmp-portal.onrender.com') as client:
        assert client.get('/').status_code == 200
        assert client.get('/').headers['strict-transport-security'] == 'max-age=31536000'
        assert client.get('/api/health').json()['status'] == 'ok'
        response = client.post('/api/rpc/login', json={'args': ['nobody','incorrect']},
                               headers={'Origin':'https://untrusted.example'})
        assert response.status_code == 403
        allowed = client.post('/api/rpc/login', json={'args': ['nobody','incorrect']},
                              headers={'Origin':'https://ltmp-portal.onrender.com'})
        assert allowed.status_code == 200
        assert allowed.json()['success'] is False


def test_render_login_cookie_security(monkeypatch, tmp_path):
    monkeypatch.setenv('COOKIE_SECURE', 'true')
    monkeypatch.setenv('SERVE_FRONTEND', 'true')
    monkeypatch.delenv('FRONTEND_ORIGIN', raising=False)
    dist = tmp_path / 'dist'
    dist.mkdir()
    (dist / 'index.html').write_text('<title>LTMP</title>')
    monkeypatch.setenv('FRONTEND_DIST_DIR', str(dist))
    url = 'sqlite+pysqlite:///' + str(tmp_path / 'login.db')
    engine = setup_engine(url)
    Factory = session_factory(engine)
    with Factory.begin() as db:
        db.add(User(username='tl-qa', password_hash=hash_password('private-test-pass'),
                    role='Team Leader', full_name='QA Manager', active=True))
    with TestClient(create_app(url), base_url='https://ltmp-portal.onrender.com') as client:
        response = client.post('/api/rpc/login', json={'args':['tl-qa','private-test-pass']},
                               headers={'Origin':'https://ltmp-portal.onrender.com'})
        assert response.status_code == 200 and response.json()['success']
        cookie = response.headers['set-cookie']
        assert 'HttpOnly' in cookie
        assert 'Secure' in cookie
        assert 'SameSite=lax' in cookie
        assert 'Path=/api' in cookie
        assert client.get('/api/migration/status').status_code == 200
        forbidden = client.post('/api/rpc/logout', json={'args':[]},
                                headers={'Origin':'https://malicious.example'})
        assert forbidden.status_code == 403
        assert client.get('/api/migration/status').status_code == 200
