"""llm_client.py - everything that talks to the LLM API.

Uses only the Python standard library (urllib), so there is nothing to install.

Providers (set LLM_PROVIDER in your .env file):
    gemini     Google Gemini  (free tier available)   key: GEMINI_API_KEY
    anthropic  Anthropic Claude                        key: ANTHROPIC_API_KEY
    openai     OpenAI or any OpenAI-compatible API     key: OPENAI_API_KEY

The API key is read from the environment / .env file. It is never in the code.
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from rules import find_room_mentions, WATER_WORDS, FITTING_WORDS, trim_summary

MAX_COMPLAINT_CHARS = 1000   # long inputs are cut, to keep cost and abuse down
MAX_RETRIES = 2              # extra attempts for network errors / rate limits

DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-haiku-5-5",
    "openai": "gpt-4o-mini",
}
KEY_VARIABLES = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


class LLMError(Exception):
    """Anything that goes wrong with the LLM call. `retryable` says if trying again may help."""

    def __init__(self, message, retryable=False):
        super().__init__(message)
        self.retryable = retryable


# ----------------------------------------------------------------------
# Settings and API key
# ----------------------------------------------------------------------
def load_env_file(path):
    """Read KEY=VALUE lines from a .env file into os.environ (does not overwrite)."""
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip().strip('"').strip("'"))


def get_settings():
    """Collect provider, model and key from the environment. Raises LLMError if no key."""
    provider = os.environ.get("LLM_PROVIDER", "gemini").strip().lower()
    if provider not in KEY_VARIABLES:
        raise LLMError(f"LLM_PROVIDER '{provider}' is not supported. Use one of: "
                       f"{', '.join(KEY_VARIABLES)} (or run with --mock).")
    key_name = KEY_VARIABLES[provider]
    api_key = os.environ.get(key_name) or os.environ.get("LLM_API_KEY")
    if not api_key:
        raise LLMError(
            f"No API key found. Copy .env.example to .env and put your key in {key_name}. "
            "(Or run with --mock to test without an LLM.)")
    return {
        "provider": provider,
        "api_key": api_key,
        "model": os.environ.get("LLM_MODEL", DEFAULT_MODELS[provider]),
        "base_url": os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        "timeout": float(os.environ.get("LLM_TIMEOUT", "30")),
    }


def load_system_prompt(path):
    """Read the system prompt from its own text file."""
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError as err:
        raise LLMError(f"cannot read system prompt file {path}: {err}")


# ----------------------------------------------------------------------
# HTTP helper and the three providers
# ----------------------------------------------------------------------
def _post_json(url, headers, body, timeout):
    """POST a JSON body, return the parsed JSON reply, or raise LLMError."""
    data = json.dumps(body).encode("utf-8")
    all_headers = {"Content-Type": "application/json"}
    all_headers.update(headers)
    request = urllib.request.Request(url, data=data, headers=all_headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", "replace")[:300]
        # 429 = rate limit, 5xx = server trouble: worth retrying. 401/403/404 are not.
        raise LLMError(f"HTTP {err.code}: {detail}", retryable=err.code in (429, 500, 502, 503, 504))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as err:
        raise LLMError(f"network or reply error: {err}", retryable=True)


def _user_message(complaint):
    """The complaint is wrapped in tags so the model treats it as DATA, not instructions."""
    clean = complaint[:MAX_COMPLAINT_CHARS].replace("</complaint>", "")
    return f"<complaint>\n{clean}\n</complaint>"


def _call_gemini(complaint, settings, system_prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings['model']}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "contents": [{"role": "user", "parts": [{"text": _user_message(complaint)}]}],
        "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
    }
    data = _post_json(url, {"x-goog-api-key": settings["api_key"]}, body, settings["timeout"])
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError):
        raise LLMError("unexpected Gemini reply shape (maybe blocked or empty)")


def _call_anthropic(complaint, settings, system_prompt):
    body = {
        "model": settings["model"],
        "max_tokens": 200,
        "temperature": 0,
        "system": system_prompt,
        "messages": [{"role": "user", "content": _user_message(complaint)}],
    }
    headers = {"x-api-key": settings["api_key"], "anthropic-version": "2023-06-01"}
    data = _post_json("https://api.anthropic.com/v1/messages", headers, body, settings["timeout"])
    try:
        return "".join(block.get("text", "") for block in data["content"] if block.get("type") == "text")
    except (KeyError, TypeError):
        raise LLMError("unexpected Anthropic reply shape")


def _call_openai(complaint, settings, system_prompt):
    body = {
        "model": settings["model"],
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _user_message(complaint)},
        ],
    }
    url = settings["base_url"].rstrip("/") + "/chat/completions"
    data = _post_json(url, {"Authorization": "Bearer " + settings["api_key"]}, body, settings["timeout"])
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError("unexpected OpenAI reply shape")


PROVIDER_FUNCTIONS = {"gemini": _call_gemini, "anthropic": _call_anthropic, "openai": _call_openai}


# ----------------------------------------------------------------------
# Turning the reply text into a Python dict
# ----------------------------------------------------------------------
def extract_json(text):
    """Parse the model's reply. Tolerates ```json fences and extra words around the JSON."""
    if not isinstance(text, str) or not text.strip():
        raise LLMError("empty reply from the model")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", cleaned).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(cleaned[start:end + 1])
        except json.JSONDecodeError:
            pass
    raise LLMError("reply was not valid JSON: " + cleaned[:80])


