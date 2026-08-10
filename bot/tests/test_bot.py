"""Bot tests.

The ones that matter most assert the bot never converts "we don't know" into
"yes". Everything else is flow plumbing.
"""

import pathlib
import sys

BOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BOT))

import messages as M          # noqa: E402
from conversation import Step, parse_income, wants_restart  # noqa: E402
from engine import Bot, InMemorySessionStore, _match_state  # noqa: E402
from matching import (Matcher, StudentProfile, Verdict,     # noqa: E402
                      evaluate)


# ------------------------------------------------------------- fixtures

NATIONAL = {
    "id": "a", "name": "National Merit Scholarship", "states": ["all"],
    "education_levels": ["UG"], "categories": ["SC", "ST"],
    "income_ceiling_inr": 250_000, "application_deadline": "2099-12-31",
    "reach_score": 70, "confidence": "high", "status": "active",
    "application_mode": "NSP", "application_url": "https://scholarships.gov.in",
}
STATE_ONLY = {
    "id": "b", "name": "Assam State Scholarship", "states": ["Assam"],
    "education_levels": ["school"], "categories": ["ST"],
    "income_ceiling_inr": 200_000, "application_deadline": "2099-12-31",
    "reach_score": 40, "confidence": "high", "status": "active",
}
NO_INCOME_STATED = {
    "id": "c", "name": "Mystery Scholarship", "states": ["all"],
    "education_levels": ["UG"], "categories": ["SC"],
    "income_ceiling_inr": None, "application_deadline": "2099-12-31",
    "reach_score": 50, "confidence": "medium", "status": "active",
}
EXPIRED = {
    "id": "d", "name": "Closed Scholarship", "states": ["all"],
    "education_levels": ["UG"], "categories": ["SC"],
    "income_ceiling_inr": 250_000, "application_deadline": "2020-01-01",
    "reach_score": 90, "confidence": "high", "status": "expired",
}

ALL = [NATIONAL, STATE_ONLY, NO_INCOME_STATED, EXPIRED]


def make_bot(records=None) -> Bot:
    return Bot(Matcher(records or ALL), store=InMemorySessionStore())


# ------------------------------------------- the safety-critical behaviour

def test_unstated_income_is_unknown_not_eligible():
    """The whole point: a missing income ceiling must never read as 'you qualify'."""
    p = StudentProfile(state="Bihar", education_level="UG", category="SC",
                       family_income_inr=5_000_000)   # far above any real cap
    r = evaluate(NO_INCOME_STATED, p)
    assert r.verdict is Verdict.UNKNOWN
    assert any(c.name == "income" and c.verdict is Verdict.UNKNOWN
               for c in r.criteria)


def test_income_over_stated_ceiling_is_not_eligible():
    p = StudentProfile(state="Bihar", education_level="UG", category="SC",
                       family_income_inr=900_000)
    assert evaluate(NATIONAL, p).verdict is Verdict.NOT_ELIGIBLE


def test_income_under_ceiling_is_eligible():
    p = StudentProfile(state="Bihar", education_level="UG", category="SC",
                       family_income_inr=100_000)
    assert evaluate(NATIONAL, p).verdict is Verdict.ELIGIBLE


def test_wrong_state_is_excluded_entirely():
    p = StudentProfile(state="Kerala", education_level="school", category="ST",
                       family_income_inr=100_000)
    assert evaluate(STATE_ONLY, p).verdict is Verdict.NOT_ELIGIBLE
    assert all(r.scholarship["id"] != "b"
               for r in Matcher(ALL).match(p))


def test_national_scheme_matches_every_state():
    for state in ("Kerala", "Bihar", "Assam"):
        p = StudentProfile(state=state, education_level="UG", category="ST",
                           family_income_inr=100_000)
        assert evaluate(NATIONAL, p).verdict is Verdict.ELIGIBLE


def test_unknown_never_disqualifies():
    """Student gave no income; the scheme has a cap. Still shown, flagged."""
    p = StudentProfile(state="Bihar", education_level="UG", category="SC")
    r = evaluate(NATIONAL, p)
    assert r.verdict is Verdict.UNKNOWN
    assert r.unknowns


