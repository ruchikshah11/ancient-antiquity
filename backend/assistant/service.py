"""Claude-backed visitor assistant: prompt, tool loop and usage accounting.

The Anthropic client is created lazily (and only when ANTHROPIC_API_KEY is set) through get_client(), which the
tests replace with a fake - the real API is never called from the test suite.
"""
import json
import logging

from django.conf import settings
from django.utils import timezone

from .tools import TOOL_DEFINITIONS, ToolContext, run_tool

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5-5"
# Models that accept server-side refusal fallbacks (fallbacks="default" + its beta header).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5", "claude-sonnet-5-5"}
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_TOKENS = 8000          # includes the model's (always-on) thinking
MAX_TOOL_ROUNDS = 6        # model -> tools -> model ... per visitor message
MAX_TURNS = 12             # conversation messages kept (older ones are dropped)
MAX_MESSAGE_CHARS = 2000
MAX_LINKS = 5
REQUEST_TIMEOUT = 60.0

SYSTEM_PROMPT = """You are the visitor assistant of Ancient Antiquity, a website for booking entry tickets to \
heritage places across India: museums, forts, palaces and monuments.

How to help
- Be warm, helpful and concise: a few short sentences or a short list. Plain text with simple "- " bullets only; \
no headings, tables or markdown links.
- Answer in the visitor's language. The visitor's chosen site language is given below; if they write in another \
language (for example Hindi in Devanagari, or Hinglish), reply in the language they wrote in.
- Facts about places, prices, timings, closed days, closures, slots, crowds, events, bookings and policies must \
come from the tools. Never guess or invent a price, timing, date or availability. If a tool has no answer, say \
you don't have that information and suggest the place page or support.
- Prices are in Indian rupees (write them like ₹50). Prices can change by date (seasonal pricing): use get_place \
or check_availability with the visitor's date.
- Use search_places to find a place's slug first when you only have a name, then get_place / check_availability. \
For "open on <weekday>" questions, use search_places with open_on_weekday, and mention calendar closures can \
still apply.
- General heritage knowledge (history, architecture, what to see, travel tips such as the best season or time of \
day) is welcome, kept brief; prefer the place's own facilities.best_time_to_visit when it exists.
- You cannot take payments, make, change or cancel bookings. Explain the steps instead: open the place page, \
choose a date and slot, pick tickets and pay on the checkout page; cancellations are done from My bookings. The \
site shows buttons for the pages you looked up, so refer to them ("use the button below") instead of writing URLs.
- my_bookings only shows the signed-in visitor's own bookings. Never discuss anyone else's bookings or personal data.
- Stay on topic: heritage places, visiting and booking in India. Politely decline unrelated requests.
- For problems you cannot solve (payment taken but no ticket, refunds not received), point to the Contact page."""


class AssistantUnavailable(Exception):
    pass


class AssistantError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def is_available():
    return bool(settings.ANTHROPIC_API_KEY)


def model_name():
    return (getattr(settings, "ASSISTANT_MODEL", "") or DEFAULT_MODEL).strip()


def get_client():
    """The Anthropic client (one per process)."""
    global _client
    if not is_available():
        raise AssistantUnavailable()
    if _client is None:
        import anthropic

        _client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY, timeout=REQUEST_TIMEOUT, max_retries=2)
    return _client


_client = None


def clean_messages(raw):
    """Validate the visitor's transcript: [{role, content}] -> the last MAX_TURNS turns, starting and ending with user."""
    if not isinstance(raw, list) or not raw:
        raise ValueError("messages must be a non-empty list")
    out = []
    for item in raw[-MAX_TURNS * 2:]:
        if not isinstance(item, dict):
            raise ValueError("each message needs role and content")
        role, content = item.get("role"), item.get("content")
        if role not in ("user", "assistant") or not isinstance(content, str):
            raise ValueError("role must be user or assistant and content a string")
        content = content.strip()[:MAX_MESSAGE_CHARS]
        if not content:
            continue
        if out and out[-1]["role"] == role:  # merge accidental doubles (e.g. a retried message)
            out[-1]["content"] += "\n\n" + content
        else:
            out.append({"role": role, "content": content})
    out = out[-MAX_TURNS:]
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise ValueError("the last message must be from the user")
    return out


