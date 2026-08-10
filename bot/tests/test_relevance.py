"""Relevance, aspiration, and the conversation changes that came with them.

Eligibility asks whether a student *can* apply. These tests are about the second
question — whether it is worth their one screen of attention — and about the
places the bot now asks before assuming.
"""

import json
import pathlib
import sys

BOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT))
sys.path.insert(0, str(BOT.parent / "src"))

import copy_hi                                  # noqa: E402
import extract_rules                            # noqa: E402
import relevance                                # noqa: E402
from conversation import Step, parse_name       # noqa: E402
from engine import Bot, InMemorySessionStore    # noqa: E402
from matching import Matcher, StudentProfile    # noqa: E402


def _rec(**kw):
    base = {
        "id": "x", "name": "Test Scholarship", "states": ["all"],
        "education_levels": ["UG"], "categories": [], "income_ceiling_inr": None,
        "application_deadline": "2099-12-31", "reach_score": 50,
        "confidence": "high", "status": "active",
    }
    base.update(kw)
    base.update(relevance.tag(base))
    return base


# ------------------------------------------------------------ scheme tagging

def test_class_range_becomes_a_school_band():
    r = _rec(education_levels=["school"], class_min=9, class_max=10)
    assert r["applicable_stages"] == ["school_secondary"]


def test_school_with_no_class_range_covers_all_of_school():
    r = _rec(education_levels=["school"])
    assert r["applicable_stages"] == ["school_primary", "school_secondary",
                                      "school_senior"]


def test_coaching_is_detected_and_targeted():
    r = _rec(name="Free Coaching for NEET and JEE aspirants")
    assert r["scheme_kind"] == "coaching"
    assert r["coaching_target"] == "entrance_after_school"

    r = _rec(name="Coaching scheme for UPSC civil services candidates")
    assert r["coaching_target"] == "competitive_services"


def test_generic_coaching_gets_no_target_and_is_never_suppressed():
    """Guessing which exam a scheme funds is the same class of invention this
    project refuses everywhere else, so an untargeted scheme stays visible."""
    r = _rec(name="Free Coaching For SC and OBC Students")
    assert r["coaching_target"] is None
    for stage in ("school_secondary", "UG", "PG"):
        assert relevance.bucket(r, stage)[0] == relevance.NOW


# ---------------------------------------------------------------- bucketing

def test_school_scheme_is_suppressed_for_a_degree_student():
    r = _rec(education_levels=["school"], class_min=9, class_max=10)
    verdict, why = relevance.bucket(r, "UG")
    assert verdict == relevance.SUPPRESS
    assert "earlier stage" in why


def test_one_step_ahead_is_aspirational_not_hidden():
    r = _rec(education_levels=["PG"])
    verdict, why = relevance.bucket(r, "UG")
    assert verdict == relevance.LATER
    assert "after your degree" in why


def test_two_steps_ahead_is_not_a_realistic_next_step():
    r = _rec(education_levels=["PhD"])
    assert relevance.bucket(r, "UG")[0] == relevance.SUPPRESS


def test_missing_level_never_suppresses():
    """The source not stating a level is a gap in the source, not a signal."""
    r = _rec(education_levels=[])
    assert r["applicable_stages"] == []
    assert relevance.bucket(r, "UG")[0] == relevance.NOW


def test_unknown_student_stage_never_suppresses():
    r = _rec(education_levels=["PhD"])
    assert relevance.bucket(r, None)[0] == relevance.NOW


def test_entrance_coaching_is_suppressed_once_the_exam_is_behind_them():
    r = _rec(name="NEET coaching support", education_levels=["school"])
    assert relevance.bucket(r, "school_senior")[0] == relevance.NOW
    assert relevance.bucket(r, "UG")[0] == relevance.SUPPRESS


def test_saying_unsure_holds_back_plan_ahead_results():
    r = _rec(education_levels=["PG"])
    assert relevance.bucket(r, "UG")[0] == relevance.LATER
    assert relevance.bucket(r, "UG",
                            wants_higher_studies="unsure")[0] == relevance.SUPPRESS
    assert relevance.bucket(r, "UG",
                            wants_higher_studies="no")[0] == relevance.SUPPRESS


def test_stream_specific_scheme_is_suppressed_for_another_stream():
    r = _rec(name="Scholarship for engineering students", education_levels=["UG"])
    assert r["stream_tags"] == ["engineering"]
    assert relevance.bucket(r, "UG", field_of_interest="engineering")[0] == relevance.NOW
    assert relevance.bucket(r, "UG", field_of_interest="medical")[0] == relevance.SUPPRESS
    # No stated interest means no filtering — we do not invent one.
    assert relevance.bucket(r, "UG")[0] == relevance.NOW


