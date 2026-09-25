"""POC Nango: credencial e instância GLPI por requisição.

Garante que dois tenants no mesmo processo não compartilham sessão, cache de leitura
nem caches de nomes (dropdown), e que a chave de rate limit lê headers minúsculos."""
import asyncio
import contextvars

from src.auth.session_manager import session_manager
from src.services.dropdown_cache import dropdown_cache


def _in_ctx(fn):
    return contextvars.copy_context().run(fn)


def test_pool_key_e_cache_key_diferem_por_instancia():
    def tenant(url, app, tok):
        def run():
            session_manager.set_current_tenant(url, app)
            session_manager.set_current_user_token(tok)
            return (session_manager._pool_key(tok), session_manager._get_cache_key("/Entity", {}),
                    session_manager.tenant_scope())
        return _in_ctx(run)

    a = tenant("https://glpi-a.example", "appA", "tokX")
    b = tenant("https://glpi-b.example", "appB", "tokX")  # mesmo user token, outra instância
    assert a[0] != b[0] and a[1] != b[1] and a[2] != b[2]


def test_sem_headers_usa_config_do_processo():
    def run():
        session_manager.set_current_tenant("", "")
        return session_manager.get_current_tenant()
    base, app = _in_ctx(run)
    from src.config import settings
    assert base == str(settings.glpi_base_url or "").rstrip("/")
    assert app == (settings.glpi_app_token or "")


def test_dropdown_cache_particionado_por_tenant():
    def fill(url, name):
        def run():
            session_manager.set_current_tenant(url, "app")
            session_manager.set_current_user_token("tok")
            dropdown_cache._cache.setdefault("Entity", {})[0] = name
            return dict(dropdown_cache._cache["Entity"])
        return _in_ctx(run)
    assert fill("https://glpi-a.example", "MSP Skills") == {0: "MSP Skills"}
    assert fill("https://glpi-b.example", "ENTIDADE-B") == {0: "ENTIDADE-B"}
    assert fill("https://glpi-a.example", "MSP Skills") == {0: "MSP Skills"}


def test_rate_limit_key_le_headers_minusculos_e_nao_expoe_token():
    key = session_manager._compose_user_key(
        {"x-glpi-url": "https://glpi-a.example", "x-glpi-app-token": "abcd1234", "x-glpi-user-token": "segredo"}, "10.0.0.1")
    assert key.startswith("https://glpi-a.example:1234:") and "segredo" not in key
