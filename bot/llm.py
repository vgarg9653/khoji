"""LLM layer for Khoji.AI — provider-agnostic.

The boundary this module exists to hold (PRD §5, §9, FR4):

    The MODEL handles LANGUAGE.  The CATALOGUE handles FACTS.

The model reads what a student wrote — any Indian language, voice or text,
however phrased — and maps it onto our controlled vocabularies. It never decides
eligibility, never states an amount or a deadline, and never names a scholarship
that is not in the catalogue. Every value it returns is validated against the
same lists the rule-based parser uses, so a hallucinated state or category is
dropped rather than trusted.

Two providers, chosen with LLM_PROVIDER:

    openrouter  one OpenAI-compatible endpoint, any model, swap with an env var
    gemini      Google direct, if you are spending Google credits

Both support audio, so voice notes work either way. Everything degrades: with no
key the bot falls back to the rule-based flow and keeps working in English.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass

import models
from conversation import CATEGORIES, LEVELS, STATES

log = logging.getLogger("bot.llm")

# Swap models without touching code. OpenRouter model ids are "vendor/model".
DEFAULT_OPENROUTER_MODEL = os.environ.get(
    "LLM_MODEL", "google/gemini-2.5-flash")
DEFAULT_GEMINI_MODEL = os.environ.get("LLM_MODEL", "gemini-2.5-flash")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

VALID_LEVELS = [v for v, _ in LEVELS]
VALID_CATEGORIES = [v for v, _ in CATEGORIES]

SUPPORTED_LANGUAGES = {
    "en": "English", "hi": "Hindi", "bn": "Bengali", "te": "Telugu",
    "mr": "Marathi", "ta": "Tamil", "gu": "Gujarati", "kn": "Kannada",
    "ml": "Malayalam", "or": "Odia", "pa": "Punjabi", "as": "Assamese",
    "ur": "Urdu", "raj": "Rajasthani", "mwr": "Marwari",
}

# WhatsApp sends voice notes as OGG/Opus. Kept explicit because format support
# varies by model, and an unsupported format fails silently as a bad transcript.
AUDIO_FORMATS = {
    "audio/ogg": "ogg", "audio/opus": "ogg", "audio/mpeg": "mp3",
    "audio/mp4": "m4a", "audio/aac": "aac", "audio/wav": "wav",
    "audio/x-wav": "wav", "audio/webm": "ogg", "audio/flac": "flac",
}

EXTRACT_SYSTEM = """You extract structured facts from an Indian student's message.

Return ONLY fields the student actually stated or clearly implied. If something \
is not stated, return null for it. Never guess. Guessing causes a student to be \
shown scholarships they cannot apply for.

Rules:
- state: one Indian state or union territory, spelled in full English. Map \
cities to their state (Jaipur -> Rajasthan). Map short forms (UP -> Uttar Pradesh).
- education_level: exactly one of school, ITI, diploma, UG, PG, PhD, professional.
  School means classes 1-12. UG means bachelor's. PG means master's.
- category: exactly one of SC, ST, OBC, EWS, minority, PwD, DNT, general.
- family_income_inr: yearly family income as a plain integer in rupees. \
"2 lakh" is 200000. "ढाई लाख" is 250000. If monthly, multiply by 12.
- class_level: integer 1-12, only for school students.
- gender: female, male, or transgender, only if stated.
- household_role: student, parent, or guardian — who is typing.
- language: BCP-47 code of the language written in (en, hi, raj, bn, ta...).

The student may write in any Indian language, in that language's script or in \
Latin transliteration (Hinglish). Understand both."""

ANSWER_SYSTEM = """You answer an Indian student's question about ONE scholarship.

You will be given that scholarship's record as JSON. Answer ONLY from that \
record. This is the entire basis for your answer.

- If the record does not contain the answer, say plainly that the source does \
not state it and tell the student to check the official page. Do NOT use general \
knowledge about Indian scholarships to fill the gap, even if you are confident.
- Never state an amount, deadline, or eligibility rule that is not in the record.
- A field that is null means the source did not publish it. Say so.
- Be brief: 2-3 sentences, warm and plain. This is WhatsApp on a small screen.
- Reply in the same language the student used."""

