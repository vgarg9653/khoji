"""The bot's brain: turn an inbound message into a reply.

Deliberately free of any WhatsApp specifics — it takes (phone, text) and returns
a list of message strings. That keeps it testable without a network, and lets
the same logic sit behind Twilio, Meta's Cloud API, or the local CLI simulator.

Session storage is an injectable dict-like, so swapping in Redis later touches
nothing else.
"""

from __future__ import annotations

import logging
import re

import copy_hi
import extract_rules
import messages as M
from conversation import (ASPIRATION_EFFECT, ASPIRATIONS, CATEGORIES, LEVELS,
                          STATES, Session, Step, parse_income, parse_name,
                          wants_help, wants_restart, _pick)
from intent import Intent, classify
from matching import Matcher, StudentProfile, Verdict

log = logging.getLogger("bot.engine")


def _redact(phone: str) -> str:
    """Log an identifier, not a contact. A phone number written to Cloud
    Logging is a phone number stored, whatever the database holds."""
    p = (phone or "").strip()
    return f"…{p[-4:]}" if len(p) >= 4 else "…"


class InMemorySessionStore:
    """Fine for one process. Swap for Redis before running more than one worker,
    or students will lose their place mid-conversation."""

    def __init__(self):
        self._d: dict[str, Session] = {}

    def get(self, phone: str) -> Session:
        if phone not in self._d:
            self._d[phone] = Session(phone=phone)
        return self._d[phone]

    def reset(self, phone: str) -> Session:
        self._d[phone] = Session(phone=phone)
        return self._d[phone]

    def save(self, s: Session) -> None:
        self._d[s.phone] = s

    def __len__(self) -> int:
        return len(self._d)


def _match_state(text: str) -> str | None:
    """Resolve free-typed state names: English, short forms, Hindi, or a city.

    Hindi matters here beyond politeness — the question itself is asked in
    Hindi, so a student answering in Hindi is doing exactly what we invited.
    """
    raw = (text or "").strip()
    t = raw.lower()
    if not t:
        return None

    # Devanagari first: exact, then contained (so "मैं राजस्थान से हूँ" works).
    if raw in copy_hi.STATES_HI:
        return copy_hi.STATES_HI[raw]
    for hi_name, canonical in copy_hi.STATES_HI.items():
        if hi_name in raw:
            return canonical
    aliases = {
        "up": "Uttar Pradesh", "mp": "Madhya Pradesh", "ap": "Andhra Pradesh",
        "hp": "Himachal Pradesh", "tn": "Tamil Nadu", "wb": "West Bengal",
        "jk": "Jammu and Kashmir", "j&k": "Jammu and Kashmir",
        "ncr": "Delhi", "new delhi": "Delhi", "bangalore": "Karnataka",
        "bengaluru": "Karnataka", "mumbai": "Maharashtra", "chennai": "Tamil Nadu",
        "kolkata": "West Bengal", "hyderabad": "Telangana",
        "orissa": "Odisha", "pondicherry": "Puducherry",
        "uttaranchal": "Uttarakhand", "chattisgarh": "Chhattisgarh",
    }
    if t in aliases:
        return aliases[t]
    for s in STATES:
        if t == s.lower():
            return s
    hits = [s for s in STATES if t in s.lower() or s.lower().startswith(t)]
    return hits[0] if len(hits) == 1 else None


# Steps that `_skip_current` knows how to move on from. NAME is skippable too,
# but it is deliberately NOT here: its own handler below already treats
# Intent.SKIP as "no name given" and then greets and moves to STATE. Routing it
# through `_skip_current` instead hit that function's fallback, which re-asks
# the current question — so "skip" at a prompt that literally says
# "(Type *skip* if you'd rather not say)" re-asked the name forever.
_SKIPPABLE = {Step.CLASS_LEVEL, Step.CATEGORY, Step.INCOME, Step.ASPIRATION}

# "restart" means it; "hi" does not. `wants_restart` deliberately treats both as
# a reset because for a first-time sender they are the same thing — this splits
# out the half that is unambiguous, so only the greeting half has to ask.
_EXPLICIT_RESTART = re.compile(
    r"^\s*(?:restart|start over|reset|start again|begin again|from start|"
    r"फिर से|दोबारा|शुरू|phir se|dobara|shuru)\s*[.!]?\s*$", re.I)

