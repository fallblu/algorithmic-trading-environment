"""Kraken REST API authentication and signed request helpers."""

import base64
import hashlib
import hmac
import os
import time
import urllib.parse

import requests

KRAKEN_API_URL = "https://api.kraken.com"


class KrakenAuthError(Exception):
    pass


def get_credentials() -> tuple[str, str]:
    """Load Kraken API credentials from environment variables.

    Expected env vars:
        KRAKEN_API_KEY  — the API key string
        KRAKEN_API_SECRET — the base64-encoded private key

    Raises:
        KrakenAuthError if either variable is missing.
    """
    api_key = os.environ.get("KRAKEN_API_KEY")
    api_secret = os.environ.get("KRAKEN_API_SECRET")
    if not api_key or not api_secret:
        raise KrakenAuthError(
            "KRAKEN_API_KEY and KRAKEN_API_SECRET environment variables must be set."
        )
    return api_key, api_secret


def _sign_request(uri_path: str, data: dict, secret: str) -> str:
    """Generate Kraken API-Sign header value.

    Signing scheme:
        HMAC-SHA512(uri_path + SHA256(nonce + postdata), base64_decode(secret))
    """
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data["nonce"]) + postdata).encode()
    message = uri_path.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def private_request(endpoint: str, data: dict | None = None, timeout: int = 30) -> dict:
    """Make an authenticated POST request to the Kraken private API.

    Args:
        endpoint: e.g. "/0/private/Balance"
        data: POST body parameters (nonce is added automatically).
        timeout: Request timeout in seconds.

    Returns:
        The "result" dict from the Kraken response.

    Raises:
        KrakenAuthError on credential, signing, or API errors.
    """
    api_key, api_secret = get_credentials()

    if data is None:
        data = {}
    data["nonce"] = str(int(time.time() * 1000))

    headers = {
        "API-Key": api_key,
        "API-Sign": _sign_request(endpoint, data, api_secret),
    }

    resp = requests.post(
        KRAKEN_API_URL + endpoint,
        headers=headers,
        data=data,
        timeout=timeout,
    )
    resp.raise_for_status()
    result = resp.json()

    if result.get("error"):
        raise KrakenAuthError(f"Kraken API error: {result['error']}")

    return result.get("result", {})
