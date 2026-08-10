"""WhatsApp webhook server.

Supports both providers people actually use, because which one you pick usually
depends on how fast you can get a number approved:

  * Twilio WhatsApp   -> POST /webhook/twilio   (form-encoded, replies via TwiML)
  * Meta Cloud API    -> GET+POST /webhook/meta (JSON, replies via Graph API)

Both adapters do nothing but translate the provider's payload into
(phone, text) and hand it to the same Bot. All the logic lives in engine.py.

    uvicorn bot.app:app --reload --port 8000

Environment:
    EDUDISHA_DATA      path to bot_matching.json (defaults to deliverables/)
    META_VERIFY_TOKEN       your webhook verify token
    META_ACCESS_TOKEN       Graph API token, needed to send replies
    META_PHONE_NUMBER_ID    the sending number's id
    TWILIO_AUTH_TOKEN       set to enable signature validation (recommended)
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import pathlib
import sys
from urllib.parse import urlencode

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from config import load_env   # noqa: E402
load_env()

import httpx                                     # noqa: E402
from fastapi import FastAPI, Form, Request, Response, HTTPException  # noqa: E402
from fastapi.responses import (HTMLResponse, JSONResponse,           # noqa: E402
                               PlainTextResponse)

import suggestions                               # noqa: E402
from engine import Bot                           # noqa: E402
from matching import Matcher                     # noqa: E402

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot.app")

# KHOJI_DATA is the current name. Every previous name is still honoured, so a
# service deployed before a rename keeps serving until it is redeployed —
# renaming a product should never be able to take the bot down.
DATA_PATH = pathlib.Path(
    os.environ.get("KHOJI_DATA")
    or os.environ.get("EDUDISHA_DATA")
    or os.environ.get("SCHOLARSAATHI_DATA")
    or (HERE.parent / "deliverables" / "dataset" / "bot_matching.json"))

VOICE_UNAVAILABLE = (
    "I couldn't listen to that voice note. Please type your answer instead — "
    "or send the voice note again.")
UNSUPPORTED_MESSAGE = (
    "I can read text and listen to voice notes. Please send one of those.")

app = FastAPI(title="Khoji.AI WhatsApp bot")
_bot: Bot | None = None


def get_bot() -> Bot:
    global _bot
    if _bot is None:
        if not DATA_PATH.exists():
            raise RuntimeError(f"dataset missing at {DATA_PATH}")

        from llm import build_llm
        from store_firestore import build_store

        llm = build_llm()
        store = build_store()
        _bot = Bot(Matcher.from_file(DATA_PATH), store=store, llm=llm)
        log.info("loaded %s scholarships | llm=%s(%s) | store=%s",
                 len(_bot.matcher.records), type(llm).__name__,
                 llm.model or "-", type(store).__name__)
    return _bot


def _model_chains() -> dict:
    """Role -> models tried in order. Empty for providers without routing."""
    try:
        import models
        return models.describe()
    except Exception:
        return {}


@app.get("/health")
def health() -> JSONResponse:
    try:
        b = get_bot()
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=503)
    return JSONResponse({
        "status": "ok",
        "sessions": len(b.store),
        "llm": type(b.llm).__name__ if b.llm else None,
        "llm_model": getattr(b.llm, "model", None) or None,
        "llm_ready": bool(b.llm and b.llm.available),
        # Which model does which job, and what it falls back to. Printed here
        # because "the bot went quiet in Hindi" turned out to be one exhausted
        # model, and there was no way to see that from outside.
        "models": _model_chains(),
        "store": type(b.store).__name__,
        **b.matcher.stats(),
    })


# --------------------------------------------------------------- Twilio

def _twiml(messages: list[str]) -> str:
    from xml.sax.saxutils import escape
    body = "".join(f"<Message>{escape(m)}</Message>" for m in messages)
    return f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>'


def _validate_twilio(request: Request, url: str, params: dict) -> bool:
    """Verify Twilio's HMAC so a stranger cannot drive the bot by POSTing to it.

    If TWILIO_AUTH_TOKEN is unset we allow the request but say so loudly —
    convenient while developing, not something to run in production.
    """
    token = os.environ.get("TWILIO_AUTH_TOKEN")
    if not token:
        log.warning("TWILIO_AUTH_TOKEN unset - webhook signature NOT validated")
        return True
    signature = request.headers.get("X-Twilio-Signature", "")
    payload = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(token.encode(), payload.encode(), hashlib.sha1).digest()
    import base64
    expected = base64.b64encode(digest).decode()
    return hmac.compare_digest(expected, signature)


@app.post("/webhook/twilio")
async def twilio_webhook(request: Request,
                         From: str = Form(default=""),
                         Body: str = Form(default="")) -> Response:
    form = dict(await request.form())
    if not _validate_twilio(request, str(request.url), form):
        raise HTTPException(status_code=403, detail="bad signature")

    phone = (From or "").replace("whatsapp:", "").strip()
    if not phone:
        return Response(_twiml([]), media_type="application/xml")

    replies = get_bot().handle(phone, Body or "")
    log.info("twilio %s -> %d message(s)", phone[-4:], len(replies))
    return Response(_twiml(replies), media_type="application/xml")


# ------------------------------------------------------------ Meta Cloud

@app.get("/webhook/meta")
def meta_verify(request: Request) -> Response:
    """Meta's one-time subscription handshake."""
    q = request.query_params
    if q.get("hub.mode") == "subscribe" and \
            q.get("hub.verify_token") == os.environ.get("META_VERIFY_TOKEN"):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="verification failed")


