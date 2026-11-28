"""Key Vault key loading (selko.keyvault) and its wiring into load_config()."""

from __future__ import annotations

import threading

import pytest
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError, ResourceNotFoundError
from azure.identity import AzureCliCredential, ClientAssertionCredential, ClientSecretCredential

from selko import config as config_module
from selko import keyvault


@pytest.fixture(autouse=True)
def _fresh_cache():
    keyvault.reset_cache()
    yield
    keyvault.reset_cache()


DEV_URL = "https://dev-vault.vault.azure.net"
HOSTS_URL = "https://hosts-vault.vault.azure.net"
URL_TO_SCOPE = {DEV_URL: keyvault.DEV_VAULT, HOSTS_URL: keyvault.HOSTS_VAULT}
#: The settings an environment that reads both vaults has.
URLS = {"SELKO_KEYVAULT_URL": DEV_URL, "SELKO_KEYVAULT_HOSTS_URL": HOSTS_URL}
APP = {"AZURE_TENANT_ID": "00000000-0000-0000-0000-000000000001",
       "AZURE_CLIENT_ID": "00000000-0000-0000-0000-000000000002"}


class FakeSecretClient:
    """Stands in for azure.keyvault.secrets.SecretClient; records every read."""

    vaults: dict[str, dict[str, object]] = {}
    reads: list[tuple[str, str]] = []
    lock = threading.Lock()

    def __init__(self, vault_url, credential):
        self.vault = URL_TO_SCOPE[vault_url]
        self.credential = credential

    def get_secret(self, name):
        with self.lock:
            self.reads.append((self.vault, name))
        value = self.vaults.get(self.vault, {}).get(name)
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise ResourceNotFoundError("missing")
        return type("Secret", (), {"value": value})()


@pytest.fixture
def vault(monkeypatch):
    import azure.keyvault.secrets as secrets

    FakeSecretClient.vaults = {
        keyvault.DEV_VAULT: {secret: f"dev:{secret}" for vault_name, secret in keyvault.SECRETS.values()
                             if vault_name == keyvault.DEV_VAULT},
        keyvault.HOSTS_VAULT: {secret: f"hosts:{secret}" for vault_name, secret in keyvault.SECRETS.values()
                               if vault_name == keyvault.HOSTS_VAULT},
    }
    FakeSecretClient.reads = []
    monkeypatch.setattr(secrets, "SecretClient", FakeSecretClient)
    credential = object()
    monkeypatch.setattr(keyvault, "make_credential", lambda getenv: (credential, "test"))
    return FakeSecretClient


