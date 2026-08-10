"""Message rendering for WhatsApp.

Constraints that shape everything here:
  * WhatsApp formatting is *bold*, _italic_, ```mono``` — no tables, no links
    with anchor text. A bare URL is the only clickable thing.
  * Many users read on a small screen over a slow connection, so messages stay
    short and put the actionable part first.
  * Anything the dataset does not know is said out loud. A scholarship shown
    without a confirmed income limit must say so, every time — the student is
    the one who bears the cost of a wrong guess.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import copy_hinglish
from conversation import ASPIRATIONS, CATEGORIES, LEVELS, STATES, Step
from matching import MatchResult, Verdict

MAX_WHATSAPP_CHARS = 4096

# An actual figure of money, however these PDFs write it.
_AMOUNT_HAS_FIGURE = re.compile(
    r"(?:rs\.?|₹|inr)\s*[\d,]+|[\d,]{3,}\s*(?:/-|per\s+(?:month|annum|year))"
    r"|\b\d[\d,.]*\s*(?:lakh|lakhs|crore)\b", re.I)


def _numbered(options: list, per_line: int = 1) -> str:
    lines = []
    for i, o in enumerate(options, 1):
        label = o[1] if isinstance(o, tuple) else o
        lines.append(f"{i}. {label}")
    return "\n".join(lines)


def welcome() -> str:
    """The one message sent before we know anything about the reader.

    So it commits to no language: Hindi and English together, two lines each,
    and nothing to decode. The old opening ran to five lines and announced a
    four-question form before saying what it was for — which is a lot to ask of
    someone who has just been handed a phone and told this might help.
    """
    return (
        "🎓 *Khoji.AI*\n\n"
        "I help you find scholarships you qualify for. Free, always.\n"
        "मैं आपको आपके लायक छात्रवृत्तियाँ ढूँढने में मदद करता हूँ। हमेशा मुफ़्त।"
    )


def ask_name() -> str:
    return ("What should I call you?\n\n"
            "(Type *skip* if you'd rather not say)")


def greet_by_name(name: str | None, lang: str = "en") -> str:
    if not name:
        return {"hi": "ठीक है, चलिए शुरू करते हैं 🙏",
                "hinglish": "Theek hai, chaliye shuru karte hain 🙏"}.get(
                    lang, "No problem — let's begin 🙏")
    return {"hi": f"नमस्ते {name} 🙏",
            "hinglish": f"Namaste {name} 🙏"}.get(lang, f"Namaste, {name} 🙏")


def ask_continue_or_restart(name: str | None, lang: str = "en") -> str:
    """Shared family phone: is this the same person, or someone new?

    Pre-translated rather than routed through the model, because it lands in the
    middle of a conversation someone is already having and a quota failure here
    would either wipe their answers or strand them.
    """
    who = name or None
    if lang == "hi":
        head = (f"नमस्ते! क्या यह {who} की ही खोज है?" if who
                else "नमस्ते! क्या हम वहीं से आगे बढ़ें?")
        return (f"{head}\n\n1. हाँ, आगे बढ़ें\n2. नई खोज शुरू करें\n\n"
                "_नई खोज पिछले जवाब हटा देगी।_")
    if lang == "hinglish":
        head = (f"Namaste! Kya yeh {who} ki hi search hai?" if who
                else "Namaste! Kya hum wahin se aage badhein?")
        return (f"{head}\n\n1. Haan, aage badhein\n2. Nayi search shuru karein\n\n"
                "_Nayi search pichhle jawab hata degi._")
    head = (f"Welcome back! Is this still {who}?" if who
            else "Welcome back! Shall we carry on where we left off?")
    return (f"{head}\n\n1. Yes, carry on\n2. Start a new search\n\n"
            "_A new search clears the previous answers._")


def resumed(name: str | None, lang: str = "en") -> str:
    if lang == "hi":
        return f"ठीक है{f', {name}' if name else ''} — जहाँ छोड़ा था वहीं से:"
    if lang == "hinglish":
        return f"Theek hai{f', {name}' if name else ''} — wahin se aage:"
    return f"Carrying on{f', {name}' if name else ''} —"


def ask_state() -> str:
    # 36 states is too many to list on a phone; ask them to type it.
    return ("*1 of 4* — Which state or UT do you live in?\n\n"
            "Just type the name, for example: _Bihar_ or _Tamil Nadu_")


def ask_state_retry(text: str) -> str:
    guesses = [s for s in STATES if text and text.strip().lower() in s.lower()][:5]
    if guesses:
        return ("I didn't catch that. Did you mean:\n\n"
                + _numbered(guesses) + "\n\nReply with the number, or type it again.")
    return ("I couldn't find that state. Please type the full name, "
            "for example: _Uttar Pradesh_, _Kerala_, _Delhi_")


def ask_level(lang: str = "en") -> str:
    import copy_hi
    H = copy_hi.headers(lang)
    if H:
        labels = copy_hi.level_labels(lang)
        opts = [(v, labels.get(l, l)) for v, l in LEVELS]
        return H["level"] + "\n\n" + _numbered(opts)
    return "*2 of 4* — What are you studying now?\n\n" + _numbered(LEVELS)


def ask_class_level() -> str:
    # Numbered as part of step 2, not as a step of its own. It is only asked of
    # school students, so counting it separately made the count a lie for
    # exactly the students who get it: they were told "4 of 4" and then had two
    # more questions to answer. A progress indicator that overshoots is worse
    # than none — it is the point in the flow where people give up.
    return ("*2 of 4* — Which class are you in? Reply with a number "
            "from *1* to *12*.\n\n"
            "(Type *skip* if you'd rather not say)")


def ask_category(lang: str = "en") -> str:
    import copy_hi
    H = copy_hi.headers(lang)
    if H:
        labels = copy_hi.category_labels(lang)
        opts = [(v, labels.get(l, l)) for v, l in CATEGORIES]
        return (H["category"] + "\n\n" + _numbered(opts)
                + "\n\n" + H["category_footer"])
    return ("*3 of 4* — Which category do you belong to?\n\n"
            + _numbered(CATEGORIES)
            + "\n\nThis helps me find scholarships reserved for your category.")


def ask_income(lang: str = "en") -> str:
    import copy_hi
    H = copy_hi.headers(lang)
    if H:
        return H["income"]
    return ("*4 of 4* — What is your family's *yearly* income?\n\n"
            "You can type: _2 lakh_ or _250000_ or _50k_\n\n"
            "Type *skip* if you don't know — I'll still show you scholarships, "
            "but you'll need to check their income limits yourself.")


ASPIRATION_COPY = {
    "en": ("One last thing, and it's optional — what would you like to do "
           "after this?", "It's completely fine not to know yet — most people "
           "don't. Type *skip* and I'll just show what fits you today."),
    "hi": ("आख़िरी बात, और यह ज़रूरी नहीं — इसके बाद आप क्या करना चाहेंगे?",
           "अभी न पता हो तो बिल्कुल ठीक है — ज़्यादातर लोगों को नहीं पता होता। "
           "*छोड़ो* लिखिए, मैं वही दिखाऊँगा जो आज आप पर लागू होता है।"),
    "hinglish": ("Aakhri baat, aur yeh zaroori nahi — iske baad aap kya karna "
                 "chahenge?",
                 "Abhi pata na ho to bilkul theek hai — zyadatar logon ko nahi "
                 "pata hota. *chodo* likhiye, main wahi dikhaunga jo aaj aap par "
                 "lagu hota hai."),
}

ASPIRATION_LABELS_HI = {
    "Keep studying — college or higher": "आगे पढ़ाई — कॉलेज या उससे ऊपर",
    "A professional course (engineering, medical, law)":
        "प्रोफेशनल कोर्स (इंजीनियरिंग, मेडिकल, लॉ)",
    "A job or skill training (ITI, diploma)": "नौकरी या हुनर की ट्रेनिंग (ITI, डिप्लोमा)",
    "Not sure yet": "अभी तय नहीं",
}

ASPIRATION_LABELS_HINGLISH = {
    "Keep studying — college or higher": "Aage padhai — college ya usse upar",
    "A professional course (engineering, medical, law)":
        "Professional course (engineering, medical, law)",
    "A job or skill training (ITI, diploma)": "Naukri ya skill training (ITI, diploma)",
    "Not sure yet": "Abhi tay nahi",
}


def ask_aspiration(lang: str = "en") -> str:
    """The exposure question, asked so that "I don't know" costs nothing.

    A student who has never met an engineer cannot aim at engineering, and this
    is the only place the bot gets to widen that. It is also the question most
    likely to make someone feel behind, so the reassurance is not decoration —
    it is the reason the question can be asked at all.
    """
    head, tail = ASPIRATION_COPY.get(lang, ASPIRATION_COPY["en"])
    labels = {"hi": ASPIRATION_LABELS_HI,
              "hinglish": ASPIRATION_LABELS_HINGLISH}.get(lang, {})
    opts = [(v, labels.get(l, l)) for v, l in ASPIRATIONS]
    return head + "\n\n" + _numbered(opts) + "\n\n" + tail


CONFIRM_COPY = {
    "en": ("Just to be sure, I understood:", "Is that right? Reply *yes*, or "
           "tell me what to change."),
    "hi": ("बस पक्का करने के लिए, मैंने यह समझा:",
           "क्या यह सही है? *yes* लिखें, या जो बदलना है वह बताइए।"),
    "hinglish": ("Bas pakka karne ke liye, maine yeh samjha:",
                 "Sahi hai? *yes* likhiye, ya jo badalna hai wo bataiye."),
}

_PROFILE_WORDS = {
    "en": {"state": "State", "education_level": "Studying", "class_level": "Class",
           "category": "Category", "family_income_inr": "Family income",
           "gender": "Gender"},
    "hi": {"state": "राज्य", "education_level": "पढ़ाई", "class_level": "कक्षा",
           "category": "श्रेणी", "family_income_inr": "पारिवारिक आय",
           "gender": "लिंग"},
    "hinglish": {"state": "State", "education_level": "Padhai", "class_level": "Class",
                 "category": "Category", "family_income_inr": "Ghar ki aay",
                 "gender": "Gender"},
}


def confirm_profile(profile, lang: str = "en") -> str:
    """One short line repeating what we heard, before anything is acted on.

    Used only when the profile came from inference — a voice note, or a whole
    sentence read in one go. Answers typed one question at a time are already
    confirmed by the act of typing them, and re-reading them back would be
    condescending.
    """
    head, tail = CONFIRM_COPY.get(lang, CONFIRM_COPY["en"])
    W = _PROFILE_WORDS.get(lang, _PROFILE_WORDS["en"])
    bits = []
    for f in ("state", "education_level", "class_level", "category",
              "family_income_inr", "gender"):
        v = getattr(profile, f, None)
        if v is None:
            continue
        if f == "family_income_inr":
            v = f"Rs {v:,}"
        bits.append(f"{W[f]}: *{v}*")
    return head + "\n" + " · ".join(bits) + "\n\n" + tail


def help_text() -> str:
    return (
        "*Khoji.AI help*\n\n"
        "I search verified Indian scholarships and show the ones you may qualify for.\n\n"
        "• *restart* — start over\n"
        "• *help* — this message\n"
        "• Reply with a number to pick an option\n"
        "• Reply with a result number to see full details\n\n"
        "⚠️ I show what the official sources say. Always confirm on the "
        "official page before applying — deadlines and rules change."
    )


def _deadline_line(s: dict) -> str:
    dl = s.get("application_deadline")
    if not dl:
        return "🗓 Last date: *not announced yet*"
    try:
        d = datetime.fromisoformat(dl).date()
    except ValueError:
        return f"🗓 Last date: {dl}"
    days = (d - date.today()).days
    pretty = d.strftime("%d %b %Y")
    if s.get("deadline_is_tentative"):
        return f"🗓 Last date: {pretty} _(tentative — confirm on the official page)_"
    if days < 0:
        return f"🗓 Last date: {pretty} _(closed)_"
    if days <= 7:
        return f"⏰ *Last date: {pretty} — only {days} days left!*"
    if days <= 30:
        return f"🗓 Last date: *{pretty}* ({days} days left)"
    return f"🗓 Last date: {pretty}"


def _amount_line(s: dict) -> str | None:
    # Prefer the source's own wording: it carries conditions the integers drop.
    text = s.get("benefit_amount_text")
    lo, hi = s.get("benefit_amount_min_inr"), s.get("benefit_amount_max_inr")
    if lo or hi:
        if lo and hi and lo != hi:
            return f"💰 Amount: Rs {lo:,} – Rs {hi:,}"
        return f"💰 Amount: Rs {(hi or lo):,}"
    if text and _AMOUNT_HAS_FIGURE.search(text):
        # The pipeline already drops amount text that is really a fragment of
        # the guideline PDF, but the check is repeated here because a dataset
        # built before that fix would otherwise render
        # "💰 Amount: 6. INSTITUITIONS ELIGIBLE AND QUANTUM OF ASSISTANCE '\.) Q…"
        # under a rupee sign, which a student cannot tell from a real figure.
        clean = " ".join(text.split())[:110]
        return f"💰 Amount: {clean}"
    return None


# One results renderer, two label sets. Two near-identical functions drifted
# apart every time either was touched; the furniture is the only thing that
# differs between languages, so only the furniture is duplicated.
RESULTS_LABELS = {
    "en": {
        "header_some": "✅ Found *{n}* scholarships you may qualify for",
        "header_eligible": "✅ Found *{n}* matches — *{k}* you clearly qualify for",
        "sorted": "_Best match first — ✅ means you meet every stated condition._",
        "now": "",
        "later": "🔭 *For later — worth planning for*",
        "fallback": "Nothing matched your current year of study exactly. "
                    "Here is what came closest:",
        "deadline_none": "Last date not announced",
        "days_left": "{d} days left",
        "check": "Check",
        "pick": "Reply with a *number* to see full details and how to apply.",
        "again": "Type *restart* to search again.",
    },
    "hi": {
        "header_some": "✅ *{n}* छात्रवृत्तियाँ मिलीं",
        "header_eligible": "✅ *{n}* मिलीं — *{k}* के लिए आप पूरी तरह योग्य हैं",
        "sorted": "_सबसे उपयुक्त पहले — ✅ का मतलब आप हर बताई गई शर्त पूरी करते हैं।_",
        "now": "",
        "later": "🔭 *आगे के लिए — अभी से तैयारी*",
        "fallback": "आपकी अभी की पढ़ाई से पूरी तरह मेल खाता कुछ नहीं मिला। "
                    "जो सबसे नज़दीक है, वह यह है:",
        "deadline_none": "अंतिम तिथि घोषित नहीं",
        "days_left": "{d} दिन बचे",
        "check": "जाँचें",
        "pick": "विवरण के लिए *नंबर* भेजिए।",
        "again": "फिर से खोजने के लिए *restart* लिखें।",
    },
}
RESULTS_LABELS["hinglish"] = copy_hinglish.RESULTS


# The matcher's internal criterion names were being printed straight to the
# student — "⚠️ जाँचें: education_level" in the middle of a Hindi message.
CRITERION_LABELS = {
    "en": {"state": "state", "education_level": "study level",
           "category": "category", "income": "income", "gender": "gender",
           "class": "class"},
    "hi": {"state": "राज्य", "education_level": "पढ़ाई का स्तर",
           "category": "श्रेणी", "income": "आय", "gender": "लिंग",
           "class": "कक्षा"},
    "hinglish": {"state": "state", "education_level": "padhai ka level",
                 "category": "category", "income": "income", "gender": "gender",
                 "class": "class"},
}


# relevance.py returns its reasons in English — they are also read in logs and
# tests, so that is where they live. The handful a student can actually see are
# translated here rather than routed through a model: they appear on every
# results screen, and paying a quota call per line for eight fixed strings would
# be indefensible.
_REASON_TEXT = {
    "hi": {
        "for later — apply once you reach Class {n}":
            "आगे के लिए — कक्षा {n} में पहुँचने पर आवेदन कीजिए",
        "for later — apply once you start your degree":
            "आगे के लिए — कॉलेज शुरू करने पर आवेदन कीजिए",
        "for later — apply after your degree, for a master's":
            "आगे के लिए — स्नातक के बाद, मास्टर्स के लिए",
        "for later — apply after your master's, for research":
            "आगे के लिए — मास्टर्स के बाद, शोध के लिए",
        "for later — apply if you join a diploma course":
            "आगे के लिए — डिप्लोमा में दाख़िला लेने पर",
        "for later — apply if you join an ITI":
            "आगे के लिए — आईटीआई में दाख़िला लेने पर",
        "for later — apply if you join a professional course":
            "आगे के लिए — प्रोफेशनल कोर्स में दाख़िला लेने पर",
        "for later — apply once you move up a level":
            "आगे के लिए — अगले स्तर पर पहुँचने पर",
        "coaching for the entrance exam after Class 12":
            "कक्षा 12 के बाद की प्रवेश परीक्षा की कोचिंग",
        "civil-services coaching, after your degree":
            "सिविल सेवा कोचिंग — स्नातक के बाद",
        "for an earlier stage of study": "पढ़ाई के पिछले स्तर के लिए",
        "more than one step ahead of where you are":
            "आपकी अभी की पढ़ाई से एक क़दम से ज़्यादा आगे",
    },
    "hinglish": {
        "for later — apply once you reach Class {n}":
            "aage ke liye — Class {n} me pahunchne par apply kijiye",
        "for later — apply once you start your degree":
            "aage ke liye — college shuru karne par apply kijiye",
        "for later — apply after your degree, for a master's":
            "aage ke liye — degree ke baad, master's ke liye",
        "for later — apply after your master's, for research":
            "aage ke liye — master's ke baad, research ke liye",
        "for later — apply if you join a diploma course":
            "aage ke liye — diploma me admission lene par",
        "for later — apply if you join an ITI":
            "aage ke liye — ITI me admission lene par",
        "for later — apply if you join a professional course":
            "aage ke liye — professional course me admission lene par",
        "for later — apply once you move up a level":
            "aage ke liye — agle level par pahunchne par",
        "coaching for the entrance exam after Class 12":
            "Class 12 ke baad ki entrance exam ki coaching",
        "civil-services coaching, after your degree":
            "civil services coaching — degree ke baad",
        "for an earlier stage of study": "padhai ke pichhle level ke liye",
        "more than one step ahead of where you are":
            "aapki abhi ki padhai se ek kadam se zyada aage",
    },
}
_CLASS_REASON = re.compile(r"^(for later — apply once you reach Class )(\d+)$")


def _relevance_text(reason: str, lang: str) -> str:
    table = _REASON_TEXT.get(lang)
    if not table or not reason:
        return reason
    m = _CLASS_REASON.match(reason)
    if m:
        return table["for later — apply once you reach Class {n}"].format(n=m.group(2))
    return table.get(reason, reason)


def _criterion_names(criteria, lang: str) -> str:
    L = CRITERION_LABELS.get(lang, CRITERION_LABELS["en"])
    return ", ".join(L.get(c.name, c.name) for c in criteria)


def _result_line(i: int, r: MatchResult, T: dict, lang: str = "en") -> list[str]:
    s = r.scholarship
    name = " ".join((s.get("name") or "").split())
    # A plan-ahead entry is NOT_ELIGIBLE today by design — it is on the list
    # because of when, not whether. A ✅/🔎 tick would misread as a judgement
    # on the student, so it gets its own mark.
    tick = ("🔭" if r.relevance == "later"
            else "✅" if r.verdict is Verdict.ELIGIBLE else "🔎")
    home = [x for x in (s.get("states") or []) if x.lower() != "all"]
    badge = f" _({home[0]})_" if len(home) == 1 else ""
    out = [f"*{i}.* {tick} {name}{badge}"]

    dl = s.get("application_deadline")
    if dl:
        try:
            d = datetime.fromisoformat(dl).date()
            days = (d - date.today()).days
            line = f"    🗓 {d:%d %b %Y}"
            if 0 <= days <= 30:
                line += " — " + T["days_left"].format(d=days)
            out.append(line)
        except ValueError:
            pass
    else:
        out.append(f"    🗓 {T['deadline_none']}")

    # Why this one is here at all. An aspirational entry with no explanation
    # reads as a mistake — "why are you showing me a PG scholarship?"
    if r.relevance in ("later", "suppress") and r.relevance_reason:
        out.append(f"    _{_relevance_text(r.relevance_reason, lang)}_")
    if r.unknowns:
        out.append(f"    ⚠️ {T['check']}: "
                   + _criterion_names(r.unknowns[:2], lang))
    out.append("")
    return out


def results_summary(results: list[MatchResult], profile_known: list[str],
                    lang: str = "en") -> str:
    """Scheme names and dates stay as published in every language — translating
    an official scholarship name would make it unsearchable."""
    if not results:
        return no_results()
    T = RESULTS_LABELS.get(lang, RESULTS_LABELS["en"])

    now = [r for r in results if r.relevance == "now"]
    later = [r for r in results if r.relevance == "later"]
    fallback = [r for r in results if r.relevance == "suppress"]

    eligible = [r for r in results if r.verdict is Verdict.ELIGIBLE]
    head = (T["header_eligible"].format(n=len(results), k=len(eligible))
            if eligible else T["header_some"].format(n=len(results)))
    lines = [head, T["sorted"], ""]

    # Numbering runs across the whole list so "3" always means the third thing
    # on screen, whichever bucket it sits in.
    i = 1
    for r in now:
        lines += _result_line(i, r, T, lang)
        i += 1
    if later:
        lines.append(T["later"])
        lines.append("")
        for r in later:
            lines += _result_line(i, r, T, lang)
            i += 1
    if fallback:
        lines.append(T["fallback"])
        lines.append("")
        for r in fallback:
            lines += _result_line(i, r, T, lang)
            i += 1

    lines.append(T["pick"])
    lines.append(T["again"])
    return "\n".join(lines)[:MAX_WHATSAPP_CHARS]


DETAIL_LABELS = {
    "en": {
        "by": "🏛 By", "who": "*Why this matches you:*",
        "apply_nsp": "📝 Apply on the *National Scholarship Portal*",
        "apply": "📝 Apply via",
        "later": "🔭 _This one is for later, not for right now._",
        "unknown_warn": "⚠️ _Some conditions above weren't stated by the source. "
                        "Please confirm on the official page before applying._",
        "checked": "_Checked against the official source on {d}._",
        "unchecked": "_Not recently re-checked — please confirm details on the "
                     "official page._",
        "next": "Type *more* to understand this scholarship, *documents* for the "
                "papers you'll need, or another *number*.",
        "more_head": "📖 *About this scholarship*",
        "docs_head": "📄 *Documents you'll need*",
        "docs_none": "The source does not list the documents for this scheme. "
                     "Check the official page.",
        "where": "Where to get it",
        "fails": "*What most often goes wrong*",
        "fails_note": "_General to this portal, not specific to this scheme._",
        "renewal": "🔁 *Next year*",
        "back": "Type *documents* for the papers, or another *number*.",
        "back_docs": "Type *more* to understand this scholarship, or another "
                     "*number*.",
    },
    "hi": {
        "by": "🏛 द्वारा", "who": "*यह आप पर क्यों लागू होती है:*",
        "apply_nsp": "📝 *National Scholarship Portal* पर आवेदन कीजिए",
        "apply": "📝 आवेदन का तरीका",
        "later": "🔭 _यह अभी के लिए नहीं, आगे के लिए है।_",
        "unknown_warn": "⚠️ _ऊपर की कुछ शर्तें स्रोत ने नहीं बताईं। आवेदन से "
                        "पहले आधिकारिक पेज पर ज़रूर जाँच लें।_",
        "checked": "_{d} को आधिकारिक स्रोत से मिलान किया गया।_",
        "unchecked": "_हाल में दोबारा जाँच नहीं हुई — आधिकारिक पेज पर पुष्टि करें।_",
        "next": "समझने के लिए *more* लिखें, ज़रूरी कागज़ों के लिए *documents*, "
                "या कोई और *नंबर*।",
        "more_head": "📖 *इस छात्रवृत्ति के बारे में*",
        "docs_head": "📄 *ज़रूरी कागज़*",
        "docs_none": "स्रोत ने कागज़ों की सूची नहीं दी। आधिकारिक पेज देखिए।",
        "where": "कहाँ से मिलेगा",
        "fails": "*आमतौर पर क्या गड़बड़ होती है*",
        "fails_note": "_यह इस पोर्टल की सामान्य बात है, इसी योजना की नहीं।_",
        "renewal": "🔁 *अगले साल*",
        "back": "कागज़ों के लिए *documents*, या कोई और *नंबर*।",
        "back_docs": "समझने के लिए *more*, या कोई और *नंबर*।",
    },
}
DETAIL_LABELS["hinglish"] = copy_hinglish.DETAIL


def scholarship_detail(r: MatchResult, lang: str = "en") -> str:
    """First screen: what it is worth, when it closes, why it matched.

    Everything else is one word away. A student on a ₹99 data pack should not
    have to scroll past a document glossary to find the deadline — the whole
    record is available, but it arrives when it is asked for.
    """
    T = DETAIL_LABELS.get(lang, DETAIL_LABELS["en"])
    s = r.scholarship
    name = " ".join((s.get("name") or "").split())
    out = [f"🎓 *{name}*", ""]

    if r.relevance == "later":
        out.append(T["later"])
        if r.relevance_reason:
            out.append(f"_{_relevance_text(r.relevance_reason, lang)}_")
        out.append("")

    provider = s.get("administering_body") or s.get("provider_name")
    if provider:
        out.append(f"{T['by']}: {provider}")

    amt = _amount_line(s)
    if amt:
        out.append(amt)
    out.append(_deadline_line(s))

    # Eligibility, stated honestly.
    out.append("")
    out.append(T["who"])
    for c in r.criteria:
        if c.verdict is Verdict.ELIGIBLE:
            out.append(f"  ✅ {c.detail}")
    for c in r.unknowns:
        out.append(f"  ❓ {c.detail}")
    # The one thing standing between them and this scholarship, named plainly.
    if r.relevance == "later":
        for c in r.failures:
            out.append(f"  🔭 {c.detail}")

    out.append("")
    mode = s.get("application_mode")
    if mode == "NSP":
        out.append(T["apply_nsp"])
    elif mode:
        out.append(f"{T['apply']}: {mode.replace('_', ' ')}")

    url = s.get("application_url") or s.get("official_url")
    if url:
        out.append(url)
    official = s.get("official_url")
    if official and official != url:
        out.append(f"\n📄 {official}")

    # Trust footer — never hide what we don't know.
    out.append("")
    if r.unknowns:
        out.append(T["unknown_warn"])
    lv = s.get("last_verified_date")
    out.append(T["checked"].format(d=lv) if lv else T["unchecked"])

    out.append("")
    out.append(T["next"])
    return "\n".join(out)[:MAX_WHATSAPP_CHARS]


def _translated(translate, texts: list[str]) -> list[str]:
    """Translate a block of content in ONE call, or not at all.

    The catalogue is written in English and translated at delivery, so a Hindi
    student reading three paragraphs would otherwise cost three model calls on a
    twenty-call daily quota. Joining them makes it one. If the model returns a
    different number of paragraphs than it was given, the mapping is no longer
    trustworthy and the English is shown instead — a garbled Hindi paragraph is
    worse than an English one.
    """
    texts = [t for t in texts if t]
    if not translate or not texts:
        return texts
    sep = "\n\n"
    try:
        out = translate(sep.join(texts))
    except Exception:
        return texts
    parts = [p.strip() for p in (out or "").split(sep) if p.strip()]
    return parts if len(parts) == len(texts) else texts


def scholarship_more(r: MatchResult, lang: str = "en", translate=None) -> str:
    """"Tell me more" — what it is, who it's for, what it changes.

    All of it comes from the dataset's composed content fields, built at
    pipeline time from verified fields and fixed human-written phrasing. Nothing
    on this screen is invented at request time; `translate` only changes the
    language it is said in.
    """
    T = DETAIL_LABELS.get(lang, DETAIL_LABELS["en"])
    s = r.scholarship
    body = _translated(translate, [s.get(k) for k in
                                   ("what_it_is", "who_its_for", "how_it_helps",
                                    "renewal_note")])
    out = [T["more_head"], ""]
    for v in body[:3]:
        out += [v, ""]
    if len(body) == 4:
        out += [T["renewal"], body[3], ""]
    out.append(T["back"])
    return "\n".join(out)[:MAX_WHATSAPP_CHARS]


def scholarship_documents(r: MatchResult, lang: str = "en", translate=None) -> str:
    """"What documents?" — each paper, and where it is actually obtained.

    The second half is the part students never get told: an income certificate
    is not something you own, it is something you queue for at the tehsildar's
    office, and knowing that a fortnight before the deadline is the difference
    between applying and not.
    """
    T = DETAIL_LABELS.get(lang, DETAIL_LABELS["en"])
    s = r.scholarship
    out = [T["docs_head"], ""]

    docs = s.get("documents_explained") or []
    fails = s.get("common_reasons_applications_fail") or []
    if not docs:
        out.append(T["docs_none"])

    # One translation call for the whole screen, in a fixed order so the pieces
    # can be put back where they came from. Document *labels* stay in English on
    # purpose — "Income Certificate" is what the portal and the counter clerk
    # both call it, and a student showing up asking for something else loses a
    # morning.
    body = [d.get("what", "") for d in docs] + \
           [d.get("where", "") for d in docs] + list(fails)
    body = _translated(translate, body)
    n = len(docs)
    whats, wheres = body[:n], body[n:2 * n]

    for i, d in enumerate(docs):
        out.append(f"*{d.get('label')}*")
        if i < len(whats) and whats[i]:
            out.append(f"  {whats[i]}")
        if i < len(wheres) and wheres[i]:
            out.append(f"  📍 {T['where']}: {wheres[i]}")
        out.append("")

    if fails:
        out.append(T["fails"])
        out.append(T["fails_note"])
        for f in body[2 * n:]:
            out.append(f"  • {f}")
        out.append("")

    out.append(T["back_docs"])
    return "\n".join(out)[:MAX_WHATSAPP_CHARS]


def no_results() -> str:
    return (
        "😔 I couldn't find a scholarship matching all your details right now.\n\n"
        "This usually means one of:\n"
        "• Applications for your state haven't opened yet\n"
        "• Your combination is covered by a scheme I don't have yet\n\n"
        "Two things you can try:\n"
        "1. Type *restart* and choose *General* for category — many schemes are "
        "open to everyone\n"
        "2. Check the National Scholarship Portal directly:\n"
        "https://scholarships.gov.in\n\n"
        "I'm still growing my list, so please check back."
    )


def invalid_option(step: Step) -> str:
    prompts = {
        Step.LEVEL: ask_level(),
        Step.CATEGORY: ask_category(),
        Step.INCOME: ask_income(),
    }
    return "Sorry, I didn't understand that.\n\n" + prompts.get(
        step, "Please reply with the number of your choice.")