# Answering the "continue or start fresh?" question. Anything that is not
# clearly a request for a fresh start keeps the existing profile: discarding six
# answered questions is the expensive mistake, re-asking one is the cheap one.
_WANTS_FRESH = re.compile(
    r"^\s*(?:2|new|fresh|new search|start fresh|restart|someone else|"
    r"नया|नई|नई खोज|कोई और|फिर से|naya|nayi|koi aur)\s*[.!]?\s*$", re.I)

_AFFIRMATIVE = re.compile(
    r"^\s*(?:y|yes|yeah|yep|ok|okay|correct|right|sahi|sahi hai|haan|han|ha|"
    r"bilkul|theek|thik|thik hai|"
    r"हाँ|हां|सही|सही है|ठीक|ठीक है|बिल्कुल)\s*[.!]?\s*$", re.I)

# "just show me already" — the signal to stop asking and deliver. Kept separate
# from Intent.RESULTS because that one matches polite requests; this one matches
# people who have run out of patience, and the right response is different: show
# whatever we have, labelled as provisional, rather than one more question.
_ENOUGH = re.compile(
    r"\b(?:bas dikhao|bas batao|jaldi|just show|show me already|"
    r"stop asking|too many questions|skip (?:all|everything)|"
    r"बस दिखाओ|बस बताओ|जल्दी|बहुत सवाल)\b", re.I)

_QUESTION_TEXT = {
    Step.NAME: "What should I call you?",
    Step.STATE: "Which state do you live in?",
    Step.LEVEL: "What are you studying now?",
    Step.CLASS_LEVEL: "Which class are you in?",
    Step.CATEGORY: "Which category do you belong to?",
    Step.INCOME: "What is your family's yearly income?",
}


def _question_for(step) -> str:
    return _QUESTION_TEXT.get(step, "")


