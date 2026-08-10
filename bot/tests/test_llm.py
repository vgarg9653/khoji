"""Gemini layer tests.

No API key needed: these exercise the validation boundary, which is the part
that matters. A model can return anything, so what protects the student is that
we only accept values from our controlled vocabularies — and that the bot works
unchanged when the model is absent.
"""

import pathlib
import sys

BOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT))

from engine import Bot, InMemorySessionStore   # noqa: E402
from llm import (GeminiLLM, NullLLM, OpenRouterLLM, ExtractedProfile,
                 build_llm, validate_extraction)       # noqa: E402
from matching import Matcher                   # noqa: E402
from test_bot import ALL                       # noqa: E402


# ------------------------------------------------- the validation boundary

def test_hallucinated_values_are_dropped():
    """A model inventing a state or category must not reach the profile."""
    out = validate_extraction({
        "state": "Wakanda",
        "education_level": "postdoctoral-wizardry",
        "category": "VIP",
        "family_income_inr": -5,
        "class_level": 99,
        "gender": "unknown",
        "language": "kl",
    })
    assert out.state is None
    assert out.education_level is None
    assert out.category is None
    assert out.family_income_inr is None
    assert out.class_level is None
    assert out.gender is None
    assert out.language == "en"          # unsupported language falls back


def test_valid_values_pass_through():
    out = validate_extraction({
        "state": "bihar",                # case-insensitive
        "education_level": "UG",
        "category": "SC",
        "family_income_inr": 150000,
        "class_level": 10,
        "gender": "female",
        "language": "hi",
    })
    assert out.state == "Bihar"
    assert out.education_level == "UG"
    assert out.category == "SC"
    assert out.family_income_inr == 150_000
    assert out.class_level == 10
    assert out.gender == "female"
    assert out.language == "hi"


def test_absurd_income_rejected():
    assert validate_extraction({"family_income_inr": 10**12,
                             "language": "en"}).family_income_inr is None


# ------------------------------------------------------ graceful degradation

def test_no_api_key_means_unavailable_not_crashed():
    g = GeminiLLM(api_key=None)
    # Depending on the environment a key may exist; only assert the contract.
    assert isinstance(g.available, bool)
    if not g.available:
        assert g.extract_profile("I am from Bihar") is None
        assert g.translate("hello", "hi") == "hello"
        assert g.answer_about("what documents?", {}) is None


def test_bot_works_without_llm():
    """The rule-based flow must be untouched when Gemini is absent."""
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=None)
    phone = "+917777777777"
    assert "Khoji" in bot.handle(phone, "hi")[0]
    bot.handle(phone, "Assam")
    bot.handle(phone, "1")
    bot.handle(phone, "10")
    bot.handle(phone, "2")
    bot.handle(phone, "1 lakh")
    assert "Assam State Scholarship" in bot.handle(phone, "4")[0]


def test_translation_failure_falls_back_to_english():
    class BrokenLLM:
        available = True

        def translate(self, text, language):
            raise RuntimeError("gemini down")

        def extract_profile(self, text):
            return None

    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=BrokenLLM())
    # handle() catches, resets, and still replies rather than stranding anyone.
    replies = bot.handle("+918888888888", "hi")
    assert replies and isinstance(replies[0], str)


# -------------------------------------------------------- free-text absorb

def test_free_text_fills_multiple_slots_at_once():
    class FakeLLM:
        available = True

        def extract_profile(self, text):
            return ExtractedProfile(state="Bihar", education_level="school",
                                    category="SC", class_level=10,
                                    family_income_inr=100_000, language="en")

        def translate(self, text, language):
            return text

    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=FakeLLM())
    phone = "+919999999999"
    bot.handle(phone, "hi")
    out = bot.handle(phone, "I am an SC student in class 10 from Bihar, "
                            "family income one lakh")
    profile = bot.store.get(phone).profile
    assert profile.state == "Bihar"
    assert profile.category == "SC"
    assert profile.class_level == 10
    assert profile.family_income_inr == 100_000
    # Every question was answered — but by inference, so it confirms once.
    assert any("Just to be sure" in m for m in out)
    out = bot.handle(phone, "haan")
    assert any("Found" in m or "couldn't find" in m for m in out)


class _KeralaLLM:
    """Extracts Kerala from anything, so we can see whether a slot is overwritten."""
    available = True

    def extract_profile(self, text):
        return ExtractedProfile(state="Kerala", language="en")

    def translate(self, text, language):
        return text


