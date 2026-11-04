"""Regression tests for the 502 caused by reserved characters in POSTGRES_PASSWORD."""
from pathlib import Path

import pytest
from sqlalchemy.engine import URL, make_url

from app.db import database_url, engine_for


@pytest.mark.parametrize('secret', [
    'MyPass@1234', 'test@1234@5678', 'abc#def', 'ab:cd/ef',
    'a+plus%percent?question', 'pa$$w0rd:with@mix/#',
])
def test_raw_postgres_password_is_not_parsed_as_a_hostname(monkeypatch, secret):
    monkeypatch.setenv('POSTGRES_PASSWORD', secret)
    monkeypatch.setenv('POSTGRES_HOST', 'db')
    monkeypatch.setenv('POSTGRES_USER', 'ltmp')
    monkeypatch.setenv('POSTGRES_DB', 'ltmp')
    monkeypatch.setenv('POSTGRES_PORT', '5432')
    url = database_url()
    assert isinstance(url, URL)
    assert url.password == secret
    assert url.host == 'db'
    assert url.username == 'ltmp'
    assert url.database == 'ltmp'
    assert url.port == 5432
    # The URI round-trips without corrupting user-entered characters.
    rendered = url.render_as_string(hide_password=False)
    assert make_url(rendered).password == secret
    assert make_url(rendered).host == 'db'
    # Check engine_for passes the URL object unchanged to SQLAlchemy.
    import app.db as db_module
    seen = {}
    def fake_engine(value, **kwargs):
        seen['url'] = value
        seen['kwargs'] = kwargs
        return object()
    with monkeypatch.context() as patch:
        patch.setattr(db_module, 'create_engine', fake_engine)
        engine_for(url)
    assert seen['url'] is url
    assert seen['kwargs']['pool_pre_ping'] is True


def test_sqlite_development_config_retained(monkeypatch, tmp_path):
    monkeypatch.delenv('POSTGRES_PASSWORD', raising=False)
    url = f'sqlite+pysqlite:///{tmp_path / "test.db"}'
    monkeypatch.setenv('DATABASE_URL', url)
    assert database_url() == url
    engine = engine_for()
    assert engine.dialect.name == 'sqlite'
    engine.dispose()


def test_empty_postgres_password_is_rejected(monkeypatch):
    monkeypatch.setenv('POSTGRES_PASSWORD', '')
    with pytest.raises(ValueError, match='must not be empty'):
        database_url()


def test_compose_passes_raw_database_secret_to_backend():
    project = Path(__file__).resolve().parents[2]
    content = (project / 'docker-compose.yml').read_text()
    assert 'POSTGRES_HOST: db' in content
    assert content.count('POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:') == 2
    assert 'DATABASE_URL:' not in content
    assert 'POSTGRES_PASSWORD_ENCODED:' not in content
    assert (project / '.env.example').exists()
    assert (project / 'imports').is_dir()
