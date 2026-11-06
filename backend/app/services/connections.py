"""External data connections, with SSRF protection and credentials that stay on the server."""
from __future__ import annotations

import ipaddress
import json
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import psycopg
from psycopg import sql

from ..config import get_settings

ALLOWED_PORTS = {80, 443, 8080, 8443}
MAX_REDIRECTS = 3


class ConnectionFailure(Exception):
    """A connection problem. The message is safe to show and never includes secrets."""


def _is_blocked(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


def resolve_public_host(host: str, port: int) -> str:
    """Resolve a host and require every address to be public. Returns one address to pin to."""
    if not host:
        raise ConnectionFailure("A host name is required.")
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except (socket.gaierror, UnicodeError) as exc:
        raise ConnectionFailure(f"The host '{host}' could not be resolved.") from exc
    addresses = sorted({info[4][0].split("%")[0] for info in infos})
    if not addresses:
        raise ConnectionFailure(f"The host '{host}' could not be resolved.")
    if not get_settings().allow_private_connections and any(_is_blocked(a) for a in addresses):
        raise ConnectionFailure("Connections to private, loopback, link-local, or other internal network addresses are not allowed.")
    return addresses[0]


def validate_url(url: str) -> tuple[str, str]:
    """Validate a URL for import. Returns (url, pinned IP address)."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"}:
        raise ConnectionFailure("Only http and https URLs are allowed.")
    if parts.username or parts.password:
        raise ConnectionFailure("Put credentials in the secret header field, not in the URL.")
    if not parts.hostname:
        raise ConnectionFailure("The URL must include a host name.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as exc:
        raise ConnectionFailure("The URL has an invalid port.") from exc
    if port not in ALLOWED_PORTS and not get_settings().allow_private_connections:
        raise ConnectionFailure(f"Port {port} is not allowed. Allowed ports: {sorted(ALLOWED_PORTS)}.")
    return url.strip(), resolve_public_host(parts.hostname, port)


def _pinned_request(client: httpx.Client, url: str, address: str, headers: dict) -> httpx.Response:
    """Connect to the validated IP while keeping the hostname for the Host header and TLS checks.

    Pinning means a second DNS lookup cannot redirect the request to an internal address.
    """
    parts = urlsplit(url)
    host = f"[{address}]" if ":" in address else address
    netloc = f"{host}:{parts.port}" if parts.port else host
    pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
    host_header = parts.hostname + (f":{parts.port}" if parts.port else "")
    request = client.build_request("GET", pinned, headers={**headers, "Host": host_header, "Accept": "application/json"}, extensions={"sni_hostname": parts.hostname})
    return client.send(request, stream=True)


def fetch_json(url: str, *, secret: dict | None = None, transport: httpx.BaseTransport | None = None):
    """Fetch JSON with no automatic redirects, a timeout, and a response size limit."""
    settings = get_settings()
    limit = settings.connection_max_response_mb * 1024 * 1024
    headers = {}
    if secret and secret.get("header_name") and secret.get("header_value"):
        headers[secret["header_name"]] = secret["header_value"]
    current = url
    with httpx.Client(timeout=settings.connection_timeout_seconds, follow_redirects=False, transport=transport) as client:
        for hop in range(MAX_REDIRECTS + 1):
            current, address = validate_url(current)
            try:
                response = _pinned_request(client, current, address, headers)
            except httpx.TimeoutException as exc:
                raise ConnectionFailure("The request timed out.") from exc
            except httpx.HTTPError as exc:
                raise ConnectionFailure("The server could not be reached.") from exc
            try:
                if response.is_redirect:
                    if hop == MAX_REDIRECTS:
                        raise ConnectionFailure("The URL redirected too many times.")
                    target = urljoin(current, response.headers.get("location", ""))
                    if urlsplit(target).hostname != urlsplit(current).hostname:
                        headers = {}  # never forward credentials to a different host
                    current = target
                    continue
                if response.status_code >= 400:
                    raise ConnectionFailure(f"The server responded with status {response.status_code}.")
                body = bytearray()
                for chunk in response.iter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise ConnectionFailure(f"The response exceeds the {settings.connection_max_response_mb} MB limit.")
            finally:
                response.close()
            try:
                return json.loads(bytes(body))
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError) as exc:
                raise ConnectionFailure("The response was not valid JSON.") from exc
    raise ConnectionFailure("The URL redirected too many times.")


def records_at_path(payload, path: str | None):
    """Follow a dotted path such as 'data.items' to the record array in a JSON response."""
    value = payload
    for key in [p for p in (path or "").split(".") if p]:
        if not isinstance(value, dict) or key not in value:
            raise ConnectionFailure(f"The path '{path}' was not found in the response.")
        value = value[key]
    return value


def _pg_connect(config: dict, secret: dict) -> psycopg.Connection:
    settings = get_settings()
    host = str(config.get("host", "")).strip()
    port = int(config.get("port") or 5432)
    address = resolve_public_host(host, port)
    try:
        return psycopg.connect(
            host=host,
            hostaddr=address,
            port=port,
            dbname=config.get("database"),
            user=config.get("username"),
            password=secret.get("password") or None,
            sslmode=config.get("sslmode") or "prefer",
            connect_timeout=min(settings.connection_timeout_seconds, 15),
            options=f"-c default_transaction_read_only=on -c statement_timeout={settings.connection_timeout_seconds * 1000}",
            autocommit=True,
        )
    except psycopg.OperationalError as exc:
        # Driver messages can reveal host details and users, so a fixed message is returned.
        raise ConnectionFailure("Could not connect to PostgreSQL. Check the host, port, database, credentials, and SSL mode.") from exc


def pg_test(config: dict, secret: dict) -> None:
    with _pg_connect(config, secret) as con:
        con.execute("SELECT 1")


def pg_list_tables(config: dict, secret: dict) -> list[dict]:
    with _pg_connect(config, secret) as con:
        rows = con.execute(
            "SELECT table_schema, table_name FROM information_schema.tables "
            "WHERE table_type IN ('BASE TABLE', 'VIEW') AND table_schema NOT IN ('pg_catalog', 'information_schema') "
            "ORDER BY 1, 2 LIMIT 500"
        ).fetchall()
    return [{"schema": s, "table": t} for s, t in rows]


def pg_import_table(config: dict, secret: dict, schema: str, table: str) -> list[dict]:
    """Read one table. Only listed tables can be selected; no user-written SQL is run."""
    limit = get_settings().connection_max_rows
    with _pg_connect(config, secret) as con:
        known = con.execute("SELECT 1 FROM information_schema.tables WHERE table_schema = %s AND table_name = %s", (schema, table)).fetchone()
        if not known:
            raise ConnectionFailure("That table was not found, or this login cannot see it.")
        try:
            query = sql.SQL("SELECT * FROM {}.{} LIMIT %s").format(sql.Identifier(schema), sql.Identifier(table))
            cursor = con.execute(query, (limit,))
            names = [d.name for d in cursor.description]
            return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]
        except psycopg.Error as exc:
            raise ConnectionFailure("The table could not be read. Check that this login has SELECT permission.") from exc