# ------------------------------------------------------------- the matcher

SCHOOL_9_10 = _rec(id="s", name="Pre-Matric Scheme", education_levels=["school"],
                   class_min=9, class_max=10, reach_score=90)
UG_SCHEME = _rec(id="u", name="College Scholarship", education_levels=["UG"],
                 reach_score=80)
PG_SCHEME = _rec(id="p", name="Masters Fellowship", education_levels=["PG"],
                 reach_score=70)
CATALOGUE = [SCHOOL_9_10, UG_SCHEME, PG_SCHEME]


def test_matcher_labels_buckets_and_hides_the_rest():
    m = Matcher(CATALOGUE)
    got = m.match(StudentProfile(state="Bihar", education_level="UG"), limit=5)
    by_id = {r.scholarship["id"]: r.relevance for r in got}
    assert by_id["u"] == "now"
    assert by_id["p"] == "later"      # one step ahead, surfaced as plan-ahead
    assert "s" not in by_id           # school scheme, behind them, hidden


def test_plan_ahead_survives_the_eligibility_filter():
    """A Class 12 student fails a UG scheme on exactly one criterion — the level
    they have not reached. Dropping it there is why "plan ahead" was empty for
    everyone before this."""
    m = Matcher(CATALOGUE)
    got = m.match(StudentProfile(state="Bihar", education_level="school",
                                 class_level=12), limit=5)
    later = [r for r in got if r.relevance == "later"]
    assert [r.scholarship["id"] for r in later] == ["u"]


def test_nothing_relevant_still_shows_something():
    """Suppressing everything the student was eligible for would leave a blank
    screen, which is worse than an honestly labelled near-miss."""
    m = Matcher([SCHOOL_9_10])
    got = m.match(StudentProfile(state="Bihar", education_level="PhD"), limit=5)
    assert got and all(r.relevance == "suppress" for r in got)


# --------------------------------------------------------------- the flow

DATA = pathlib.Path(__file__).resolve().parents[2] / "deliverables" / "dataset" / "bot_matching.json"


def make_bot():
    return Bot(Matcher(CATALOGUE), store=InMemorySessionStore())


def test_a_state_is_not_a_name():
    """Answering the name question with "Bihar" and being called Bihar for the
    rest of the conversation is worse than never learning the name."""
    b = make_bot()
    b.handle("+91n1", "hi")
    b.handle("+91n1", "Bihar")
    s = b.store.get("+91n1")
    assert s.profile.name is None
    assert s.profile.state == "Bihar"


def test_name_is_read_out_of_a_sentence():
    assert parse_name("mera naam Farheen hai") == "Farheen"
    assert parse_name("my name is Rahul") == "Rahul"
    assert parse_name("Farheen") == "Farheen"
    assert parse_name("+919876543210") is None
    assert parse_name("I don't really want to tell you my name today") is None


def test_language_is_detected_from_wording_never_from_the_name():
    assert copy_hi.detect_language("मैं राजस्थान से हूँ") == "hi"
    assert copy_hi.detect_language("mai Rajasthan me rehta hun") == "hinglish"
    assert copy_hi.detect_language("I live in Rajasthan") == "en"
    # A bare name says nothing about language, and must not flip it.
    assert copy_hi.detect_language("Farheen") is None
    assert copy_hi.detect_language("Rahul Sharma") is None


def test_language_follows_a_switch_mid_conversation():
    b = make_bot()
    b.handle("+91n2", "hi")
    b.handle("+91n2", "skip")
    b.handle("+91n2", "I live in Bihar")
    assert b.store.get("+91n2").language == "en"
    b.handle("+91n2", "mujhe kya karna hoga")
    assert b.store.get("+91n2").language == "hinglish"


def test_inferred_profile_is_read_back_before_matching():
    b = make_bot()
    b.handle("+91n3", "hi")
    out = b.handle("+91n3", "I am an SC student in class 10 from Bihar, income 1 lakh")
    assert any("Just to be sure" in m for m in out)
    assert b.store.get("+91n3").step is not Step.RESULTS
    out = b.handle("+91n3", "yes")
    assert b.store.get("+91n3").step is Step.RESULTS


def test_answering_one_question_at_a_time_is_never_read_back():
    """Repeating answers someone typed themselves is condescending, so the
    confirmation fires only for inference."""
    b = make_bot()
    for msg in ("hi", "Farheen", "Bihar", "4", "8", "skip", "4"):
        out = b.handle("+91n4", msg)
    assert not any("Just to be sure" in m for m in out)


def test_running_out_of_patience_shows_results_immediately():
    b = make_bot()
    b.handle("+91n5", "hi")
    b.handle("+91n5", "Bihar")
    out = b.handle("+91n5", "bas dikhao")
    assert b.store.get("+91n5").step is Step.RESULTS
    assert not any("category" in m.lower() and "1." in m for m in out[:1])


