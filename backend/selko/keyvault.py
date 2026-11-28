"""Read selko's external API keys from Azure Key Vault at startup.

Every consumer pulls what it needs from Key Vault when it starts, with
Microsoft's SDK; nothing is pushed or rendered into files.
``selko.config.load_config`` calls :func:`fetch_missing` with the names its
environment (process environment plus ``.env``) does not already set: a set
variable always wins, as it does in CI. Each name is fetched at most once per
process, in parallel, and a key that cannot be read is simply absent: a run
that does not need it is not blocked, and one that does fails as
unauthorized.

Where the keys are is configuration, never code:

- ``SELKO_KEYVAULT_URL``: the vault holding the LLM provider keys.
- ``SELKO_KEYVAULT_HOSTS_URL``: the vault holding the OAuth clients.
  A name whose vault has no URL is not fetched.
- ``AZURE_TENANT_ID`` and ``AZURE_CLIENT_ID``: the Entra app that reads them.

The credential is picked by environment, explicitly:

1. ``AZURE_CLIENT_SECRET`` set (cloud sessions; the older name
   ``MELISMA_SECRETS_CLIENT_SECRET`` is accepted too): a client-secret
   credential for that app.
2. ``SELKO_KEYVAULT_AUTH=gce`` (production on a GCE VM): that app through
   workload identity federation, with a Google ID token from the GCE metadata
   server as the client assertion.
3. Otherwise the Azure CLI's sign-in (``az login`` on a workstation). Without
   ``az`` on ``PATH`` (CI, the image check) nothing is fetched.

``SELKO_KEYVAULT_AUTH=off`` disables the fetch; the test suite sets it unless
``--run-llm`` asks for real keys. Values are never logged: only counts and
names. The production image carries the tenant, client and vault URLs from
build arguments until the server's env file provides them.
"""

from __future__ import annotations

import logging
import shutil
import threading
import urllib.request
from collections.abc import Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)
# The SDK logs every request and response header at INFO; keep its warnings.
if logging.getLogger("azure").level == logging.NOTSET:
    logging.getLogger("azure").setLevel(logging.WARNING)

GCE_IDENTITY_URL = (
    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/"
    "default/identity?audience=api://AzureADTokenExchange&format=full"
)

#: Scope -> the setting that names its vault's URL.
DEV_VAULT = "dev"  # the LLM provider keys
HOSTS_VAULT = "hosts"  # the OAuth clients
VAULT_URL_SETTINGS = {DEV_VAULT: "SELKO_KEYVAULT_URL", HOSTS_VAULT: "SELKO_KEYVAULT_HOSTS_URL"}

#: Names the client secret may be set under, the standard one first.
CLIENT_SECRET_NAMES = ("AZURE_CLIENT_SECRET", "MELISMA_SECRETS_CLIENT_SECRET")

#: Environment variable -> (vault scope, secret). Only external keys: selko's own
#: SELKO_JWT_SECRET and non-secret settings stay in its env file.
SECRETS: dict[str, tuple[str, str]] = {
    "ANTHROPIC_API_KEY": (DEV_VAULT, "selko-anthropic-api-key"),
    "OPENAI_API_KEY": (DEV_VAULT, "openai-api-key"),
    "GEMINI_API_KEY": (DEV_VAULT, "gemini-api-key"),
    "ALIBABA_API_KEY": (DEV_VAULT, "alibaba-api-key"),
    "ZAI_API_KEY": (DEV_VAULT, "zai-api-key"),
    "META_MODEL_API_KEY": (DEV_VAULT, "meta-model-api-key"),
    "MOONSHOT_API_KEY": (DEV_VAULT, "moonshot-api-key"),
    "DEEPSEEK_API_KEY": (DEV_VAULT, "deepseek-api-key"),
    "MINIMAX_API_KEY": (DEV_VAULT, "minimax-api-key"),
    "TINKER_API_KEY": (DEV_VAULT, "tinker-api-key"),
    "GOOGLE_CLIENT_ID": (HOSTS_VAULT, "selko-google-client-id"),
    "GOOGLE_CLIENT_SECRET": (HOSTS_VAULT, "selko-google-client-secret"),
    "MICROSOFT_CLIENT_ID": (HOSTS_VAULT, "selko-microsoft-client-id"),
    "MICROSOFT_CLIENT_SECRET": (HOSTS_VAULT, "selko-microsoft-client-secret"),
}

#: Other names config.py accepts for the same key; any of them set counts as set.
ALIASES: dict[str, tuple[str, ...]] = {
    "ANTHROPIC_API_KEY": ("SELKO_ANTHROPIC_API_KEY",),
    "ZAI_API_KEY": ("ZHIPU_API_KEY",),
    "META_MODEL_API_KEY": ("META_API_KEY", "MODEL_API_KEY"),
}

_lock = threading.Lock()
_fetched: dict[str, str] = {}
_attempted: set[str] = set()


def missing_names(values: Mapping[str, str]) -> list[str]:
    """The in-scope names that ``values`` sets under none of their spellings."""
    return [
        name for name in SECRETS
        if not any(values.get(n) for n in (name, *ALIASES.get(name, ())))
    ]