def test_expired_scholarships_are_not_offered():
    p = StudentProfile(state="Bihar", education_level="UG", category="SC",
                       family_income_inr=100_000)
    assert all(r.scholarship["id"] != "d" for r in Matcher(ALL).match(p))


def test_eligible_outranks_unknown():
    p = StudentProfile(state="Bihar", education_level="UG", category="SC",
                       family_income_inr=100_000)
    results = Matcher(ALL).match(p)
    assert results[0].verdict is Verdict.ELIGIBLE


# ----------------------------------------------------------- input parsing

def test_income_parsing_accepts_how_people_actually_type():
    assert parse_income("2 lakh") == 200_000
    assert parse_income("250000") == 250_000
    assert parse_income("2,50,000") == 250_000
    assert parse_income("50k") == 50_000
    assert parse_income("1.5 lakh") == 150_000
    assert parse_income("Rs 3 lakh") == 300_000
    assert parse_income("2") == 200_000          # bare small number means lakhs
    assert parse_income("skip") is None
    assert parse_income("don't know") is None


def test_state_matching_handles_short_forms_and_cities():
    assert _match_state("up") == "Uttar Pradesh"
    assert _match_state("TN") == "Tamil Nadu"
    assert _match_state("bihar") == "Bihar"
    assert _match_state("mumbai") == "Maharashtra"
    assert _match_state("orissa") == "Odisha"
    assert _match_state("zzzz") is None


def test_restart_words():
    for w in ("hi", "restart", "Hello", "menu", "namaste"):
        assert wants_restart(w)


# ---------------------------------------------------------------- the flow

def test_full_conversation_reaches_results():
    bot = make_bot()
    phone = "+911111111111"
    assert "Khoji" in bot.handle(phone, "hi")[0]
    assert "Farheen" in bot.handle(phone, "Farheen")[0]
    assert "Assam" in bot.handle(phone, "Assam")[0]
    bot.handle(phone, "1")            # school
    bot.handle(phone, "10")           # class 10
    bot.handle(phone, "2")            # ST
    bot.handle(phone, "1 lakh")
    out = bot.handle(phone, "4")[0]      # aspiration: not sure yet
    assert "Assam State Scholarship" in out


def test_detail_view_shows_official_url_and_caveats():
    bot = make_bot()
    phone = "+912222222222"
    for msg in ("hi", "Bihar", "4", "1", "skip", "4"):
        bot.handle(phone, msg)
    detail = bot.handle(phone, "1")[0]
    assert "Why this matches you" in detail
    # Income was skipped, so the bot must say the check is outstanding.
    assert "confirm on the official page" in detail.lower()


def test_invalid_input_reprompts_without_advancing():
    bot = make_bot()
    phone = "+913333333333"
    bot.handle(phone, "hi")
    bot.handle(phone, "Farheen")
    before = bot.store.get(phone).step
    assert before is Step.STATE
    bot.handle(phone, "not a state at all")
    assert bot.store.get(phone).step == before


def test_help_does_not_lose_place():
    bot = make_bot()
    phone = "+914444444444"
    bot.handle(phone, "hi")
    bot.handle(phone, "Bihar")
    step = bot.store.get(phone).step
    bot.handle(phone, "help")
    assert bot.store.get(phone).step == step


def test_handler_never_raises_on_garbage():
    bot = make_bot()
    for junk in ("", "😀😀😀", "*" * 5000, "'; DROP TABLE--", "\x00\x01"):
        assert bot.handle("+915555555555", junk)


def test_no_results_message_offers_a_way_forward():
    bot = Bot(Matcher([]), store=InMemorySessionStore())
    phone = "+916666666666"
    for msg in ("hi", "Bihar", "4", "1", "skip", "4"):
        out = bot.handle(phone, msg)
    # Skipping income now prefixes a reassurance before the results message,
    # so the pointer can be in any of the replies.
    assert any("scholarships.gov.in" in m for m in out)


