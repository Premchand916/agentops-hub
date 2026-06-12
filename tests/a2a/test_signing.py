# tests/a2a/test_signing.py

import json
import pytest
from fastapi.testclient import TestClient

from app.a2a.signing import (
    KeyPair,
    generate_key_pair,
    get_key_pair,
    get_jwks,
    sign_agent_card,
    verify_agent_card,
)
from app.a2a.server import app


# ── Key generation ────────────────────────────────────────────────────────────

def test_generate_key_pair_returns_pem_strings():
    kp = generate_key_pair()
    assert kp.private_pem.startswith("-----BEGIN")
    assert kp.public_pem.startswith("-----BEGIN")


def test_generate_key_pair_unique():
    kp1 = generate_key_pair()
    kp2 = generate_key_pair()
    assert kp1.private_pem != kp2.private_pem


def test_get_key_pair_is_singleton():
    kp1 = get_key_pair()
    kp2 = get_key_pair()
    assert kp1.key_id == kp2.key_id
    assert kp1.private_pem == kp2.private_pem


# ── Sign / verify ─────────────────────────────────────────────────────────────

def test_sign_returns_jws_compact():
    kp = generate_key_pair()
    token = sign_agent_card({"name": "test"}, kp)
    assert isinstance(token, str) and len(token) > 0
    assert token.count(".") == 2  # header.payload.signature


def test_verify_round_trips():
    kp = generate_key_pair()
    card = {"name": "AgentOps Hub", "version": "2.0.0"}
    token = sign_agent_card(card, kp)
    recovered = verify_agent_card(token, kp.public_pem)
    assert recovered == card


def test_verify_rejects_tampered_signature():
    kp = generate_key_pair()
    token = sign_agent_card({"name": "legit"}, kp)
    header, payload, _ = token.split(".")
    tampered = f"{header}.{payload}.invalidsignatureXXX"
    with pytest.raises(Exception):
        verify_agent_card(tampered, kp.public_pem)


def test_verify_rejects_wrong_key():
    kp1 = generate_key_pair()
    kp2 = generate_key_pair()
    token = sign_agent_card({"name": "legit"}, kp1)
    with pytest.raises(Exception):
        verify_agent_card(token, kp2.public_pem)


# ── JWKS ──────────────────────────────────────────────────────────────────────

def test_get_jwks_structure():
    kp = generate_key_pair()
    jwks = get_jwks(kp)
    assert "keys" in jwks
    assert len(jwks["keys"]) == 1
    key = jwks["keys"][0]
    assert key["kty"] == "RSA"
    assert key["alg"] == "RS256"
    assert key["use"] == "sig"
    assert key["kid"] == kp.key_id
    assert "n" in key and len(key["n"]) > 0
    assert "e" in key and len(key["e"]) > 0


# ── Server endpoints ──────────────────────────────────────────────────────────

def test_jwks_endpoint_returns_keys():
    client = TestClient(app)
    resp = client.get("/.well-known/jwks.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "keys" in data
    assert data["keys"][0]["kty"] == "RSA"


def test_agent_card_includes_signature():
    client = TestClient(app)
    resp = client.get("/.well-known/agent.json")
    assert resp.status_code == 200
    data = resp.json()
    assert "signature" in data
    assert data["signature"].count(".") == 2  # JWS compact


def test_agent_card_signature_is_verifiable():
    client = TestClient(app)
    card_resp = client.get("/.well-known/agent.json")
    jwks_resp = client.get("/.well-known/jwks.json")
    data = card_resp.json()
    token = data.pop("signature")
    # Recover public PEM from JWKS key_id to verify round-trip integrity
    # Use the singleton public key directly — JWKS kid must match
    kp = get_key_pair()
    recovered = verify_agent_card(token, kp.public_pem)
    assert recovered["name"] == data["name"]