TRANSCRIBE_SYSTEM = """Transcribe this Indian student's voice note verbatim.

Return JSON only:
  text       what was said, in the script the language is normally written in
  language   BCP-47 code (en, hi, raj, bn, ta, ...)
  confident  true only if the audio was clear and you are sure of the words

Set confident to false if the audio is noisy, clipped, or you had to guess at \
numbers, names or amounts. A wrong number here sends a student to the wrong \
scholarship, so say when you are unsure."""

COACH_SYSTEM = """An Indian student asked a question that is hard to answer as written.

Rewrite it as a clearer question they could ask instead, and say in one short \
sentence what made your version answerable. Never criticise how they wrote it — \
many are writing in their second or third language. Never refuse to help.

Reply in their language. Return JSON: {"improved": "...", "why": "..."}"""


@dataclass
class ExtractedProfile:
    state: str | None = None
    education_level: str | None = None
    category: str | None = None
    family_income_inr: int | None = None
    class_level: int | None = None
    gender: str | None = None
    household_role: str | None = None
    language: str = "en"

    def any_field(self) -> bool:
        return any(getattr(self, f) is not None
                   for f in ("state", "education_level", "category",
                             "family_income_inr", "class_level", "gender"))


@dataclass
class Transcript:
    text: str
    language: str = "en"
    confident: bool = True


def validate_extraction(data: dict) -> ExtractedProfile:
    """Keep only values that exist in our controlled vocabularies.

    This is the guard that makes model output safe to use. A hallucinated state
    or an invented category is dropped instead of entering the student's profile
    and skewing every match. It runs on every provider's output.
    """
    out = ExtractedProfile()

    state = (data.get("state") or "").strip()
    if state:
        for s in STATES:
            if s.lower() == state.lower():
                out.state = s
                break

    level = (data.get("education_level") or "").strip()
    if level in VALID_LEVELS:
        out.education_level = level

    cat = (data.get("category") or "").strip()
    if cat in VALID_CATEGORIES:
        out.category = cat

    income = data.get("family_income_inr")
    if isinstance(income, (int, float)) and 0 < income <= 100_000_000:
        out.family_income_inr = int(income)

    cls = data.get("class_level")
    if isinstance(cls, int) and 1 <= cls <= 12:
        out.class_level = cls

    gender = (data.get("gender") or "").strip().lower()
    if gender in ("female", "male", "transgender"):
        out.gender = gender

    role = (data.get("household_role") or "").strip().lower()
    if role in ("student", "parent", "guardian"):
        out.household_role = role

    lang = (data.get("language") or "en").strip().lower()[:5]
    out.language = lang if lang in SUPPORTED_LANGUAGES else "en"
    return out