def test_income_stated_in_roman_hindi_is_read():
    """"ghar ki aay 2 lakh" parsed perfectly except for the one number that
    decides eligibility, then asked for it again."""
    got = extract_rules.extract("mai Rajasthan me rehta hun, class 12, OBC, "
                                "ghar ki aay 2 lakh")
    assert got["family_income_inr"] == 200_000
    assert extract_rules.extract("ghar ki aamdani 250000 hai")[
        "family_income_inr"] == 250_000


def test_a_scholarship_amount_is_not_read_as_income():
    assert "family_income_inr" not in extract_rules.extract(
        "scholarship amount 50000 milta hai")


def test_more_and_documents_never_reach_the_model():
    """Found live: with a model attached, "documents" was classified as a
    QUESTION and answered in prose from the record — a quota call spent to
    produce something worse than the list we already had. Literal commands are
    resolved by rules, before anything gets to interpret them."""
    import intent

    class LoudLLM:
        available = True
        calls = 0

        def _chat(self, *a, **k):
            LoudLLM.calls += 1
            return "question"

        def translate(self, t, lang):
            return t

        def answer_about(self, *a, **k):
            LoudLLM.calls += 1
            return "some prose the model made up"

    assert intent.classify_rule_based("more") is intent.Intent.DEEPER
    assert intent.classify_rule_based("documents") is intent.Intent.DEEPER

    b = Bot(Matcher(CATALOGUE), store=InMemorySessionStore(), llm=LoudLLM())
    for msg in ("hi", "Farheen", "Bihar", "4", "skip", "skip", "4"):
        b.handle("+91n6", msg)
    assert b.store.get("+91n6").step is Step.RESULTS
    b.handle("+91n6", "1")
    before = LoudLLM.calls
    assert "About this scholarship" in b.handle("+91n6", "more")[0]
    assert "Documents you" in b.handle("+91n6", "documents")[0]
    assert LoudLLM.calls == before, "a literal command consulted the model"


# ------------------------------------------------- understanding an answer

def test_the_words_an_acronym_stands_for_are_understood():
    """Reported live: typing "Schedule caste" at the category question was not
    understood, because the option label is "SC" and matching was substring
    only. A student typing what the abbreviation abbreviates is not phrasing
    anything unusually — and this must work with no model at all."""
    b = Bot(Matcher(CATALOGUE), store=InMemorySessionStore(), llm=None)
    for msg in ("hi", "Farheen", "Bihar", "1", "10"):
        b.handle("+91c1", msg)
    b.handle("+91c1", "Schedule caste")
    assert b.store.get("+91c1").profile.category == "SC"

    for phrase, want in (("Scheduled Caste", "SC"), ("dalit", "SC"),
                         ("anusuchit jati", "SC"), ("scheduled tribe", "ST"),
                         ("pichhda varg", "OBC"), ("divyang", "PwD"),
                         ("alpsankhyak", "minority"), ("none of these", "general")):
        assert extract_rules.find_category(phrase) == want, phrase


def test_a_degree_is_not_a_caste():
    """"I joined B.Sc last year" was read as category SC — the dot in "B.Sc" is
    a word boundary. Same shape as the "Assam Rifles" bug, and it would have
    shown SC-only schemes to a general-category student."""
    for text in ("I joined B.Sc last year", "doing M.Sc physics",
                 "B.Sc. Nursing", "St. Xavier College", "21st August"):
        assert extract_rules.find_category(text) is None, text
    # …without breaking the cases that must still work.
    for text, want in (("I am SC", "SC"), ("SC category", "SC"),
                       ("ST student", "ST"), ("sc", "SC")):
        assert extract_rules.find_category(text) == want, text


def test_a_class_number_is_dropped_once_they_are_past_school():
    """"I finished 12th and joined B.Sc" states a class and a level, and only
    one is where they are now."""
    got = extract_rules.extract("I finished 12th and joined B.Sc last year")
    assert got["education_level"] == "UG"
    assert "class_level" not in got
    assert extract_rules.extract("I am in class 10")["class_level"] == 10


def test_free_typed_levels_are_understood_without_a_model():
    for text, want in (("B.Tech", "UG"), ("bachelors", "UG"),
                       ("graduation", "UG"), ("intermediate", "school"),
                       ("polytechnic", "diploma"), ("MBBS", "professional"),
                       ("masters", "PG"), ("I am in college", "UG")):
        assert extract_rules.find_level(text) == want, text


