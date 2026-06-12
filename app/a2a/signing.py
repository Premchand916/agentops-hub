# app/a2a/signing.py

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any
import uuid

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import load_pem_public_key
from jose import jws as jose_jws


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class KeyPair:
    private_pem: str
    public_pem: str
    key_id: str = field(default_factory=lambda: str(uuid.uuid4()))


# ── Key generation ────────────────────────────────────────────────────────────

def generate_key_pair(key_id: str | None = None) -> KeyPair:
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode()
    return KeyPair(
        private_pem=private_pem,
        public_pem=public_pem,
        key_id=key_id or str(uuid.uuid4()),
    )


# ── Singleton ─────────────────────────────────────────────────────────────────

_key_pair: KeyPair | None = None


def get_key_pair() -> KeyPair:
    global _key_pair
    if _key_pair is None:
        _key_pair = generate_key_pair(key_id="agentops-hub-signing-key")
    return _key_pair


# ── Sign / verify ─────────────────────────────────────────────────────────────

def sign_agent_card(card_dict: dict[str, Any], key_pair: KeyPair) -> str:
    """Sign an Agent Card dict with RS256. Returns a JWS compact serialization."""
    payload = json.dumps(card_dict, sort_keys=True).encode()
    return jose_jws.sign(
        payload,
        key_pair.private_pem,
        algorithm="RS256",
        headers={"kid": key_pair.key_id},
    )


def verify_agent_card(token: str, public_pem: str) -> dict[str, Any]:
    """Verify a signed Agent Card JWS. Raises on invalid signature. Returns the card dict."""
    payload_bytes = jose_jws.verify(token, public_pem, algorithms=["RS256"])
    return json.loads(payload_bytes)


# ── JWKS ──────────────────────────────────────────────────────────────────────

def _int_to_base64url(n: int) -> str:
    byte_length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(byte_length, "big")).rstrip(b"=").decode()


def get_jwks(key_pair: KeyPair) -> dict[str, Any]:
    """Return a JWKS document for the public key."""
    pub = load_pem_public_key(key_pair.public_pem.encode())
    nums = pub.public_numbers()  # type: ignore[union-attr]
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": "RS256",
                "kid": key_pair.key_id,
                "n": _int_to_base64url(nums.n),
                "e": _int_to_base64url(nums.e),
            }
        ]
    }