def _loads(raw: str | None) -> dict | None:
    """Parse JSON, tolerating the ```json fences some models add."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1] if "```" in text[3:] else text[3:]
        text = text.removeprefix("json").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        log.warning("model returned non-JSON: %s", raw[:160])
        return None


class BaseLLM:
    """Shared behaviour. Subclasses implement _chat and _chat_audio."""

    available = False
    model = ""

    # -- provider hooks ---------------------------------------------------
    def _chat(self, system: str, prompt: str, json_out: bool = False,
              role: str = models.ROUTER) -> str | None:
        """`role` picks the model. Providers that only have one ignore it."""
        raise NotImplementedError

    def _chat_audio(self, system: str, audio: bytes, mime: str) -> str | None:
        raise NotImplementedError

    # -- capabilities -----------------------------------------------------

    def extract_profile(self, text: str) -> ExtractedProfile | None:
        if not self.available or not (text or "").strip():
            return None
        data = _loads(self._chat(EXTRACT_SYSTEM, f"Student message: {text}",
                                 json_out=True, role=models.ROUTER))
        return validate_extraction(data) if data else None

    def transcribe(self, audio: bytes, mime: str = "audio/ogg") -> Transcript | None:
        """Voice note -> text (PRD FR1). None means transcription failed and the
        caller must ask the student to type instead."""
        if not self.available or not audio:
            return None
        data = _loads(self._chat_audio(TRANSCRIBE_SYSTEM, audio, mime))
        if not data or not (data.get("text") or "").strip():
            return None
        lang = (data.get("language") or "en").strip().lower()[:5]
        return Transcript(
            text=data["text"].strip(),
            language=lang if lang in SUPPORTED_LANGUAGES else "en",
            confident=bool(data.get("confident", True)),
        )

    def translate(self, text: str, language: str) -> str:
        """Returns the original on any failure, so an outage degrades to
        English rather than to silence."""
        if not self.available or language == "en" or language not in SUPPORTED_LANGUAGES:
            return text
        out = self._chat(
            f"Translate the user's message into {SUPPORTED_LANGUAGES[language]}. "
            f"Keep WhatsApp formatting (*bold*, _italic_), emoji, numbers, URLs, "
            f"dates and proper nouns exactly as they are. Scholarship names stay "
            f"in English. Reply with the translation only.", text,
            role=models.GENERATION)
        return out or text

    def coach_question(self, question: str) -> dict | None:
        """Improve an unclear question without blocking it (PRD §8)."""
        if not self.available or not (question or "").strip():
            return None
        return _loads(self._chat(COACH_SYSTEM, question, json_out=True,
                                 role=models.ROUTER))

    def answer_about(self, question: str, record: dict,
                     language: str = "en") -> str | None:
        """Answer strictly from one scholarship record (FR4)."""
        if not self.available:
            return None
        keep = ("name", "administering_body", "provider_name", "states",
                "education_levels", "class_min", "class_max", "categories",
                "gender", "income_ceiling_inr", "benefit_amount_min_inr",
                "benefit_amount_max_inr", "benefit_amount_text", "benefit_type",
                "renewable", "renewal_criteria", "documents_required",
                "application_mode", "application_url", "application_deadline",
                "deadline_is_tentative", "official_url", "status",
                "last_verified_date", "number_of_awards", "duration_years",
                "min_marks_percent", "age_min", "age_max",
                "parent_occupation_specific", "selection_process")
        trimmed = {k: record.get(k) for k in keep}
        return self._chat(
            ANSWER_SYSTEM,
            f"Scholarship record:\n{json.dumps(trimmed, ensure_ascii=False, indent=2)}"
            f"\n\nStudent's question: {question}", role=models.GENERATION)


class OpenRouterLLM(BaseLLM):
    """OpenAI-compatible endpoint fronting many providers.

    Chosen when you want to change models by editing an env var rather than
    redeploying code — set LLM_MODEL to any id from openrouter.ai/models.
    Audio is sent base64 in an `input_audio` part, which is how OpenRouter
    accepts voice notes; direct URLs are not supported.
    """

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.model = model or DEFAULT_OPENROUTER_MODEL
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY")
        self.available = bool(self.api_key)
        if self.available:
            log.info("LLM: OpenRouter (model=%s)", self.model)
        else:
            log.info("LLM: no OPENROUTER_API_KEY - rule-based only")

    def _post(self, messages: list[dict], json_out: bool) -> str | None:
        import httpx
        body: dict = {"model": self.model, "messages": messages,
                      "temperature": 0.0 if json_out else 0.3,
                      "max_tokens": 900}
        if json_out:
            body["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(
                OPENROUTER_URL, json=body, timeout=45,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    # OpenRouter uses these for attribution; harmless if unset.
                    "HTTP-Referer": os.environ.get("PUBLIC_URL", "https://khoji.ai"),
                    "X-Title": "Khoji.AI",
                })
            if r.status_code >= 400:
                log.warning("openrouter %s: %s", r.status_code, r.text[:250])
                return None
            return r.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.warning("openrouter call failed: %s: %s", type(e).__name__, e)
            return None

    def _chat(self, system: str, prompt: str, json_out: bool = False,
              role: str = models.ROUTER) -> str | None:
        # One endpoint, one model id. Role-based routing is a Gemini-side
        # concept here; OpenRouter users swap models with LLM_MODEL.
        return self._post([{"role": "system", "content": system},
                           {"role": "user", "content": prompt}], json_out)

    def _chat_audio(self, system: str, audio: bytes, mime: str) -> str | None:
        fmt = AUDIO_FORMATS.get(mime.split(";")[0].strip().lower(), "ogg")
        return self._post([
            {"role": "system", "content": system},
            {"role": "user", "content": [
                {"type": "text", "text": "Transcribe this voice note."},
                {"type": "input_audio", "input_audio": {
                    "data": base64.b64encode(audio).decode(), "format": fmt}},
            ]},
        ], json_out=True)


class GeminiLLM(BaseLLM):
    """Google direct — use this if you are spending Google credits."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        if model:
            os.environ["LLM_MODEL"] = model      # explicit beats configured
        self.model = model or models.for_role(models.GENERATION)
        self._served: dict[str, str] = {}
        self._client = None
        key = (api_key or os.environ.get("GEMINI_API_KEY")
               or os.environ.get("GOOGLE_API_KEY"))
        if not key:
            log.info("LLM: no GEMINI_API_KEY - rule-based only")
            return
        try:
            from google import genai
            self._client = genai.Client(api_key=key)
            log.info("LLM: Gemini direct | %s", models.describe())
        except Exception as e:
            log.warning("Gemini unavailable (%s) - rule-based only", e)

    @property
    def available(self) -> bool:  # type: ignore[override]
        return self._client is not None

    def _cfg(self, system: str, json_out: bool):
        from google.genai import types
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.0 if json_out else 0.3,
            max_output_tokens=900,
            response_mime_type="application/json" if json_out else None,
        )

    def _generate(self, role: str, contents, system: str, json_out: bool) -> str | None:
        """One call, tried down the role's model chain.

        A 429 on the first model is not the end of the day: the next model in
        the chain is a different quota bucket on the same key. The bot was found
        live with its only model exhausted and three others idle.
        """
        last = None
        for model in models.chain(role):
            try:
                r = self._client.models.generate_content(
                    model=model, contents=contents,
                    config=self._cfg(system, json_out))
                if model != self._served.get(role):
                    log.info("model[%s] -> %s", role, model)
                    self._served[role] = model
                return (r.text or "").strip()
            except Exception as e:
                last = e
                if not models.should_try_next(e):
                    break
                log.warning("model[%s] %s unusable (%s); trying next",
                            role, model, str(e)[:110])
        log.warning("gemini %s failed: %s: %s", role, type(last).__name__, last)
        return None

    def _chat(self, system: str, prompt: str, json_out: bool = False,
              role: str = models.ROUTER) -> str | None:
        if not self._client:
            return None
        return self._generate(role, prompt, system, json_out)

    def _chat_audio(self, system: str, audio: bytes, mime: str) -> str | None:
        if not self._client:
            return None
        from google.genai import types
        part = types.Part.from_bytes(data=audio, mime_type=mime.split(";")[0].strip())
        return self._generate(models.AUDIO,
                              [part, "Transcribe this voice note."],
                              system, json_out=True)


