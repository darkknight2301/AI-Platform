"""Reach a remote Ollama over SSH.

HTTP is spoken through an SSH ``direct-tcpip`` channel: no local port is opened and nothing but
Ollama needs to run on the remote host. Host, username and password are asked for at run time and
live only in memory; the password is used solely to authenticate the SSH session and is never
logged, written to a file, or placed in any request to Ollama.
"""

import getpass
import http.client
import json
import logging
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any
from urllib.parse import urlparse

from ..config import SshCfg
from ..errors import ConfigError, RmsumError, SshAuthError, TransportError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SshCredentials:
    """Run-time SSH login. ``repr=False`` keeps the password out of tracebacks."""

    host: str
    username: str
    password: str = field(default="", repr=False)


Connector = Callable[[SshCfg, SshCredentials], Any]


def connect_paramiko(cfg: SshCfg, creds: SshCredentials) -> Any:
    """Open an authenticated paramiko SSHClient (password and/or key; the ssh-agent if neither is given)."""
    try:
        import paramiko
    except ImportError:
        raise ConfigError("ssh.enabled needs paramiko: pip install 'rmsum[ssh]'") from None
    client = paramiko.SSHClient()
    client.load_system_host_keys()  # ~/.ssh/known_hosts
    # RejectPolicy unless the user explicitly accepted the risk: an unverified host could capture the password.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy() if cfg.trust_unknown_host else paramiko.RejectPolicy())
    log.info("connecting to %s@%s:%d", creds.username, creds.host, cfg.port)
    try:
        client.connect(
            creds.host,
            port=cfg.port,
            username=creds.username,
            password=creds.password or None,
            key_filename=cfg.key_file or None,
            timeout=15,
            look_for_keys=not creds.password,
            allow_agent=not creds.password,
        )
    except paramiko.AuthenticationException as exc:
        client.close()
        raise SshAuthError(f"SSH authentication failed for {creds.username}@{creds.host}") from exc
    except (paramiko.SSHException, OSError) as exc:
        client.close()
        raise TransportError(f"SSH connection to {creds.host} failed: {type(exc).__name__}: {exc}") from exc
    transport = client.get_transport()
    if transport is not None:
        transport.set_keepalive(30)
    return client