# ----------------------------------------------------------------------
# The function the rest of the program calls
# ----------------------------------------------------------------------
def classify(complaint, settings, system_prompt):
    """Send ONE complaint to the LLM and return its reply as a dict (NOT yet validated).

    Network errors and rate limits are retried with a growing wait (2 s, 4 s).
    Raises LLMError if it still fails.
    """
    call = PROVIDER_FUNCTIONS[settings["provider"]]
    for attempt in range(MAX_RETRIES + 1):
        try:
            return extract_json(call(complaint, settings, system_prompt))
        except LLMError as err:
            if not err.retryable or attempt == MAX_RETRIES:
                raise
            time.sleep(2 ** (attempt + 1))


# ----------------------------------------------------------------------
# MOCK classifier - NOT an LLM. Simple keyword rules so you can run the whole
# pipeline offline. Use it to test your Python; use the real LLM for your results.
# ----------------------------------------------------------------------
_MOCK_ISSUE_RULES = [
    ("internet", r"\b(wi-?fi|internet|lan|router|ethernet|network|broadband)\b"),
    ("carpentry", r"\b(door|lock|latch|window|cupboard|cot|bed|table|chair|hinge|shelf|handle|almirah|wardrobe)\b"),
    ("cleaning", r"\b(dustbin|clean(ing|ed)?|dirty|garbage|trash|sweep(ing)?|mop(ping)?|cobwebs?|dust)\b"),
    ("electrical", r"\b(fan|lights?|tube ?light|bulb|switch(board)?|sockets?|plug|wiring|mcb|ac|regulator|spark(s|ing)?|shock)\b"),
    ("plumbing", r"\b(tap|flush|toilet|drain(age)?|pipe|leak(s|ing|age)?|water|shower|bathroom|basin|overflow(ing)?|flood(ed|ing)?)\b"),
]
_MOCK_URGENT = re.compile(
    r"\bspark(s|ed|ing)?\b|\bshock(s|ed)?\b|burn(t|ing) smell|smell of burn(t|ing)|\bflood(s|ed|ing)?\b", re.I)


def mock_classify(complaint):
    """Stand-in for the LLM. Copies the first room-like thing it sees (like an LLM would)."""
    mentions = sorted(find_room_mentions(complaint))
    room = mentions[0] if mentions else None
    issue = "other"
    if WATER_WORDS.search(complaint) and FITTING_WORDS.search(complaint):
        issue = "electrical"
    else:
        for name, pattern in _MOCK_ISSUE_RULES:
            if re.search(pattern, complaint, re.I):
                issue = name
                break
    urgent = bool(_MOCK_URGENT.search(complaint)) or (
        WATER_WORDS.search(complaint) is not None and FITTING_WORDS.search(complaint) is not None)
    return {"room": room, "issue": issue, "urgent": urgent, "summary": trim_summary(complaint)}