class NullLLM(BaseLLM):
    """No provider configured. The bot runs rule-based, English only."""
    available = False


def build_llm() -> BaseLLM:
    """Pick a provider from the environment.

    LLM_PROVIDER=openrouter|gemini|none. With nothing set we prefer whichever
    key exists, so a working deployment does not depend on remembering a flag.
    """
    choice = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if choice == "none":
        return NullLLM()
    if choice == "openrouter":
        return OpenRouterLLM()
    if choice == "gemini":
        return GeminiLLM()

    if os.environ.get("OPENROUTER_API_KEY"):
        return OpenRouterLLM()
    if os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY"):
        return GeminiLLM()
    log.info("LLM: no provider key found - rule-based only")
    return NullLLM()


def list_models() -> list[str]:
    """Print model ids the configured provider offers, so you can set LLM_MODEL
    to something confirmed rather than guessed."""
    if os.environ.get("OPENROUTER_API_KEY"):
        import httpx
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=30)
        r.raise_for_status()
        out = []
        for m in r.json().get("data", []):
            mods = (m.get("architecture") or {}).get("input_modalities") or []
            tag = " [audio]" if "audio" in mods else ""
            out.append(f"{m['id']}{tag}")
        return sorted(out)

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        from google import genai
        client = genai.Client(api_key=key)
        return sorted(m.name.replace("models/", "") for m in client.models.list()
                      if not getattr(m, "supported_actions", None)
                      or "generateContent" in m.supported_actions)

    raise SystemExit("Set OPENROUTER_API_KEY or GEMINI_API_KEY first.")


if __name__ == "__main__":
    for name in list_models():
        print(name)
