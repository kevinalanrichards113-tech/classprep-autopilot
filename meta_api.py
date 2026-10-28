"""Meta Model API access for ClassPrep Autopilot.

Two credential routes, in order:
1. MODEL_API_KEY env var / .env  (for standalone deployment)
2. The Muse vault connection `custom.meta-model-api` via the credential
   surrogate (used when running inside Muse; the key itself is never
   readable and never touches this repo)

Verified Oct 28, 2026: base URL https://api.meta.ai/v1, Responses API,
model muse-spark-1.3. NOTE: Muse Spark is a reasoning model — most of the
output budget goes to reasoning tokens, so keep max_output_tokens high
(>= 2000) or responses come back empty with status "incomplete".
"""
import json
import os
import sys
import urllib.request

BASE_URL = "https://api.meta.ai/v1"
DEFAULT_MODEL = "muse-spark-1.3"
CONNECTOR_BIN = os.path.expanduser(
    "~/workspace/custom-connectors/custom.meta-model-api/bin")
SKILL_BIN = "/opt/muse/skills/custom-connector-setup/bin"


def get_key():
    return os.environ.get("MODEL_API_KEY") or os.environ.get("META_API_KEY")


def get_model():
    return os.environ.get("META_MODEL", DEFAULT_MODEL)


def _vault_available():
    return os.path.exists(os.path.join(CONNECTOR_BIN, "meta_api_call.py"))


def api_ready():
    return bool(get_key()) or _vault_available()


def _extract_text(resp: dict) -> str:
    if resp.get("output_text"):
        return resp["output_text"]
    parts = []
    for item in resp.get("output", []) or []:
        for content in item.get("content", []) or []:
            if content.get("type") in ("output_text", "text") and content.get("text"):
                parts.append(content["text"])
    return "\n".join(parts)


def _chat_via_sdk(system, user, max_output_tokens):
    from openai import OpenAI
    client = OpenAI(base_url=BASE_URL, api_key=get_key())
    resp = client.responses.create(
        model=get_model(), instructions=system, input=user,
        max_output_tokens=max_output_tokens)
    return resp.output_text


def _chat_via_vault(system, user, max_output_tokens):
    sys.path.insert(0, SKILL_BIN)
    from dynamic_credentials import add_surrogate_to_request, read_json_response

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            raise RuntimeError("redirect refused, verify the endpoint")

    payload = {"model": get_model(), "instructions": system, "input": user,
               "max_output_tokens": max_output_tokens}
    request = urllib.request.Request(
        f"{BASE_URL}/responses", data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    add_surrogate_to_request(request, "custom.meta-model-api",
                             allowed_hosts=["api.meta.ai"])
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=180) as r:
        return _extract_text(read_json_response(r))


def chat(system: str, user: str, max_output_tokens: int = 4000) -> str:
    """One Responses-API call. Raises RuntimeError with a plain message."""
    if get_key():
        try:
            return _chat_via_sdk(system, user, max_output_tokens)
        except ImportError:
            raise RuntimeError(
                "openai package not installed. Run: pip install -r requirements.txt")
    if _vault_available():
        try:
            return _chat_via_vault(system, user, max_output_tokens)
        except Exception as e:
            raise RuntimeError(f"Meta Model API call failed: {e}")
    raise RuntimeError(
        "No API key set. Add MODEL_API_KEY to .env "
        "(create the key at dev.meta.ai: Billing first, then API keys).")