def _page_context_text(page_context):
    if not page_context:
        return ""
    if isinstance(page_context, dict):
        parts = [f"{k}={str(v)[:120]}" for k, v in list(page_context.items())[:5] if v not in (None, "")]
        text = ", ".join(parts)
    else:
        text = str(page_context)
    return text[:300]


def build_system(lang, page_context, user):
    """Stable, cached prompt first; the per-request facts (date, language, page) after the cache breakpoint."""
    now = timezone.localtime()
    lines = [
        f"Today is {now:%A %d %B %Y}, {now:%H:%M} India time ({now.date().isoformat()}).",
        f"Visitor's site language: {'Hindi' if lang == 'hi' else 'English'}.",
        f"Visitor is {'signed in' if user is not None else 'not signed in'}.",
    ]
    ctx = _page_context_text(page_context)
    if ctx:
        lines.append(f"The visitor is looking at this page of the site: {ctx}")
    return [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "\n".join(lines)},
    ]


def _usage_add(totals, usage):
    if usage is None:
        return
    for key, attr in (("in", "input_tokens"), ("out", "output_tokens"),
                      ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
        totals[key] += int(getattr(usage, attr, 0) or 0)


def _text_of(response):
    return "\n".join(b.text for b in response.content if getattr(b, "type", "") == "text" and b.text).strip()


def chat(messages, lang="en", page_context=None, user=None):
    """Run one assistant turn. Returns dict(reply, links, usage, tool_calls, outcome)."""
    import anthropic

    client = get_client()
    model = model_name()
    ctx = ToolContext(user)
    convo = list(messages)
    totals = {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0}
    tool_calls = 0
    extra = {}
    if model in FALLBACK_MODELS:
        extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    params = dict(
        model=model,
        max_tokens=MAX_TOKENS,
        system=build_system(lang, page_context, ctx.user),
        tools=TOOL_DEFINITIONS,
        output_config={"effort": getattr(settings, "ASSISTANT_EFFORT", "low") or "low"},
        **extra,
    )

    reply, outcome = "", "ok"
    for _round in range(MAX_TOOL_ROUNDS):
        try:
            response = client.beta.messages.create(messages=convo, **params)
        except anthropic.RateLimitError as exc:
            raise AssistantError("The assistant is busy right now. Please try again in a minute.", 503) from exc
        except anthropic.APIStatusError as exc:
            logger.error("Assistant API error %s: %s", exc.status_code, exc.message)
            raise AssistantError("The assistant could not answer right now. Please try again.") from exc
        except anthropic.APIConnectionError as exc:
            raise AssistantError("The assistant could not be reached. Please try again.") from exc
        _usage_add(totals, getattr(response, "usage", None))

        if response.stop_reason == "refusal":
            reply, outcome = "", "refused"
            break
        tool_uses = [b for b in response.content if getattr(b, "type", "") == "tool_use"]
        if response.stop_reason != "tool_use" or not tool_uses:
            reply = _text_of(response)
            break
        convo.append({"role": "assistant", "content": response.content})
        results = []
        for block in tool_uses:
            tool_calls += 1
            result, is_error = run_tool(ctx, block.name, block.input)
            results.append({
                "type": "tool_result", "tool_use_id": block.id,
                "content": json.dumps(result, ensure_ascii=False, default=str),
                **({"is_error": True} if is_error else {}),
            })
        convo.append({"role": "user", "content": results})  # all results of a round in one message
    else:
        reply = _text_of(response) if response is not None else ""

    if outcome == "refused":
        reply = ("माफ़ कीजिए, मैं इसमें मदद नहीं कर सकता। विरासत स्थलों या टिकट बुकिंग के बारे में पूछें।" if lang == "hi"
                 else "Sorry, I can't help with that. Ask me about heritage places or booking tickets.")
    elif not reply:
        reply = ("माफ़ कीजिए, मैं अभी उत्तर नहीं दे सका। कृपया दोबारा पूछें।" if lang == "hi"
                 else "Sorry, I couldn't put an answer together. Please try asking again.")
    return {
        "reply": reply,
        "links": ctx.links[-MAX_LINKS:],
        "usage": totals,
        "tool_calls": tool_calls,
        "outcome": outcome,
        "model": model,
    }
