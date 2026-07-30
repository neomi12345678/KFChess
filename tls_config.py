"""TLS/SSL context helpers shared by every server-side listener
(server/ws_server.py's GameServer, services/ws_gateway/main.py,
services/api_gateway/main.py) and the client (client/network_client.py,
client/client_cli.py) - opt-in, the same "an unset env var means today's
plaintext behavior" convention every other cross-process feature in this
project already follows (see server/main.py's own docstrings on
REDIS_URL/NATS_URL/DATABASE_URL).

Unset SSL_CERT_FILE/SSL_KEY_FILE (the default): get_server_ssl_context()
returns None, and every websockets.serve/web.run_app call site already
treats ssl=None/ssl_context=None as "plaintext ws://, http://" - exactly
today's behavior, no other code has to change to keep running without TLS.
Set both (see docker-compose.yml/k8s's own commented-out example), a real
certificate is loaded and that listener speaks wss://, https:// instead.

generate_self_signed_cert exists for local development/demos only (see its
own docstring) - a deployment that actually needs TLS in front of real
traffic should mount a certificate from cert-manager or a real CA via
SSL_CERT_FILE/SSL_KEY_FILE, never this function.
"""

import ipaddress
import ssl
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence


def generate_self_signed_cert(
    cert_path: str, key_path: str, hostnames: Sequence[str] = ("localhost", "127.0.0.1")
) -> None:
    """Writes a throwaway self-signed cert/key pair to cert_path/key_path,
    for local development only - real deployments mount a real certificate
    instead (see this module's own docstring). A no-op if both files
    already exist, so re-running this (or a container restarting against
    the same volume-mounted directory) doesn't rotate the cert - and thus
    invalidate anything that already pinned/trusted it - on every restart.

    Deliberately not run automatically by any server/service main() below -
    generating and trusting a cert is a conscious step a developer takes
    once (see this file's own __main__ block), the same explicit-step
    convention .env.example's own "docker compose up -d postgres" already
    uses, not a hidden side effect of starting a process.
    """
    if Path(cert_path).exists() and Path(key_path).exists():
        return

    # Imported lazily - only this dev-only generation path needs the
    # `cryptography` package (see requirements.txt's own comment on why
    # it's listed there and nowhere else); every server/service main()
    # below only ever calls get_server_ssl_context, which loads an
    # already-written cert through the stdlib ssl module alone.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])])

    san_entries = []
    for name in hostnames:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError:
            san_entries.append(x509.DNSName(name))

    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        # A day of slack behind "now" - avoids a freshly generated cert
        # being briefly not-yet-valid against a client clock that's a
        # little ahead.
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(private_key, hashes.SHA256())
    )

    Path(cert_path).write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    Path(key_path).write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )


def get_server_ssl_context(cert_file: Optional[str], key_file: Optional[str]) -> Optional[ssl.SSLContext]:
    """None (both cert_file/key_file unset) means plaintext - see this
    module's own docstring. Exactly one set is a misconfiguration and
    raises rather than silently falling back to plaintext: every other
    optional feature in this project fails soft on a half-set pair of env
    vars (see server/main.py's own _maybe_start_shard_heartbeat), but
    silently serving plaintext when a caller explicitly pointed at a
    certificate is a security regression, not a convenience - so this one
    call site deliberately departs from that convention.
    """
    if cert_file is None and key_file is None:
        return None
    if cert_file is None or key_file is None:
        raise ValueError("SSL_CERT_FILE and SSL_KEY_FILE must both be set, or neither")

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_file, key_file)
    return context


def get_client_ssl_context(*, verify: bool = True, ca_file: Optional[str] = None) -> ssl.SSLContext:
    """Only ever called once a caller has already decided TLS is on (see
    e.g. client/network_client.py's own NetworkGameClient.__init__) -
    "TLS or not" is that caller's own plain bool/None check, same as every
    other optional constructor argument in this project; this function
    only ever answers "verified or not" for the TLS-is-on case.

    verify=True (the default): a real, CA-signed certificate is required -
    ssl.create_default_context(), optionally trusting ca_file instead of
    the system store. verify=False: for connecting to a development server
    using generate_self_signed_cert's own throwaway cert above, where
    there is no CA to trust at all - hostname/CA validation is disabled.
    Kept as an explicit opt-in a caller has to ask for, never this
    function's own default, so an operator can't end up silently
    unverified in production by forgetting a flag.
    """
    if not verify:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context

    return ssl.create_default_context(cafile=ca_file)


def _main() -> None:  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate a throwaway self-signed cert/key pair for local development. "
        "Point SSL_CERT_FILE/SSL_KEY_FILE at the output, and (for a client connecting to it) "
        "pass verify_ssl=False - see this module's own docstring."
    )
    parser.add_argument("cert_path")
    parser.add_argument("key_path")
    parser.add_argument("hostnames", nargs="*", default=["localhost", "127.0.0.1"])
    args = parser.parse_args()

    generate_self_signed_cert(args.cert_path, args.key_path, args.hostnames)
    print(f"wrote {args.cert_path} and {args.key_path} for {', '.join(args.hostnames)}")


if __name__ == "__main__":  # pragma: no cover
    _main()