class TestCredentialSelection:
    # Validates: SEL-749
    def test_off_disables_even_with_a_client_secret(self):
        env = {**APP, "SELKO_KEYVAULT_AUTH": "off", "AZURE_CLIENT_SECRET": "s"}
        assert keyvault.make_credential(env.get) == (None, "off")

    # Validates: SEL-752
    @pytest.mark.parametrize("secret_name", keyvault.CLIENT_SECRET_NAMES)
    def test_a_client_secret_signs_in_as_the_configured_app(self, secret_name):
        credential, label = keyvault.make_credential({**APP, secret_name: "s"}.get)
        assert isinstance(credential, ClientSecretCredential)
        assert label == "client-secret"
        assert credential._client_id == APP["AZURE_CLIENT_ID"]
        assert credential._tenant_id == APP["AZURE_TENANT_ID"]

    # Validates: SEL-752
    @pytest.mark.parametrize("env", [
        {"AZURE_CLIENT_SECRET": "s"},
        {"AZURE_CLIENT_SECRET": "s", "AZURE_TENANT_ID": "t"},
        {"SELKO_KEYVAULT_AUTH": "gce", "AZURE_CLIENT_ID": "c"},
    ])
    def test_without_tenant_and_client_nothing_is_fetched(self, env):
        assert keyvault.make_credential(env.get) == (None, "unconfigured")

    def test_no_tenant_client_or_vault_is_written_in_the_code(self):
        """Where the keys live is configuration: the module names no ID or vault."""
        import re
        from pathlib import Path

        source = Path(keyvault.__file__).read_text()
        assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", source)
        assert ".vault.azure.net" not in source

    # Validates: SEL-751
    def test_gce_uses_workload_identity_with_the_metadata_token(self, monkeypatch):
        credential, label = keyvault.make_credential({**APP, "SELKO_KEYVAULT_AUTH": "gce"}.get)
        assert isinstance(credential, ClientAssertionCredential)
        assert label == "gce"
        assert credential._client._client_id == APP["AZURE_CLIENT_ID"]
        assert credential._client._tenant_id == APP["AZURE_TENANT_ID"]

        seen = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def read(self):
                return b"google-id-token"

        def urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["flavor"] = request.get_header("Metadata-flavor")
            return Response()

        monkeypatch.setattr(keyvault.urllib.request, "urlopen", urlopen)
        assert keyvault._gce_identity_token() == "google-id-token"
        assert seen["url"] == keyvault.GCE_IDENTITY_URL
        assert "audience=api://AzureADTokenExchange" in seen["url"]
        assert seen["flavor"] == "Google"

    def test_mac_uses_the_azure_cli_when_az_is_on_path(self, tmp_path):
        az = tmp_path / "az"
        az.write_text("#!/bin/sh\n")
        az.chmod(0o755)
        credential, label = keyvault.make_credential({"PATH": str(tmp_path)}.get)
        assert isinstance(credential, AzureCliCredential)
        assert label == "azure-cli"

    def test_without_az_nothing_is_fetched(self, tmp_path):
        assert keyvault.make_credential({"PATH": str(tmp_path)}.get) == (None, "no-az")

    # Validates: SEL-749
    def test_unknown_auth_value_fetches_nothing(self):
        assert keyvault.make_credential({"SELKO_KEYVAULT_AUTH": "gcp"}.get) == (None, "unknown")


class TestFetch:
    # Validates: SEL-746
    def test_missing_names_honours_aliases(self):
        values = {"SELKO_ANTHROPIC_API_KEY": "x", "MODEL_API_KEY": "y", "ZHIPU_API_KEY": "z",
                  "OPENAI_API_KEY": ""}
        missing = keyvault.missing_names(values)
        assert "ANTHROPIC_API_KEY" not in missing
        assert "META_MODEL_API_KEY" not in missing
        assert "ZAI_API_KEY" not in missing
        assert "OPENAI_API_KEY" in missing  # empty counts as unset

    # Validates: SEL-748
    def test_fetches_each_name_from_its_vault_once(self, vault):
        names = list(keyvault.SECRETS)
        got = keyvault.fetch_missing(names, URLS.get)
        assert got == {name: f"{'dev' if v == keyvault.DEV_VAULT else 'hosts'}:{s}"
                       for name, (v, s) in keyvault.SECRETS.items()}
        assert sorted(vault.reads) == sorted(keyvault.SECRETS.values())

        vault.reads.clear()
        assert keyvault.fetch_missing(names, URLS.get) == got
        assert vault.reads == []  # cached for the process

    # Validates: SEL-747
    def test_a_missing_secret_does_not_block_the_rest(self, vault):
        del vault.vaults[keyvault.DEV_VAULT]["tinker-api-key"]
        got = keyvault.fetch_missing(["TINKER_API_KEY", "OPENAI_API_KEY", "GEMINI_API_KEY"], URLS.get)
        assert set(got) == {"OPENAI_API_KEY", "GEMINI_API_KEY"}

    def test_a_vault_the_credential_cannot_read_is_skipped(self, vault):
        # A cloud session's app reads the LLM keys' vault only.
        vault.vaults[keyvault.HOSTS_VAULT] = {
            s: ClientAuthenticationError("no") for v, s in keyvault.SECRETS.values() if v == keyvault.HOSTS_VAULT
        }
        got = keyvault.fetch_missing(list(keyvault.SECRETS), URLS.get)
        assert set(got) == {n for n, (v, _) in keyvault.SECRETS.items() if v == keyvault.DEV_VAULT}
        assert sum(1 for v, _ in vault.reads if v == keyvault.HOSTS_VAULT) == 1

    def test_a_forbidden_vault_is_skipped_after_one_read(self, vault):
        forbidden = HttpResponseError("forbidden")
        forbidden.status_code = 403
        vault.vaults[keyvault.HOSTS_VAULT] = {
            s: forbidden for v, s in keyvault.SECRETS.values() if v == keyvault.HOSTS_VAULT
        }
        keyvault.fetch_missing(list(keyvault.SECRETS), URLS.get)
        assert sum(1 for v, _ in vault.reads if v == keyvault.HOSTS_VAULT) == 1

    # Validates: SEL-752
    def test_a_vault_without_a_url_is_not_read(self, vault):
        got = keyvault.fetch_missing(list(keyvault.SECRETS), {"SELKO_KEYVAULT_URL": DEV_URL}.get)
        assert set(got) == {n for n, (v, _) in keyvault.SECRETS.items() if v == keyvault.DEV_VAULT}
        assert all(v == keyvault.DEV_VAULT for v, _ in vault.reads)

    # Validates: SEL-747
    def test_no_credential_fetches_nothing(self, monkeypatch):
        monkeypatch.setattr(keyvault, "make_credential", lambda getenv: (None, "no-az"))
        assert keyvault.fetch_missing(list(keyvault.SECRETS), URLS.get) == {}