class Bot:
    def __init__(self, matcher: Matcher, store=None, results_limit: int = 5,
                 llm=None):
        self.matcher = matcher
        # `store or InMemorySessionStore()` is wrong here. FirestoreSessionStore
        # defines __len__, and any object whose __len__ returns 0 is falsy — so
        # an EMPTY session collection made a perfectly good Firestore store
        # evaluate as False and get silently replaced by an in-memory one.
        # It then "fixed itself" after the first conversation, which is the
        # worst kind of bug: intermittent and invisible in the startup log.
        self.store = store if store is not None else InMemorySessionStore()
        self.results_limit = results_limit
        # Optional. When absent the bot runs the rule-based flow unchanged —
        # Gemini adds language reach, it is not load-bearing.
        self.llm = llm

    @property
    def _llm_on(self) -> bool:
        return bool(self.llm and getattr(self.llm, "available", False))

    def _out(self, session: Session, messages: list[str]) -> list[str]:
        """Render outbound messages in the student's language.

        Pre-translated copy first, model second. Re-translating "which state do
        you live in?" on every conversation is pure waste — measured at 8 model
        calls for one Hindi conversation, which is two conversations a day on a
        20-call quota. Static lookups make the standard flow free.
        """
        if session.language == "en":
            return messages

        out = []
        for m in messages:
            fixed = copy_hi.lookup(m, session.language)
            if fixed is not None:
                out.append(fixed)
            elif self._llm_on:
                out.append(self.llm.translate(m, session.language))
            else:
                out.append(m)          # English beats silence
        return out

    # ------------------------------------------------------------ main entry

    def handle(self, phone: str, text: str) -> list[str]:
        """Return the messages to send back. Never raises: a crash mid-flow
        would strand the student with no way forward."""
        try:
            return self._handle(phone, text)
        except Exception:
            log.exception("handler failed for %s", _redact(phone))
            self.store.reset(phone)
            return ["Sorry, something went wrong on my side. "
                    "Let's start again — type *hi*."]

    def handle_voice(self, phone: str, audio: bytes,
                     mime: str = "audio/ogg") -> list[str]:
        """Voice note in, replies out (PRD FR1).

        When transcription confidence is low we repeat our understanding and ask
        for confirmation before matching, rather than acting on a guess — a
        misheard income figure sends a student to the wrong scholarship.
        """
        session = self.store.get(phone)

        if not self._llm_on:
            return self._out(session, [
                "I can't listen to voice notes just yet — please type your "
                "answer instead."])

        transcript = None
        try:
            transcript = self.llm.transcribe(audio, mime)
        except Exception:
            log.exception("transcription failed for %s", _redact(phone))

        if transcript is None or not transcript.text.strip():
            return self._out(session, [
                "Sorry, I couldn't make out that voice note. Could you type it, "
                "or record it again somewhere quieter?"])

        # Detect from the transcription, exactly as we would from typed text —
        # a voice note in Hindi transcribes to Devanagari, which the script
        # check reads correctly on its own.
        self._absorb_language(session, transcript.text, transcript.language)
        # Anything read out of speech is inference twice over — the model heard
        # it, then parsed it — so the profile gets read back before matching.
        session.profile_inferred = True
        self.store.save(session)

        if not transcript.confident:
            # Don't act on it; confirm first.
            session.pending_transcript = transcript.text
            self.store.save(session)
            return self._out(session, [
                f'I heard: "_{transcript.text}_"\n\n'
                f"Is that right? Reply *yes* to continue, or type the correct "
                f"answer."])

        return self._handle(phone, transcript.text)

    def _handle(self, phone: str, text: str) -> list[str]:
        text = (text or "").strip()
        session = self.store.get(phone)

        # A low-confidence voice note is waiting on confirmation.
        if session.pending_transcript:
            pending = session.pending_transcript
            session.pending_transcript = None
            self.store.save(session)
            if text.strip().lower() in ("yes", "y", "haan", "हाँ", "हां", "ok", "sahi"):
                return self._handle(phone, pending)
            # Anything else is the student correcting us — use their words.

        # Devanagari in, Hindi out. Detected from the script so it works with
        # no model and on the student's very first message.
        # Language is re-decided on EVERY message, from the script and wording
        # of that message alone. People switch mid-conversation — a student
        # starts in English, gets stuck, and writes the hard part in Hindi — and
        # following them costs nothing.
        detected = copy_hi.detect_language(text)
        if detected and detected != session.language:
            session.language = detected
            self.store.save(session)

        # Someone greeted us on top of an existing profile and we asked whether
        # to keep it. Settle that before anything else reads the message.
        if session.pending_restart:
            session.pending_restart = False
            if _WANTS_FRESH.match(text or ""):
                return self._do_restart(phone, session.language)
            self.store.save(session)
            return self._out(session, [
                M.resumed(session.profile.name, session.language),
                _question_for(session.step)])

        # We read a profile back and asked whether it was right. Nothing else
        # happens until that is settled.
        if session.pending_confirm:
            session.pending_confirm = False
            if _AFFIRMATIVE.match(text):
                session.profile_confirmed = True
                self.store.save(session)
                return self._to_results(session)
            fixed = self._apply_correction(session, text)
            if fixed:
                return fixed
            # They said something we could not turn into a change. Rather than
            # asking a third time, take them at their word that it was wrong and
            # go back to the first question it could have been about.
            session.profile.state = None
            session.step = Step.STATE
            self.store.save(session)
            return self._out(session, [
                "Sorry — let's fix that. " + _question_for(Step.STATE)])

        # "more" and "documents" are commands, not conversation, and they are
        # answered before anything gets to interpret them. Sending "documents"
        # to the intent classifier got it read as a *question* and answered by
        # the model from the record — plausible prose instead of the document
        # list, at the cost of a quota call. Literal commands never go near a
        # model.
        if session.step in (Step.RESULTS, Step.DETAIL):
            if not session.last_results and session.last_result_ids:
                session.last_results = self.matcher.rehydrate(
                    session.last_result_ids, session.profile)
            deeper = self._detail_screen(session, text)
            if deeper is not None:
                return deeper

        # What is the student doing? Answering, asking, skipping, correcting?
        # Before this, anything that was not an answer to the current question
        # was rejected as a bad answer — the single biggest source of friction.
        # Short replies during a question are answers ~always. Skipping the
        # model here removes the majority of classification calls, which
        # matters on a rate-limited key and makes the common path instant.
        _short = len(text.split()) <= 2
        what = classify(text,
                        None if (_short and session.step in _QUESTION_TEXT)
                        else (self.llm if self._llm_on else None),
                        _question_for(session.step))

        if what is Intent.HELP or wants_help(text):
            return self._out(session, [M.help_text()])

        if what is Intent.QUESTION:
            answered = self._answer_question(session, text)
            if answered:
                return answered

        if what is Intent.CORRECTION:
            fixed = self._apply_correction(session, text)
            if fixed:
                return fixed

        if what is Intent.SKIP and session.step in _SKIPPABLE:
            return self._skip_current(session)

        # Out of patience, or simply ready. Either way: stop asking.
        if _ENOUGH.search(text) or (what is Intent.RESULTS
                                    and session.profile.known_fields()):
            if not session.profile.known_fields():
                # Nothing to search on yet. Ask the one question that cannot be
                # skipped, and put them on it rather than leaving them where
                # they were.
                session.step = Step.STATE
                self.store.save(session)
                return self._out(session, [_question_for(Step.STATE)])
            session.profile_confirmed = True     # they asked for it directly
            session.step = Step.RESULTS
            self.store.save(session)
            note = ("Showing what I have so far — these may need checking "
                    "against your details.") if not session.profile.state else None
            msgs = ([note] if note else []) + self._show_results(session)
            return self._out(session, msgs)

        # Intent.GREETING is in here, not just `wants_restart`, because that
        # helper is a literal word list: "namaste" was in it and "नमस्ते" was
        # not, so the Devanagari greeting fell through to the slot parser and
        # came back as "I couldn't read that amount" — in a Hindi conversation.
        # The intent layer already recognises greetings in every script we take.
        if (what in (Intent.RESTART, Intent.GREETING) or wants_restart(text)
                or session.step is Step.WELCOME):
            # One phone is one session, and these households share phones. A
            # sibling or parent opening with "hi" was silently wiping a profile
            # someone had just spent six questions building — and "hi" is not a
            # request to start over, it is how people open a chat. So a GREETING
            # on top of real answers asks first; an explicit "restart" still
            # resets immediately, because that one is unambiguous.
            explicit = what is Intent.RESTART or _EXPLICIT_RESTART.match(text or "")
            if (not explicit and session.step not in (Step.WELCOME, Step.NAME)
                    and session.profile.known_fields()):
                session.pending_restart = True
                self.store.save(session)
                return self._out(session, [
                    M.ask_continue_or_restart(session.profile.name,
                                              session.language)])
            return self._do_restart(phone, session.language)

        if session.step is Step.NAME:
            # Plenty of people ignore the question and answer the one they came
            # for — "Bihar", or a whole profile in one sentence. Naming someone
            # "Bihar" and then using it in every later message is a worse
            # failure than not learning their name at all, so anything that
            # reads as an answer is treated as one.
            if what is not Intent.SKIP and (extract_rules.extract(text)
                                            or _match_state(text)):
                session.step = Step.STATE
                self.store.save(session)
                return self._handle(phone, text)

            name = None if what is Intent.SKIP else parse_name(text)
            if name:
                session.profile.name = name
            session.step = Step.STATE
            self.store.save(session)
            return [M.greet_by_name(session.profile.name, session.language)] + \
                self._out(session, [M.ask_state()])

        # Free-form shortcut: if the student typed a sentence rather than an
        # option, let Gemini read whatever they stated and skip those questions.
        if len(text.split()) >= 3 and \
                session.step in (Step.STATE, Step.LEVEL, Step.CATEGORY, Step.INCOME):
            jumped = self._absorb_free_text(session, text)
            if jumped:
                return jumped

        step = session.step

        if step is Step.STATE:
            state = self._understand(session, Step.STATE, text)
            if not state:
                return self._out(session, [M.ask_state_retry(text)])
            session.profile.state = state
            session.step = Step.LEVEL
            self.store.save(session)
            return self._out(session, [f"Got it — *{state}* ✅", M.ask_level(session.language)])

        if step is Step.LEVEL:
            level = self._understand(session, Step.LEVEL, text)
            if not level:
                return self._out(session, [M.invalid_option(Step.LEVEL)])
            session.profile.education_level = level
            # Only school students have a class; asking anyone else wastes a turn.
            if level == "school":
                session.step = Step.CLASS_LEVEL
                self.store.save(session)
                return self._out(session, [M.ask_class_level()])
            session.step = Step.CATEGORY
            self.store.save(session)
            return self._out(session, [M.ask_category(session.language)])

        if step is Step.CLASS_LEVEL:
            if text.lower() not in ("skip", "no", "-"):
                digits = "".join(c for c in text if c.isdigit())
                cls = (int(digits) if digits and 1 <= int(digits) <= 12
                       else self._understand(session, Step.CLASS_LEVEL, text))
                if cls is None:
                    return self._out(session, ["Please reply with a number from *1* to *12*, or type *skip*."])
                session.profile.class_level = cls
            session.step = Step.CATEGORY
            self.store.save(session)
            return self._out(session, [M.ask_category(session.language)])

        if step is Step.CATEGORY:
            cat = self._understand(session, Step.CATEGORY, text)
            if not cat:
                return self._out(session, [M.invalid_option(Step.CATEGORY)])
            session.profile.category = cat
            session.step = Step.INCOME
            self.store.save(session)
            return self._out(session, [M.ask_income(session.language)])

        if step is Step.INCOME:
            if text.lower() in ("skip", "don't know", "dont know", "no", "-"):
                session.profile.family_income_inr = None
            else:
                income = self._understand(session, Step.INCOME, text)
                if income is None:
                    return self._out(session, ["I couldn't read that amount. Try _2 lakh_ or _250000_, or type *skip*."])
                session.profile.family_income_inr = income
            session.step = Step.ASPIRATION
            self.store.save(session)
            return self._out(session, [M.ask_aspiration(session.language)])

        if step is Step.ASPIRATION:
            choice = _pick(text, ASPIRATIONS)
            if choice:
                for f, v in ASPIRATION_EFFECT[choice].items():
                    setattr(session.profile, f, v)
            elif not extract_rules.find_field_of_interest(text):
                # Not one of the options and not a subject they named. This
                # question is optional, so an unreadable answer moves on rather
                # than blocking the results behind it.
                pass
            else:
                session.profile.field_of_interest = \
                    extract_rules.find_field_of_interest(text)
                session.profile.wants_higher_studies = "yes"
            return self._to_results(session)

        if step in (Step.RESULTS, Step.DETAIL):
            # Sessions come back from storage without the heavy result objects,
            # so rebuild them from the stored ids before interpreting a number.
            if not session.last_results and session.last_result_ids:
                session.last_results = self.matcher.rehydrate(
                    session.last_result_ids, session.profile)

            deeper = self._detail_screen(session, text)
            if deeper is not None:
                return deeper

            digits = "".join(c for c in text if c.isdigit())
            if digits:
                idx = int(digits) - 1
                if 0 <= idx < len(session.last_results):
                    session.step = Step.DETAIL
                    session.last_detail_index = idx
                    self.store.save(session)
                    return [M.scholarship_detail(session.last_results[idx],
                                                 session.language)]
                n = len(session.last_results)
                if n == 0:
                    # Nothing to pick from — show the list again rather than
                    # asking for "a number between 1 and 0".
                    session.step = Step.RESULTS
                    self.store.save(session)
                    return self._out(session, self._show_results(session))
                return self._out(session, [f"Please pick a number between 1 and {n}."])
            return self._handle_followup(session, text)

        session.step = Step.STATE
        self.store.save(session)
        return self._out(session, [M.ask_state()])

    # -------------------------------------------------- understanding a slot

    # How to read an answer to each question, without a model. `_pick` alone was
    # the whole implementation, and it failed on "Scheduled Caste" — the words
    # SC is an abbreviation *of* — because it only matched the option label as a
    # substring. A student typing what the acronym stands for is not phrasing
    # anything unusually.
    _SLOT_RULES = {
        Step.STATE: ("state",
                     lambda t: _match_state(t) or extract_rules.find_state(t)),
        Step.LEVEL: ("education_level",
                     lambda t: _pick(t, LEVELS) or extract_rules.find_level(t)),
        Step.CATEGORY: ("category",
                        lambda t: _pick(t, CATEGORIES) or extract_rules.find_category(t)),
        Step.CLASS_LEVEL: ("class_level", lambda t: extract_rules.find_class(t)),
        Step.INCOME: ("family_income_inr",
                      lambda t: extract_rules.find_income(t) or parse_income(t)),
    }

    def _understand(self, session: Session, step, text: str):
        """What did they mean by that? Rules, then the model.

        Three layers, cheapest first. The first two are free and instant and
        handle almost everything. The third exists because "Schedule caste" —
        one letter short of the expansion — should not be a dead end, and the
        model resolves it in about a second.

        The model is a fallback, not a rationing decision. When it is available
        it gets used; when it is not, the first two layers still answer.
        """
        entry = self._SLOT_RULES.get(step)
        if not entry:
            return None
        field, rule = entry
        try:
            got = rule(text)
        except Exception:
            got = None
        if got is not None:
            return got
        if not self._llm_on or not (text or "").strip():
            return None

        extracted = self.llm.extract_profile(text)
        if extracted is None:
            return None
        self._absorb_language(session, text, extracted.language)
        value = getattr(extracted, field, None)
        if value is not None:
            log.info("slot %s resolved by model", field)
            # The model read a whole sentence; keep anything else it found
            # rather than asking for it again in a moment.
            for f in ("state", "education_level", "category", "class_level",
                      "family_income_inr", "gender"):
                if f == field:
                    continue
                v = getattr(extracted, f, None)
                if v is not None and getattr(session.profile, f, None) is None:
                    setattr(session.profile, f, v)
                    session.profile_inferred = True
        return value

    @staticmethod
    def _absorb_language(session: Session, text: str, model_language: str | None):
        """The script the student typed in beats the model's opinion of it.

        The model reads "mai Rajasthan me rehta hun" and reports `hi`, which is
        true about the language and wrong about the reply: answering in
        Devanagari someone who typed in Roman script gives them something they
        have to work to read. Script detection is checked first and wins.
        """
        by_script = copy_hi.detect_language(text)
        if by_script:
            session.language = by_script
        elif model_language and model_language != session.language:
            session.language = model_language

    # ---------------------------------------------------------- corrections

    def _apply_correction(self, session: Session, text: str) -> list[str] | None:
        """"Actually I meant Rajasthan" should change the answer, not be read as
        a new one. Returns None if we cannot tell what they are correcting, so
        the caller falls through rather than guessing."""
        # Strip the correction phrasing and see what is left.
        stripped = re.sub(
            r"\b(?:actually|sorry|i meant|i mean|change (?:my|the)|it'?s|its|"
            r"no i am|no i'?m|not|wrong|mistake|instead|correction|"
            r"maine galat|galat|असल में|गलत|बदलो)\b", " ", text, flags=re.I)
        stripped = re.sub(r"\s+", " ", stripped).strip(" ,.")

        updates = []
        state = _match_state(stripped)
        if state and state != session.profile.state:
            session.profile.state = state
            updates.append(f"state → *{state}*")

        if self._llm_on and not updates:
            got = self.llm.extract_profile(text)
            if got:
                for f in ("state", "education_level", "category",
                          "family_income_inr", "class_level", "gender"):
                    v = getattr(got, f)
                    if v is not None and v != getattr(session.profile, f):
                        setattr(session.profile, f, v)
                        updates.append(f"{f.replace('_',' ')} → *{v}*")

        if not updates:
            return None

        # A changed profile invalidates the shortlist built from the old one.
        session.last_results, session.last_result_ids = [], []
        self.store.save(session)
        ack = "Updated: " + ", ".join(updates) + " ✅"
        if session.step in (Step.RESULTS, Step.DETAIL):
            session.step = Step.RESULTS
            self.store.save(session)
            return self._out(session, [ack] + self._show_results(session))
        return self._out(session, [ack, _question_for(session.step)])

    # ------------------------------------------------------ questions & skips

    def _answer_question(self, session: Session, text: str) -> list[str] | None:
        """Answer a question asked mid-flow, then put the student back where
        they were. Returns None if we have nothing useful to say, so the caller
        falls through to normal handling rather than dead-ending."""
        # If we already have results, answer from the record they are looking at.
        if session.last_results or session.last_result_ids:
            if not session.last_results and session.last_result_ids:
                session.last_results = self.matcher.rehydrate(
                    session.last_result_ids, session.profile)
            if session.last_results:
                return self._handle_followup(session, text)

        if not self._llm_on:
            # Without a model we cannot answer freely, but we can say so and
            # keep going instead of pretending the message was an answer.
            return self._out(session, [
                "Good question — I can answer that once I've found your "
                "scholarships.\n\n" + _question_for(session.step)])

        # No shortlist yet: answer generally, from the catalogue's own shape,
        # then repeat the question we were on.
        answer = None
        try:
            answer = self.llm.answer_about(
                text, {"note": "No specific scholarship selected yet. "
                               "Answer only in general terms about how Indian "
                               "scholarships work, and say that exact details "
                               "depend on the scheme."},
                session.language)
        except Exception:
            log.exception("answer_about failed")

        if not answer:
            # The model may be rate-limited or down. We still KNOW this was a
            # question, so acknowledge it and keep the flow moving. Falling
            # through here used to produce "I couldn't find that state" — an
            # answer to a question the student never asked.
            return self._out(session, [
                "Good question — I'll be able to answer that once I've found "
                "your scholarships.\n\n" + _question_for(session.step)])
        return self._out(session, [answer, _question_for(session.step)])

    def _do_restart(self, phone: str, lang: str) -> list[str]:
        """Wipe and start over. The one place that clears a profile, so there is
        no second route that forgets to preserve the language."""
        session = self.store.reset(phone)
        session.step = Step.NAME
        # A student who opened in Hindi should not be reset to English.
        session.language = lang
        self.store.save(session)
        # The welcome is bilingual on purpose and goes out untranslated; only
        # the question after it is rendered in their language.
        return [M.welcome()] + self._out(session, [M.ask_name()])

    def _skip_current(self, session: Session) -> list[str]:
        """Accept a refusal and move on. Refusing to answer is a legitimate
        choice, especially about family income."""
        step = session.step
        if step is Step.CLASS_LEVEL:
            session.step = Step.CATEGORY
            self.store.save(session)
            return self._out(session, ["No problem.", M.ask_category(session.language)])
        if step is Step.CATEGORY:
            session.step = Step.INCOME
            self.store.save(session)
            return self._out(session, ["That's fine.", M.ask_income(session.language)])
        if step is Step.INCOME:
            session.profile.family_income_inr = None
            session.step = Step.ASPIRATION
            self.store.save(session)
            return self._out(session, [
                "No problem — I'll show you what I have, and you can check "
                "each scheme's income limit on its official page.",
                M.ask_aspiration(session.language)])
        if step is Step.ASPIRATION:
            return self._to_results(session)
        return self._out(session, [_question_for(step)])

    # ------------------------------------------------------- confirm & match

    def _to_results(self, session: Session) -> list[str]:
        """The one place matching is entered from, so the check before it
        cannot be skipped by adding another route later."""
        if session.profile_inferred and not session.profile_confirmed:
            session.pending_confirm = True
            self.store.save(session)
            return [M.confirm_profile(session.profile, session.language)]
        session.step = Step.RESULTS
        self.store.save(session)
        return self._out(session, self._show_results(session))

    # ------------------------------------------------------- deeper screens

    # Deliberately generous, and multilingual in both scripts: a student who
    # types "aur batao" or "कागज़ कौन से" is asking the same thing as one who
    # types "more".
    _WANTS_MORE = re.compile(
        r"^\s*(?:more|tell me more|details?|explain|about|what is (?:this|it)|"
        r"aur|aur batao|zyada|vistaar|"
        r"और|और बताओ|विस्तार|ज़्यादा|ये क्या है|यह क्या है)\s*[?.!]?\s*$", re.I)
    _WANTS_DOCS = re.compile(
        r"(?:^|\b)(?:documents?|docs|papers?|certificates?|what documents|"
        r"kaagaz|kagaz|kaghaz|dastavez|"
        r"कागज़|कागज|दस्तावेज़|दस्तावेज|प्रमाण ?पत्र)(?:\b|$)", re.I)

    def _translator(self, session: Session):
        """A callable that renders catalogue prose in the student's language,
        or None when English is already right or no model is available."""
        if session.language == "en" or not self._llm_on:
            return None
        return lambda t: self.llm.translate(t, session.language)

    def _detail_screen(self, session: Session, text: str) -> list[str] | None:
        """"more" / "documents", applied to whichever result they are reading.

        Returns None when the message is neither, so the caller carries on.
        """
        if not session.last_results:
            return None
        idx = session.last_detail_index
        if idx is None or not (0 <= idx < len(session.last_results)):
            # They asked for depth without picking anything. If there is only
            # one result the intent is obvious; otherwise ask which.
            if len(session.last_results) == 1:
                idx = 0
            elif self._WANTS_MORE.match(text or "") or self._WANTS_DOCS.search(text or ""):
                return self._out(session, [
                    f"Which one? Reply with a number from 1 to "
                    f"{len(session.last_results)}."])
            else:
                return None

        r = session.last_results[idx]
        if self._WANTS_DOCS.search(text or ""):
            session.step = Step.DETAIL
            self.store.save(session)
            return [M.scholarship_documents(r, session.language,
                                            self._translator(session))]
        if self._WANTS_MORE.match(text or ""):
            session.step = Step.DETAIL
            self.store.save(session)
            return [M.scholarship_more(r, session.language,
                                       self._translator(session))]
        return None

    # ---------------------------------------------------------- follow-ups

    def _handle_followup(self, session: Session, text: str) -> list[str]:
        """A question typed at the results screen, e.g. "what documents do I
        need for the second one?".

        Answered strictly from the scholarship record — see llm.ANSWER_SYSTEM.
        Without Gemini we say what the bot can do instead of guessing.
        """
        fallback = ["Reply with a result *number* for details, "
                    "or type *restart* to search again."]
        if not self._llm_on or not session.last_results:
            return self._out(session, fallback)

        # Default to the top result unless the student named another.
        record = session.last_results[0].scholarship
        for i, r in enumerate(session.last_results, 1):
            if f"{i}" in text or (r.scholarship.get("name") or "").lower()[:20] in text.lower():
                record = r.scholarship
                break

        answer = self.llm.answer_about(text, record, session.language)
        if not answer:
            return self._out(session, fallback)
        return [answer + "\n\n_Please confirm on the official page before applying._"]

    # ------------------------------------------------------- free-form input

    def _absorb_free_text(self, session: Session, text: str) -> list[str] | None:
        """Take everything the student volunteered in one sentence.

        "I'm an SC student in class 10 from Bihar, family income 1 lakh" should
        answer four questions at once. Returns the next prompt if anything was
        absorbed, or None to let the normal step handler run.
        """
        # Rules first. The most impressive thing a student can type — a single
        # sentence containing everything — should not depend on a quota, a
        # network round-trip, or a provider being up.
        facts = extract_rules.extract(text)
        extracted = None
        if not facts and self._llm_on:
            extracted = self.llm.extract_profile(text)
            if extracted is None:
                return None
            for f in ("state", "education_level", "category",
                      "family_income_inr", "class_level", "gender"):
                v = getattr(extracted, f, None)
                if v is not None:
                    facts[f] = v
            self._absorb_language(session, text, extracted.language)
        if not facts:
            return None

        p = session.profile
        got = []
        for field, value in facts.items():
            if value is not None and getattr(p, field, None) is None:
                setattr(p, field, value)
                got.append(field)

        if not got:
            self.store.save(session)
            return None

        # These fields were read out of a sentence, not answered one by one, so
        # they get read back before anything is matched on them.
        session.profile_inferred = True

        # Jump to the first question still unanswered.
        if p.state is None:
            session.step = Step.STATE
            nxt = M.ask_state()
        elif p.education_level is None:
            session.step = Step.LEVEL
            nxt = M.ask_level(session.language)
        elif p.education_level == "school" and p.class_level is None:
            session.step = Step.CLASS_LEVEL
            nxt = M.ask_class_level()
        elif p.category is None:
            session.step = Step.CATEGORY
            nxt = M.ask_category(session.language)
        elif p.family_income_inr is None and session.step is not Step.RESULTS:
            session.step = Step.INCOME
            nxt = M.ask_income(session.language)
        else:
            # Deliberately no aspiration question here. Someone who typed their
            # whole situation in one sentence has told us they want an answer,
            # not another form field; the optional question belongs to the
            # guided flow, where it costs a turn nobody was rushing through.
            self.store.save(session)
            return self._to_results(session)

        self.store.save(session)
        ack = "Got it — " + ", ".join(
            f"*{getattr(p, f)}*" for f in got if getattr(p, f) is not None) + " ✅"
        return self._out(session, [ack, nxt])

    # --------------------------------------------------------------- results

    def _show_results(self, session: Session) -> list[str]:
        results = self.matcher.match(session.profile, limit=self.results_limit)
        session.last_results = results
        # Ids persist; the objects do not. Without this the student's next
        # message rebuilds an empty shortlist and "1" is rejected as out of range.
        session.last_result_ids = [r.scholarship.get("id") for r in results
                                   if r.scholarship.get("id")]
        self.store.save(session)
        if not results:
            return [M.no_results()]
        return [M.results_summary(results, session.profile.known_fields(), session.language)]