def _gce_identity_token() -> str:
    request = urllib.request.Request(GCE_IDENTITY_URL, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.read().decode()


def make_credential(getenv):
    """The credential this environment uses, or None (with its label)."""
    auth = (getenv("SELKO_KEYVAULT_AUTH") or "").strip().lower()
    if auth == "off":
        return None, "off"
    client_secret = next((v for v in (getenv(n) for n in CLIENT_SECRET_NAMES) if v), None)
    tenant_id = (getenv("AZURE_TENANT_ID") or "").strip()
    client_id = (getenv("AZURE_CLIENT_ID") or "").strip()
    if client_secret or auth == "gce":
        if not (tenant_id and client_id):
            logger.warning("Key Vault: AZURE_TENANT_ID or AZURE_CLIENT_ID is not set; nothing fetched")
            return None, "unconfigured"
    if client_secret:
        from azure.identity import ClientSecretCredential

        return ClientSecretCredential(
            tenant_id=tenant_id, client_id=client_id, client_secret=client_secret
        ), "client-secret"
    if auth == "gce":
        from azure.identity import ClientAssertionCredential

        return ClientAssertionCredential(
            tenant_id=tenant_id, client_id=client_id, func=_gce_identity_token
        ), "gce"
    if auth:
        logger.warning("Key Vault: unknown SELKO_KEYVAULT_AUTH=%r; nothing fetched", auth)
        return None, "unknown"
    if shutil.which("az", path=getenv("PATH")) is None:
        return None, "no-az"
    from azure.identity import AzureCliCredential

    return AzureCliCredential(), "azure-cli"


def vault_urls(getenv) -> dict[str, str]:
    """Scope -> vault URL, for the scopes this environment configures."""
    urls = {}
    for scope, setting in VAULT_URL_SETTINGS.items():
        url = (getenv(setting) or "").strip().rstrip("/")
        if url:
            urls[scope] = url
    return urls


def _read_vault(credential, vault_url: str, pairs: list[tuple[str, str]]) -> dict[str, str]:
    """Read ``(env name, secret)`` pairs from one vault, in parallel.

    The first read runs alone so the client's token policy holds a token before
    the rest fan out (otherwise each thread asks the credential, and the Azure
    CLI credential starts one ``az`` process per secret). If that read cannot
    authenticate or is forbidden, the rest of the vault is skipped.
    """
    from azure.core.exceptions import ClientAuthenticationError
    from azure.keyvault.secrets import SecretClient

    client = SecretClient(vault_url, credential)
    vault = vault_url.removeprefix("https://").split(".", 1)[0]
    found: dict[str, str] = {}

    def read(pair: tuple[str, str]) -> bool:
        """False when the credential failed or may not read this vault."""
        name, secret = pair
        try:
            value = client.get_secret(secret).value
        except Exception as exc:  # not found, forbidden, network: the key is absent
            logger.warning("Key Vault: %s (%s/%s) not read: %s", name, vault, secret, type(exc).__name__)
            denied = isinstance(exc, ClientAuthenticationError) or getattr(exc, "status_code", None) == 403
            return not denied
        if value:
            found[name] = value
        return True

    if read(pairs[0]) and len(pairs) > 1:
        with ThreadPoolExecutor(max_workers=len(pairs) - 1) as pool:
            list(pool.map(read, pairs[1:]))
    return found


def fetch_missing(names: Iterable[str], getenv) -> dict[str, str]:
    """Values from Key Vault for ``names`` (in-scope, unset), cached per process.

    ``getenv`` reads the merged configuration (it selects the credential).
    Returns every value fetched so far for the requested names; a name already
    attempted in this process is not fetched again.
    """
    wanted = [n for n in names if n in SECRETS]
    with _lock:
        todo = [n for n in wanted if n not in _attempted]
        if todo:
            credential, label = make_credential(getenv)
            urls = vault_urls(getenv)
            if credential is not None:
                by_vault: dict[str, list[tuple[str, str]]] = {}
                unconfigured = []
                for name in todo:
                    scope, secret = SECRETS[name]
                    if scope in urls:
                        by_vault.setdefault(urls[scope], []).append((name, secret))
                    else:
                        unconfigured.append(name)
                if unconfigured:
                    logger.info(
                        "Key Vault: no vault URL (%s) for %d keys",
                        ", ".join(sorted({VAULT_URL_SETTINGS[SECRETS[n][0]] for n in unconfigured})),
                        len(unconfigured),
                    )
                if by_vault:
                    with ThreadPoolExecutor(max_workers=len(by_vault)) as pool:
                        for found in pool.map(lambda item: _read_vault(credential, *item), by_vault.items()):
                            _fetched.update(found)
                loaded = [n for n in todo if n in _fetched]
                logger.info(
                    "Key Vault: loaded %d of %d keys (credential: %s)%s",
                    len(loaded), len(todo), label,
                    "; not loaded: " + ", ".join(n for n in todo if n not in _fetched)
                    if len(loaded) < len(todo) else "",
                )
                _attempted.update(todo)
            elif label != "off":
                logger.info("Key Vault: no credential (%s); %d keys not fetched", label, len(todo))
                _attempted.update(todo)
        return {n: _fetched[n] for n in wanted if n in _fetched}


def reset_cache() -> None:
    """Forget fetched values (tests)."""
    with _lock:
        _fetched.clear()
        _attempted.clear()