class TestLoadConfigUsesTheVault:
    def _env(self, monkeypatch, tmp_path):
        monkeypatch.setattr(config_module, "PROJECT_ROOT", tmp_path)  # no .env
        monkeypatch.setenv("ENVIRONMENT", "development")
        monkeypatch.setenv("SELKO_DATA_DIR", "data")
        monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "none")
        for name, value in URLS.items():
            monkeypatch.setenv(name, value)
        for name in list(keyvault.SECRETS) + [a for v in keyvault.ALIASES.values() for a in v]:
            monkeypatch.delenv(name, raising=False)

    # Validates: SEL-745
    def test_vault_values_reach_the_config(self, monkeypatch, tmp_path, vault):
        self._env(monkeypatch, tmp_path)
        config = config_module.load_config()
        assert config.anthropic_api_key == "dev:selko-anthropic-api-key"
        assert config.meta_api_key == "dev:meta-model-api-key"
        assert config.zai_api_key == "dev:zai-api-key"
        assert config.google_client_secret == "hosts:selko-google-client-secret"
        assert config.microsoft_client_id == "hosts:selko-microsoft-client-id"

    # Validates: SEL-746
    def test_a_set_variable_wins_and_is_not_fetched(self, monkeypatch, tmp_path, vault):
        self._env(monkeypatch, tmp_path)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        monkeypatch.setenv("META_API_KEY", "meta-from-env")
        config = config_module.load_config()
        assert config.anthropic_api_key == "from-env"
        assert config.meta_api_key == "meta-from-env"
        read = {secret for _, secret in vault.reads}
        assert "selko-anthropic-api-key" not in read
        assert "meta-model-api-key" not in read
        assert "openai-api-key" in read

    def test_selko_anthropic_alias(self, monkeypatch, tmp_path, vault):
        self._env(monkeypatch, tmp_path)
        monkeypatch.setenv("SELKO_ANTHROPIC_API_KEY", "alias")
        assert config_module.load_config().anthropic_api_key == "alias"

    # Validates: SEL-749
    def test_the_suite_runs_with_the_vault_off(self, request):
        import os

        if request.config.getoption("--run-llm"):
            pytest.skip("--run-llm reads real keys")
        assert os.environ.get("SELKO_KEYVAULT_AUTH") == "off"