def test_free_text_does_not_overwrite_answered_slots():
    """Volunteering extra detail must not silently rewrite an explicit answer."""
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=_KeralaLLM())
    phone = "+919000000001"
    bot.handle(phone, "hi")
    bot.handle(phone, "Assam")                       # answered explicitly
    bot.handle(phone, "my school is quite far from home")
    assert bot.store.get(phone).profile.state == "Assam"


def test_an_explicit_correction_does_overwrite():
    """"Actually I meant X" is the one case where overwriting is the point."""
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=_KeralaLLM())
    phone = "+919000000002"
    bot.handle(phone, "hi")
    bot.handle(phone, "Assam")
    out = bot.handle(phone, "actually I meant Rajasthan")
    assert bot.store.get(phone).profile.state == "Rajasthan"
    assert any("Updated" in m for m in out)


def test_correction_without_llm_still_works_for_states():
    """The common correction — a different state — must not need a model."""
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=None)
    phone = "+919000000003"
    bot.handle(phone, "hi")
    bot.handle(phone, "Assam")
    bot.handle(phone, "sorry I meant Kerala")
    assert bot.store.get(phone).profile.state == "Kerala"


# ------------------------------------------------------------------ voice

class _VoiceLLM:
    """Stand-in for a provider, so voice logic is testable without audio."""
    available = True

    def __init__(self, text="I am in class 10", confident=True, lang="en"):
        from llm import Transcript
        self._t = Transcript(text=text, language=lang, confident=confident)

    def transcribe(self, audio, mime="audio/ogg"):
        return self._t

    def extract_profile(self, text):
        return None

    def translate(self, text, language):
        return text


def test_confident_voice_note_is_acted_on_directly():
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(),
              llm=_VoiceLLM(text="Assam"))
    phone = "+919100000001"
    bot.handle(phone, "hi")
    out = bot.handle_voice(phone, b"fake-audio")
    assert bot.store.get(phone).profile.state == "Assam"
    assert any("Assam" in m for m in out)


def test_low_confidence_voice_note_asks_before_acting():
    """FR1: repeat the understanding and confirm before matching."""
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(),
              llm=_VoiceLLM(text="Assam", confident=False))
    phone = "+919100000002"
    bot.handle(phone, "hi")
    out = bot.handle_voice(phone, b"fake-audio")
    assert "I heard" in out[0]
    # Nothing was committed to the profile yet.
    assert bot.store.get(phone).profile.state is None

    bot.handle(phone, "yes")
    assert bot.store.get(phone).profile.state == "Assam"


def test_correcting_a_misheard_voice_note_uses_the_correction():
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(),
              llm=_VoiceLLM(text="Assam", confident=False))
    phone = "+919100000003"
    bot.handle(phone, "hi")
    bot.handle_voice(phone, b"fake-audio")
    bot.handle(phone, "Kerala")
    assert bot.store.get(phone).profile.state == "Kerala"


def test_voice_without_llm_asks_for_text():
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=None)
    out = bot.handle_voice("+919100000004", b"fake-audio")
    assert "type" in out[0].lower()


def test_unreadable_voice_note_does_not_crash():
    class Deaf(_VoiceLLM):
        def transcribe(self, audio, mime="audio/ogg"):
            return None
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=Deaf())
    out = bot.handle_voice("+919100000005", b"")
    assert out and "couldn't make out" in out[0].lower()


# ------------------------------------------------------- privacy: hashing

def test_phone_numbers_are_hashed_not_stored_raw():
    """PRD 12.2 — the store must never hold a readable phone number."""
    import os
    from store_firestore import hash_phone
    os.environ["PHONE_HASH_SALT"] = "test-salt"

    phone = "+919812345678"
    h = hash_phone(phone)
    assert phone not in h
    assert "9812345678" not in h
    assert len(h) == 40
    # Stable for the same input, so a returning student keeps their session.
    assert h == hash_phone(phone)


def test_hash_changes_with_the_salt():
    """An unsalted hash of an Indian mobile number is brute-forceable."""
    import os
    from store_firestore import hash_phone
    os.environ["PHONE_HASH_SALT"] = "salt-one"
    a = hash_phone("+919812345678")
    os.environ["PHONE_HASH_SALT"] = "salt-two"
    assert hash_phone("+919812345678") != a
