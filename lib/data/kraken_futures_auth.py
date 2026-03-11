"""Kraken Futures API authentication and signed request helpers.

Uses separate credentials from Kraken spot (different API, different signing).
"""

import base64
import hashlib
import hmac
import os
import time
import urllib.parse

import requests

KRAKEN_FUTURES_API_URL = "https://futures.kraken.com"


class KrakenFuturesAuthError(Exception):
    pass


def get_futures_credentials() -> tuple[str, str]:
    """Load Kraken Futures API credentials from environment variables.

    Expected env vars:
        KRAKEN_FUTURES_API_KEY
        KRAKEN_FUTURES_API_SECRET

    Raises:
        KrakenFuturesAuthError if either variable is missing.
    """
    api_key = os.environ.get("KRAKEN_FUTURES_API_KEY")
    api_secret = os.environ.get("KRAKEN_FUTURES_API_SECRET")
    if not api_key or not api_secret:
        raise KrakenFuturesAuthError(
            "KRAKEN_FUTURES_API_KEY and KRAKEN_FUTURES_API_SECRET "
            "environment variables must be set."
        )
    return api_key, api_secret


def _sign_futures_request(endpoint: str, postdata: str, secret: str, nonce: str) -> str:
    """Generate Kraken Futures API signature.

    Signing scheme (different from spot):
        sha256 = SHA256(postdata + nonce + endpoint)
        signature = HMAC-SHA512(sha256, base64_decode(secret))
    """
    message = (postdata + nonce + endpoint).encode()
    sha256_hash = hashlib.sha256(message).digest()
    mac = hmac.new(base64.b64decode(secret), sha256_hash, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def private_futures_request(
    endpoint: str, data: dict | None = None, timeout: int = 30
) -> dict:
    """Make an authenticated POST request to the Kraken Futures private API.

    Args:
        endpoint: e.g. "/derivatives/api/v3/sendorder"
        data: POST body parameters (nonce is added automatically).
        timeout: Request timeout in seconds.

    Returns:
        The response dict from the Kraken Futures API.

    Raises:
        KrakenFuturesAuthError on credential, signing, or API errors.
    """
    api_key, api_secret = get_futures_credentials()

    if data is None:
        data = {}

    nonce = str(int(time.time() * 1000))
    data["nonce"] = nonce

    postdata = urllib.parse.urlencode(data)

    headers = {
        "APIKey": api_key,
        "Authent": _sign_futures_request(endpoint, postdata, api_secret, nonce),
        "Nonce": nonce,
    }

    resp = requests.post(
        KRAKEN_FUTURES_API_URL + endpoint,
        headers=headers,
        data=data,
        timeout=timeout,
    )
    resp.raise_for_status()
    result = resp.json()

    if result.get("result") != "success":
        errors = result.get("errors", result.get("error", "Unknown error"))
        raise KrakenFuturesAuthError(f"Kraken Futures API error: {errors}")

    return result