# ------------------------------------------------------------- formatting

def test_messages_fit_whatsapp_limit():
    p = StudentProfile(state="Bihar", education_level="UG", category="SC")
    results = Matcher(ALL).match(p)
    assert len(M.results_summary(results, [])) <= M.MAX_WHATSAPP_CHARS
    assert len(M.scholarship_detail(results[0])) <= M.MAX_WHATSAPP_CHARS


def test_tentative_deadline_is_never_shown_as_firm():
    s = dict(NATIONAL, application_deadline="2099-05-01",
             deadline_is_tentative=True)
    p = StudentProfile(state="Bihar", education_level="UG", category="SC",
                       family_income_inr=100_000)
    assert "tentative" in M.scholarship_detail(evaluate(s, p)).lower()


def test_missing_deadline_is_stated_not_hidden():
    s = dict(NATIONAL, application_deadline=None)
    p = StudentProfile(state="Bihar", education_level="UG", category="SC",
                       family_income_inr=100_000)
    assert "not announced" in M.scholarship_detail(evaluate(s, p)).lower()


def test_class_criterion_skipped_when_not_applicable():
    """A PhD scheme stating no class range must not warn about class."""
    ug = StudentProfile(state="Bihar", education_level="UG", category="SC",
                        family_income_inr=100_000)
    r = evaluate(NATIONAL, ug)
    assert not any(c.name == "class" for c in r.criteria)
    assert r.verdict is Verdict.ELIGIBLE

    # But a school student on a school scheme with no range still gets asked.
    school_scheme = dict(STATE_ONLY, class_min=None, class_max=None)
    school = StudentProfile(state="Assam", education_level="school",
                            category="ST", family_income_inr=100_000)
    r2 = evaluate(school_scheme, school)
    assert any(c.name == "class" and c.verdict is Verdict.UNKNOWN
               for c in r2.criteria)


def test_absent_category_is_no_restriction_but_absent_income_is_unknown():
    """The asymmetry is deliberate and worth pinning down.

    Schemes that restrict by category say so in their title, so an empty list
    means no restriction. Income ceilings are near-universal, so a missing one
    means we failed to read it — and must never read as "no limit".
    """
    no_cat = dict(NATIONAL, categories=[])
    p = StudentProfile(state="Bihar", education_level="UG", category="OBC",
                       family_income_inr=100_000)
    r = evaluate(no_cat, p)
    assert r.verdict is Verdict.ELIGIBLE
    assert not any(c.name == "category" for c in r.unknowns)

    # NATIONAL is restricted to SC/ST, so use a category it accepts — otherwise
    # this fails on category before income is ever reached.
    sc = StudentProfile(state="Bihar", education_level="UG", category="SC",
                        family_income_inr=100_000)
    no_income = dict(NATIONAL, income_ceiling_inr=None)
    r2 = evaluate(no_income, sc)
    assert r2.verdict is Verdict.UNKNOWN
    assert any(c.name == "income" for c in r2.unknowns)


def test_stated_category_still_excludes():
    """Loosening the empty case must not loosen the stated case."""
    p = StudentProfile(state="Bihar", education_level="UG", category="general",
                       family_income_inr=100_000)
    assert evaluate(NATIONAL, p).verdict is Verdict.NOT_ELIGIBLE


def test_state_specific_scheme_outranks_a_national_one_for_that_state():
    """Relevance beats reach when ranking for one student.

    A Rajasthan-only scheme scores low on national reach but is exactly what a
    Rajasthan student should see first. Before this, 26 Rajasthan schemes never
    surfaced for a Rajasthan student.
    """
    national = dict(NATIONAL, id="nat", name="National Scheme", states=["all"],
                    reach_score=95, categories=[], education_levels=["UG"],
                    income_ceiling_inr=None)
    state = dict(NATIONAL, id="raj", name="Rajasthan Scheme", states=["Rajasthan"],
                 reach_score=20, categories=[], education_levels=["UG"],
                 income_ceiling_inr=None)
    p = StudentProfile(state="Rajasthan", education_level="UG", category="OBC")
    results = Matcher([national, state]).match(p, limit=5)
    assert results[0].scholarship["id"] == "raj"

    # But a student elsewhere must not see it at all.
    other = StudentProfile(state="Kerala", education_level="UG", category="OBC")
    assert all(r.scholarship["id"] != "raj"
               for r in Matcher([national, state]).match(other, limit=5))