def test_the_model_is_a_fallback_not_the_first_resort():
    """Rules answer the common cases for free; the model exists for the ones
    they genuinely cannot reach. It must not be consulted when they can."""
    class CountingLLM:
        available = True
        calls = 0

        def extract_profile(self, text):
            CountingLLM.calls += 1
            return None

        def translate(self, t, lang):
            return t

    b = Bot(Matcher(CATALOGUE), store=InMemorySessionStore(), llm=CountingLLM())
    for msg in ("hi", "Farheen", "Rajasthan", "graduation", "Scheduled Caste",
                "2 lakh", "4"):
        b.handle("+91c2", msg)
    p = b.store.get("+91c2").profile
    assert (p.state, p.education_level, p.category, p.family_income_inr) == \
        ("Rajasthan", "UG", "SC", 200_000)
    assert CountingLLM.calls == 0, "rules could answer; the model was called anyway"


def test_the_script_they_typed_in_beats_the_models_opinion():
    """The model reads "mai Rajasthan me rehta hun" and reports `hi`, which is
    true about the language and wrong about the reply — answering in Devanagari
    gives a Roman-script writer something they have to work to read."""
    class HindiClaimingLLM:
        available = True

        def extract_profile(self, text):
            class E:
                state = "Rajasthan"
                education_level = category = None
                family_income_inr = class_level = gender = None
                language = "hi"
            return E()

        def translate(self, t, lang):
            return t

    b = Bot(Matcher(CATALOGUE), store=InMemorySessionStore(), llm=HindiClaimingLLM())
    b.handle("+91c3", "hi")
    b.handle("+91c3", "skip")
    b.handle("+91c3", "mai wahan rehta hun jahan mera ghar hai")
    assert b.store.get("+91c3").language == "hinglish"


# ---------------------------------------------------------- model routing

def test_a_429_falls_through_to_a_different_quota_bucket():
    """A free-tier limit is per model, not per key. The bot was found live with
    its only model exhausted and three others idle on the same key."""
    import models
    chain = models.chain(models.ROUTER)
    assert len(chain) >= 2, "no fallback model configured"
    assert chain[0] != chain[1], "a fallback sharing a bucket is just a retry"
    assert models.should_try_next(Exception("429 RESOURCE_EXHAUSTED quota"))
    assert models.should_try_next(Exception("404 NOT_FOUND model not available"))
    # A prompt the model refuses will be refused by every model; retrying only
    # spends time the student is waiting through.
    assert not models.should_try_next(Exception("400 INVALID_ARGUMENT"))


# ------------------------------------------------------- the shipped dataset

def test_every_served_record_carries_its_content_and_tags():
    if not DATA.exists():
        return                        # dataset not built in this checkout
    records = json.loads(DATA.read_text(encoding="utf-8"))
    assert records
    for r in records:
        for f in ("what_it_is", "who_its_for", "how_it_helps", "renewal_note",
                  "content_status"):
            assert r.get(f), f"{r.get('id')} missing {f}"
        assert isinstance(r.get("eligibility_explained"), list)
        assert isinstance(r.get("documents_explained"), list)
        assert r.get("scheme_kind") in ("study", "coaching", "research")
        assert isinstance(r.get("applicable_stages"), list)


def test_content_never_claims_an_income_limit_that_is_not_in_the_data():
    if not DATA.exists():
        return
    records = json.loads(DATA.read_text(encoding="utf-8"))
    for r in records:
        if r.get("income_ceiling_inr") is None:
            assert "does not publish an income limit" in r["who_its_for"], \
                f"{r.get('id')} invented an income limit"


def test_pdf_fragments_are_never_rendered_as_an_amount():
    """Found in the live demo: a record whose amount line read
    "💰 Amount: 6. INSTITUITIONS ELIGIBLE AND QUANTUM OF ASSISTANCE '\\.) Q The
    designated portal shall allow updating of the i…" — a heading and a clause
    fragment under a rupee sign. 29 records were doing some version of it, and a
    student cannot tell extraction noise from a real condition."""
    import messages as M
    junk = ("6. INSTITUITIONS ELIGIBLE AND QUANTUM OF ASSISTANCE '\\.) Q The "
            "designated portal shall allow updating of the i")
    assert M._amount_line({"benefit_amount_text": junk}) is None
    assert M._amount_line({"benefit_amount_text":
                           "scholarship/financial assistance/paid as signment"}) is None
    # A real figure still shows.
    line = M._amount_line({"benefit_amount_text": "Rs. 50,000/- per annum"})
    assert line and "50,000" in line
    # And nothing in the shipped dataset gets past it.
    if DATA.exists():
        for r in json.loads(DATA.read_text(encoding="utf-8")):
            t = r.get("benefit_amount_text")
            if t:
                assert M._amount_line({"benefit_amount_text": t}), \
                    f"{r.get('id')} has unusable amount text: {t[:60]}"