class SshTransport:
    """``Transport`` that carries every HTTP request through one SSH connection.

    The connection is opened by :meth:`connect` (eagerly, so bad credentials surface before any work
    starts) and re-opened automatically if it drops. ``connector`` is injectable for tests.
    """

    def __init__(self, cfg: SshCfg, creds: SshCredentials, connector: Connector = connect_paramiko) -> None:
        self._cfg = cfg
        self._creds = creds
        self._connector = connector
        self._client: Any = None

    @property
    def host(self) -> str:
        """SSH server host name (never the credentials)."""
        return self._creds.host

    def connect(self) -> None:
        """Open the SSH session now. Raises SshAuthError or TransportError."""
        self._client = self._connector(self._cfg, self._creds)

    def _ssh_transport(self) -> Any:
        transport = self._client.get_transport() if self._client is not None else None
        if transport is None or not transport.is_active():
            self.connect()
            transport = self._client.get_transport()
        return transport

    def request_json(
        self, url: str, *, headers: Mapping[str, str] | None = None, body: Any = None, timeout: float = 30.0
    ) -> Any:
        target = urlparse(url)
        host, port = target.hostname or self._cfg.remote_host, target.port or 80
        data = json.dumps(body).encode() if body is not None else None
        all_headers = {"Accept": "application/json", **({"Content-Type": "application/json"} if data else {})}
        all_headers.update(headers or {})
        try:
            channel = self._ssh_transport().open_channel(
                "direct-tcpip", (host, port), ("127.0.0.1", 0), timeout=timeout
            )
            channel.settimeout(timeout)
            connection = http.client.HTTPConnection(host, port, timeout=timeout)
            connection.sock = channel  # speak HTTP over the SSH channel instead of a TCP socket
            try:
                path = target.path + (f"?{target.query}" if target.query else "")
                connection.request("POST" if data else "GET", path, body=data, headers=all_headers)
                response = connection.getresponse()
                raw = response.read()
            finally:
                connection.close()
        except RmsumError:
            raise
        except Exception as exc:  # paramiko has its own exception hierarchy; reconnect on the next attempt
            self._drop_client()
            raise TransportError(f"SSH request via {self._creds.host} failed: {type(exc).__name__}: {exc}") from exc
        if response.status >= 400:
            raise TransportError(f"{response.reason} {raw[:200].decode('utf-8', 'replace')}".strip(), response.status)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise TransportError(f"invalid JSON from remote host: {exc}") from exc

    def _drop_client(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # best effort: the connection is already broken
                log.debug("error while closing broken SSH client", exc_info=True)
        self._client = None

    def close(self) -> None:
        """Close the SSH session."""
        self._drop_client()


@dataclass
class CredentialPrompter:
    """Collects SSH credentials at run time. Input functions are injectable for tests."""

    ask: Callable[[str], str] = input
    ask_secret: Callable[[str], str] = getpass.getpass
    environ: Mapping[str, str] = field(default_factory=lambda: os.environ)
    interactive: Callable[[], bool] = lambda: sys.stdin.isatty()

    def credentials(self, defaults: SshCfg) -> SshCredentials:
        """Ask for host, username and password (once per run).

        Without a terminal (cron, CI) the values come from RMSUM_SSH_HOST / RMSUM_SSH_USER /
        RMSUM_SSH_PASSWORD instead, so unattended runs fail clearly rather than hang.
        """
        if not self.interactive():
            host = self.environ.get("RMSUM_SSH_HOST", defaults.host)
            user = self.environ.get("RMSUM_SSH_USER", defaults.username)
            if not host or not user:
                raise ConfigError(
                    "no terminal available: set RMSUM_SSH_HOST and RMSUM_SSH_USER (and RMSUM_SSH_PASSWORD)"
                )
            return SshCredentials(host, user, self.environ.get("RMSUM_SSH_PASSWORD", ""))
        host = self._required("Ollama server IP / hostname", defaults.host)
        user = self._required("SSH username", defaults.username)
        return SshCredentials(host, user, self.ask_secret(f"SSH password for {user}@{host}: "))

    def new_password(self, creds: SshCredentials) -> SshCredentials | None:
        """Ask again after a rejected password; None when no terminal is available."""
        if not self.interactive():
            return None
        return replace(creds, password=self.ask_secret(f"SSH password for {creds.username}@{creds.host}: "))

    def _required(self, label: str, default: str) -> str:
        """Prompt until a non-empty answer is given; Enter accepts the default shown in brackets."""
        while True:
            answer = self.ask(f"{label}{f' [{default}]' if default else ''}: ").strip() or default
            if answer:
                return answer


def open_ssh_transport(
    cfg: SshCfg,
    prompter: CredentialPrompter,
    on_secret: Callable[[str], None],
    connector: Connector = connect_paramiko,
    attempts: int = 3,
) -> SshTransport:
    """Prompt for credentials, connect, and give the user ``attempts`` tries for the password.

    ``on_secret`` receives every password entered so the logger can redact it.
    """
    creds = prompter.credentials(cfg)
    on_secret(creds.password)
    for attempt in range(1, attempts + 1):
        transport = SshTransport(cfg, creds, connector)
        try:
            transport.connect()
            return transport
        except SshAuthError:
            retry = prompter.new_password(creds) if attempt < attempts else None
            if retry is None:
                raise
            log.warning("SSH authentication failed (attempt %d/%d)", attempt, attempts)
            creds = retry
            on_secret(creds.password)
    raise AssertionError("unreachable")  # loop always returns or raises