def test_home_state_schemes_are_always_represented():
    """A student must see their own state's schemes, even when national ones
    outscore them. Without this a Rajasthan student saw five national schemes
    and none of the 22 available in Rajasthan."""
    national = [dict(NATIONAL, id=f"n{i}", name=f"National {i}", states=["all"],
                     categories=[], education_levels=["UG"], reach_score=90,
                     income_ceiling_inr=None) for i in range(6)]
    # Weaker on paper: level unstated, low reach.
    state = dict(NATIONAL, id="raj", name="Rajasthan Scheme",
                 states=["Rajasthan"], categories=[], education_levels=[],
                 reach_score=15, income_ceiling_inr=None)

    p = StudentProfile(state="Rajasthan", education_level="UG", category="OBC")
    results = Matcher(national + [state]).match(p, limit=5)
    assert any(r.scholarship["id"] == "raj" for r in results), \
        "home-state scheme must appear even though national ones score higher"
    assert len(results) == 5, "reserving a slot must not shrink the result list"


def test_home_state_reservation_never_introduces_ineligible_results():
    """The reserved slot draws only from results that already passed."""
    state_wrong_cat = dict(NATIONAL, id="raj", name="Rajasthan ST Scheme",
                           states=["Rajasthan"], categories=["ST"],
                           education_levels=["UG"])
    national = dict(NATIONAL, id="n1", name="National", states=["all"],
                    categories=[], education_levels=["UG"],
                    income_ceiling_inr=None)
    p = StudentProfile(state="Rajasthan", education_level="UG", category="OBC")
    results = Matcher([state_wrong_cat, national]).match(p, limit=5)
    assert all(r.scholarship["id"] != "raj" for r in results)


def test_empty_session_store_is_not_swapped_for_an_in_memory_one():
    """An object with __len__ returning 0 is falsy in Python.

    `self.store = store or InMemorySessionStore()` therefore discarded a real,
    working Firestore store whenever its collection was empty — and quietly
    started working again after the first conversation.
    """
    class EmptyStore(InMemorySessionStore):
        def __len__(self):
            return 0            # falsy, exactly like a fresh Firestore store

    injected = EmptyStore()
    bot = Bot(Matcher(ALL), store=injected)
    assert bot.store is injected, "an empty store must still be used"

    # And omitting the store entirely still gets the default.
    assert isinstance(Bot(Matcher(ALL)).store, InMemorySessionStore)


# --------------------------------------------- picking a result after storage

class RoundTripStore(InMemorySessionStore):
    """Mimics Firestore: only the fields that store persists survive a message.

    Full MatchResult objects are too heavy to persist, so anything relying on
    them surviving between messages must be caught here.

    The field list is imported from the real store rather than restated. Written
    out by hand it was correct once and quietly wrong afterwards — which is how
    `last_detail_index` reached production, where "more" and "documents" could
    not tell which result they referred to.
    """
    def save(self, s):
        from conversation import Session
        from store_firestore import _CARRIED
        copy = Session(phone=s.phone, step=s.step, profile=s.profile)
        for f in _CARRIED:
            setattr(copy, f, getattr(s, f))
        self._d[s.phone] = copy


def test_the_store_carries_every_session_field():
    """A field added to Session without a decision about persistence is a
    production-only bug: in-memory keeps the whole object, so tests pass and the
    deployed bot forgets."""
    from dataclasses import fields
    from conversation import Session
    from store_firestore import _CARRIED, _NOT_CARRIED
    assert {f.name for f in fields(Session)} == set(_CARRIED) | _NOT_CARRIED