def _meta_extract(payload: dict) -> list[dict]:
    """Pull inbound messages out of Meta's deeply nested webhook body.

    Returns dicts of {phone, kind, text, media_id}. Statuses (delivered/read
    receipts) arrive on the same endpoint and must be ignored, or the bot ends
    up replying to its own delivery notifications.
    """
    out: list[dict] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                phone = msg.get("from", "")
                if not phone:
                    continue
                mtype = msg.get("type")
                if mtype == "text":
                    out.append({"phone": phone, "kind": "text",
                                "text": msg.get("text", {}).get("body", ""),
                                "media_id": None})
                elif mtype in ("audio", "voice"):
                    # PRD FR1: voice notes are a first-class input.
                    out.append({"phone": phone, "kind": "audio", "text": "",
                                "media_id": (msg.get(mtype) or {}).get("id")})
                elif mtype == "interactive":
                    # The id, not the title. We set the id to the text the
                    # engine parses and the title to what the student reads, and
                    # they are deliberately different where a number is matched
                    # more reliably than a word — tapping "School" has to arrive
                    # as "1". Title stays as the fallback for anything sent by
                    # an older build whose ids were not set.
                    i = msg.get("interactive") or {}
                    reply = i.get("button_reply") or i.get("list_reply") or {}
                    out.append({"phone": phone, "kind": "text",
                                "text": reply.get("id") or reply.get("title", ""),
                                "media_id": None})
                else:
                    out.append({"phone": phone, "kind": mtype or "unknown",
                                "text": "", "media_id": None})
    return out


async def _meta_fetch_media(media_id: str) -> tuple[bytes, str] | None:
    """Download a voice note. Meta gives a lookup URL first, then the bytes —
    and the second call needs the auth header too, which is easy to miss."""
    token = os.environ.get("META_ACCESS_TOKEN")
    if not (token and media_id):
        return None
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            meta = await client.get(
                f"https://graph.facebook.com/v21.0/{media_id}", headers=headers)
            if meta.status_code >= 400:
                log.error("media lookup failed %s: %s", meta.status_code,
                          meta.text[:200])
                return None
            info = meta.json()
            url = info.get("url")
            if not url:
                return None
            blob = await client.get(url, headers=headers)
            if blob.status_code >= 400:
                log.error("media download failed %s", blob.status_code)
                return None
            return blob.content, info.get("mime_type", "audio/ogg")
    except Exception as e:
        log.warning("media fetch failed: %s: %s", type(e).__name__, e)
        return None


async def _meta_send(phone: str, text: str, chips: list[dict] | None = None) -> None:
    """Send one message, as tappable options when we have them.

    Typing is the barrier this product exists to remove. A student who can only
    reply by typing "documents" — an English word, spelled correctly, on a
    keyboard they may not have set to the right script — is being asked for more
    literacy than reading the answer required. The web demo already offers taps;
    this brings the same thing to the channel students actually use.

    Falls back to plain text whenever the options do not fit WhatsApp's limits
    or the interactive send is rejected, because a message that arrives with no
    buttons is a minor loss and a message that does not arrive is the product
    failing.
    """
    token = os.environ.get("META_ACCESS_TOKEN")
    number_id = os.environ.get("META_PHONE_NUMBER_ID")
    if not (token and number_id):
        log.warning("META_ACCESS_TOKEN / META_PHONE_NUMBER_ID unset - not sending")
        return
    url = f"https://graph.facebook.com/v21.0/{number_id}/messages"
    headers = {"Authorization": f"Bearer {token}"}
    plain = {"messaging_product": "whatsapp", "to": phone,
             "type": "text", "text": {"preview_url": False, "body": text}}

    body = _meta_interactive(phone, text, chips) or plain
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(url, json=body, headers=headers)
        if r.status_code >= 400 and body is not plain:
            # Interactive has more ways to be rejected than text does (a limit
            # we mis-measured, a policy on the number). Never let that cost the
            # student the message itself.
            log.warning("meta interactive send failed %s: %s - retrying as text",
                        r.status_code, r.text[:200])
            r = await client.post(url, json=plain, headers=headers)
        if r.status_code >= 400:
            log.error("meta send failed %s: %s", r.status_code, r.text[:300])