def test_can_pick_a_result_after_the_session_round_trips():
    """The shortlist must survive between messages.

    Without persisted ids the next message rebuilt an empty list and the bot
    replied "Please pick a number between 1 and 0" — then rejected "1".
    """
    bot = Bot(Matcher(ALL), store=RoundTripStore())
    phone = "+919300000001"
    for msg in ("hi", "Farheen", "Assam", "1", "10", "2", "1 lakh", "4"):
        bot.handle(phone, msg)

    assert bot.store.get(phone).last_result_ids, "ids must be persisted"
    detail = bot.handle(phone, "1")[0]
    assert "Why this matches you" in detail, "picking 1 must open the detail view"

    # Which result they were reading has to survive too, or "more" and
    # "documents" ask "which one?" about something they just opened. This passed
    # in memory and failed in production for exactly that reason.
    assert "About this scholarship" in bot.handle(phone, "more")[0]
    assert "Documents you" in bot.handle(phone, "documents")[0]


def test_lost_shortlist_reruns_the_search_instead_of_offering_zero():
    """If the ids are gone too, re-run the search rather than saying '1 and 0'."""
    bot = Bot(Matcher(ALL), store=RoundTripStore())
    phone = "+919300000002"
    for msg in ("hi", "Assam", "1", "10", "2", "1 lakh", "4"):
        bot.handle(phone, msg)
    s = bot.store.get(phone)
    s.last_results, s.last_result_ids = [], []
    bot.store.save(s)

    out = bot.handle(phone, "1")[0]
    assert "between 1 and 0" not in out
    assert "Found" in out or "couldn't find" in out


# ------------------------------------------------------------- result order

def test_results_are_ranked_and_stable_between_calls():
    """An order that changes under the reader looks broken."""
    p = StudentProfile(state="Assam", education_level="school", category="ST",
                       family_income_inr=100_000, class_level=10)
    m = Matcher(ALL)
    runs = [[r.scholarship["id"] for r in m.match(p, limit=5)] for _ in range(3)]
    assert runs[0] == runs[1] == runs[2], "ordering must be deterministic"
    scores = [r.score for r in m.match(p, limit=5)]
    assert scores == sorted(scores, reverse=True), "must be ranked by score"


def test_equal_scores_break_ties_by_soonest_deadline():
    """Among equally good matches the one closing soonest matters most, and a
    scheme with no published deadline is not urgent — it sorts last."""
    base = dict(NATIONAL, categories=[], education_levels=["UG"],
                income_ceiling_inr=None, reach_score=50)
    later = dict(base, id="later", name="Later", application_deadline="2099-12-31")
    sooner = dict(base, id="sooner", name="Sooner", application_deadline="2099-01-31")
    undated = dict(base, id="undated", name="Undated", application_deadline=None)

    p = StudentProfile(state="Bihar", education_level="UG", category="OBC")
    order = [r.scholarship["id"]
             for r in Matcher([undated, later, sooner]).match(p, limit=3)]
    assert order == ["sooner", "later", "undated"], order


def test_summary_explains_its_own_ordering():
    p = StudentProfile(state="Bihar", education_level="UG", category="SC")
    out = M.results_summary(Matcher(ALL).match(p, limit=5), [])
    assert "Best match first" in out


def test_a_question_never_dead_ends_when_the_model_is_unavailable():
    """Rate limits and outages happen. A recognised question must still be
    acknowledged — falling through produced "I couldn't find that state",
    which answers a question the student never asked."""
    class DownLLM:
        available = True
        def extract_profile(self, text): return None
        def translate(self, text, language): return text
        def answer_about(self, q, rec, language="en"): raise RuntimeError("429")

    for llm in (None, DownLLM()):
        bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=llm)
        phone = f"+9194000000{1 if llm is None else 2}"
        bot.handle(phone, "hi")
        out = bot.handle(phone, "what documents do I need?")
        joined = " ".join(out).lower()
        assert "couldn't find that state" not in joined
        assert "good question" in joined


# ------------------------------------------- Hindi without a language model

def test_hindi_conversation_needs_no_model_calls():
    """A Hindi student cost 8 model calls — two conversations on a 20/day quota.
    Pre-translated copy and Devanagari parsing make the standard flow free."""
    class CountingLLM:
        available = True
        def __init__(self): self.n = 0
        def _chat(self, *a, **k): self.n += 1; return "answer"
        def extract_profile(self, t): self.n += 1; return None
        def translate(self, t, l): self.n += 1; return t
        def answer_about(self, *a, **k): self.n += 1; return "..."

    llm = CountingLLM()
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=llm)
    phone = "+919500000001"
    bot.handle(phone, "hi")
    s = bot.store.get(phone); s.language = "hi"; bot.store.save(s)
    for msg in ("असम", "1", "10", "2", "1 लाख"):
        bot.handle(phone, msg)
    assert llm.n == 0, f"Hindi flow should need no model calls, used {llm.n}"


def test_devanagari_state_names_resolve():
    assert _match_state("राजस्थान") == "Rajasthan"
    assert _match_state("उत्तर प्रदेश") == "Uttar Pradesh"
    assert _match_state("मैं बिहार से हूँ") == "Bihar"
    assert _match_state("जयपुर") == "Rajasthan"        # a city implies its state


def test_hindi_income_words_and_digits():
    from conversation import parse_income
    assert parse_income("2 लाख") == 200_000
    assert parse_income("ढाई लाख") == 250_000          # spoken quantity
    assert parse_income("डेढ़ लाख") == 150_000
    assert parse_income("२५०००० रुपये") == 250_000     # Devanagari digits


# ------------------------------- one sentence, everything, no model needed

def test_one_sentence_profile_needs_no_model():
    """The most impressive thing a student can type must not depend on a quota."""
    import extract_rules
    got = extract_rules.extract(
        "I'm an OBC girl in class 12 in Rajasthan, income 2 lakh")
    assert got["state"] == "Rajasthan"
    assert got["category"] == "OBC"
    assert got["gender"] == "female"
    assert got["class_level"] == 12
    assert got["education_level"] == "school"
    assert got["family_income_inr"] == 200_000


def test_one_sentence_profile_in_hindi():
    import extract_rules
    got = extract_rules.extract(
        "मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख")
    assert got["state"] == "Rajasthan"
    assert got["class_level"] == 12
    assert got["category"] == "OBC"
    assert got["family_income_inr"] == 250_000


def test_rules_do_not_mistake_an_award_amount_for_income():
    """"Scholarship of 50000" is not the family's earnings."""
    import extract_rules
    got = extract_rules.extract("Is there a scholarship of 50000 for BSc in Bihar?")
    assert got.get("family_income_inr") is None
    assert got["state"] == "Bihar"
    assert got["education_level"] == "UG"


def test_a_stronger_level_word_beats_an_implied_school_level():
    import extract_rules
    got = extract_rules.extract("passed class 12, now doing BSc in Kerala")
    assert got["education_level"] == "UG"


def test_full_sentence_reaches_results_without_a_model():
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=None)
    phone = "+919600000001"
    bot.handle(phone, "hi")
    out = bot.handle(phone, "I am an ST student in class 10 in Assam, income 1 lakh")
    p = bot.store.get(phone).profile
    assert (p.state, p.category, p.class_level) == ("Assam", "ST", 10)
    # Read out of a sentence rather than answered question by question, so it is
    # read back before anything is matched on it.
    assert any("Just to be sure" in m for m in out)
    out = bot.handle(phone, "yes")
    assert any("Found" in m or "couldn't find" in m for m in out)


def test_devanagari_input_gets_a_hindi_reply_without_a_model():
    """Parsing a student's Hindi correctly and then answering in English is the
    one thing a vernacular-first bot must not do."""
    bot = Bot(Matcher(ALL), store=InMemorySessionStore(), llm=None)
    phone = "+919700000001"
    bot.handle(phone, "hi")
    out = bot.handle(phone, "मैं असम से हूँ")
    assert bot.store.get(phone).language == "hi"
    assert any(any("ऀ" <= ch <= "ॿ" for ch in m) for m in out), \
        "reply should be in Hindi"