# WhatsApp's documented ceilings. Exceeding any one of them rejects the whole
# message, so they are enforced here rather than hoped for.
_BODY_MAX = 1024
_BUTTON_TITLE_MAX = 20
_ROW_TITLE_MAX = 24
_MAX_BUTTONS = 3
_MAX_ROWS = 10


def _meta_interactive(phone: str, text: str, chips: list[dict] | None) -> dict | None:
    """Build a button or list payload, or None if plain text is the right call.

    Three buttons or fewer render inline, which is one tap. More than that has
    to be a list, which costs a tap to open — so the split is by count, not by
    preference.
    """
    if not chips or len(text) > _BODY_MAX:
        return None
    rows = [c for c in chips if c.get("send") and c.get("label")][:_MAX_ROWS]
    if not rows:
        return None

    base = {"messaging_product": "whatsapp", "to": phone, "type": "interactive"}

    if len(rows) <= _MAX_BUTTONS:
        if any(len(c["label"]) > _BUTTON_TITLE_MAX for c in rows):
            return None          # a truncated label can change what it means
        return base | {"interactive": {
            "type": "button",
            "body": {"text": text},
            "action": {"buttons": [
                {"type": "reply",
                 "reply": {"id": c["send"][:256], "title": c["label"]}}
                for c in rows]}}}

    if any(len(c["label"]) > _ROW_TITLE_MAX for c in rows):
        return None
    return base | {"interactive": {
        "type": "list",
        "body": {"text": text},
        "action": {"button": "Choose",
                   "sections": [{"rows": [
                       {"id": c["send"][:200], "title": c["label"]}
                       for c in rows]}]}}}


async def _send_batch(bot, phone: str, replies: list[str]) -> None:
    """Send a turn's replies, with the options attached to the last one.

    Only the last: the options answer the question the student has just been
    asked, and that question is always in the final message. Buttons on an
    earlier one would be answering something they have not read yet.
    """
    replies = list(replies)
    if not replies:
        return
    try:
        chips = suggestions.for_session(bot.store.get(phone))
    except Exception:
        chips = None                     # never lose a reply over a chip
    for reply in replies[:-1]:
        await _meta_send(phone, reply)
    await _meta_send(phone, replies[-1], chips)


@app.post("/webhook/meta")
async def meta_webhook(request: Request) -> JSONResponse:
    payload = await request.json()
    bot = get_bot()
    for msg in _meta_extract(payload):
        phone, kind = msg["phone"], msg["kind"]

        if kind == "audio":
            media = await _meta_fetch_media(msg["media_id"])
            if not media:
                await _meta_send(phone, VOICE_UNAVAILABLE)
                continue
            audio, mime = media
            await _send_batch(bot, phone, bot.handle_voice(phone, audio, mime))
            continue

        if kind != "text" or not msg["text"]:
            await _meta_send(phone, UNSUPPORTED_MESSAGE)
            continue

        await _send_batch(bot, phone, bot.handle(phone, msg["text"]))
    # Meta retries aggressively on non-200, which would double-send replies.
    return JSONResponse({"status": "ok"})


# --------------------------------------------------------------------- demo

@app.get("/", response_class=HTMLResponse)
@app.get("/demo", response_class=HTMLResponse)
def demo_page() -> Response:
    """A web chat driven by the same engine as WhatsApp.

    Exists so the product can be shown to anyone with a browser, without
    depending on a WhatsApp number being approved. It posts to /webhook/test,
    so what a visitor sees is exactly what a student on WhatsApp would get.
    """
    page = HERE / "demo.html"
    if not page.exists():
        raise HTTPException(status_code=404, detail="demo page not found")
    return HTMLResponse(page.read_text(encoding="utf-8"))


# --------------------------------------------------------------- local test

@app.post("/webhook/test")
async def test_webhook(request: Request) -> JSONResponse:
    """Provider-free endpoint for curl and integration tests."""
    payload = await request.json()
    phone = payload.get("phone", "+910000000000")
    text = payload.get("text", "")
    bot = get_bot()
    replies = bot.handle(phone, text)
    # Quick-reply chips for the demo page. Read AFTER handling, so they describe
    # the question the student is now looking at rather than the one they just
    # answered. WhatsApp gets no equivalent — it has its own reply UI — so this
    # stays on the test endpoint only.
    return JSONResponse({
        "phone": phone,
        "replies": replies,
        "suggestions": suggestions.for_session(bot.store.get(phone)),
    })
