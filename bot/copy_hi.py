"""Pre-translated Hindi copy for the fixed messages.

Measured on a real conversation: a Hindi student cost 8 model calls, all of them
translating the SAME fixed prompts — "which state do you live in?" does not need
a language model, and on a 20-calls-per-day free tier it bought two
conversations. The English path already cost zero.

So the standard prompts ship translated. The model is then needed only for what
is genuinely dynamic or unpredictable: understanding free-form input, and
answering questions. That takes a Hindi conversation from 8 calls to about 0.

Keys are the exact English strings the bot produces. Anything absent falls
through to the model, so adding a new message degrades gracefully rather than
appearing untranslated.
"""

from __future__ import annotations

# Exact-match lookups: English message -> Hindi message.
HI: dict[str, str] = {

    # The welcome itself is bilingual by construction and is never translated —
    # it is the one message sent before we know anything about the reader.

    "What should I call you?\n\n"
    "(Type *skip* if you'd rather not say)":
        "मैं आपको क्या कहकर बुलाऊँ?\n\n"
        "(न बताना चाहें तो *छोड़ो* लिखें)",

    # ---- the four questions --------------------------------------------
    "*1 of 4* — Which state or UT do you live in?\n\n"
    "Just type the name, for example: _Bihar_ or _Tamil Nadu_":
        "*1 / 4* — आप किस राज्य में रहते हैं?\n\n"
        "बस नाम लिखिए, जैसे: _बिहार_ या _राजस्थान_",

    "*2 of 4* — Which class are you in? Reply with a number "
    "from *1* to *12*.\n\n"
    "(Type *skip* if you'd rather not say)":
        "*2 / 4* — आप किस कक्षा में हैं? *1* से *12* तक कोई नंबर भेजिए।\n\n"
        "(न बताना चाहें तो *छोड़ो* लिखें)",

    # ---- short questions used by the intent layer -----------------------
    "Which state do you live in?": "आप किस राज्य में रहते हैं?",
    "What are you studying now?": "आप अभी क्या पढ़ रहे हैं?",
    "Which class are you in?": "आप किस कक्षा में हैं?",
    "Which category do you belong to?": "आप किस श्रेणी से हैं?",
    "What is your family's yearly income?": "आपके परिवार की सालाना आय कितनी है?",

    # ---- acknowledgements ----------------------------------------------
    "No problem.": "कोई बात नहीं।",
    "That's fine.": "ठीक है।",
    "No problem — I'll show you what I have, and you can check "
    "each scheme's income limit on its official page.":
        "कोई बात नहीं — मैं आपको जो मिला है दिखाता हूँ। हर योजना की आय-सीमा "
        "आप उसके आधिकारिक पेज पर देख सकते हैं।",

    "Good question — I'll be able to answer that once I've found "
    "your scholarships.":
        "अच्छा सवाल — आपकी छात्रवृत्तियाँ मिलने के बाद मैं इसका जवाब दे सकूँगा।",

    # ---- errors and retries ---------------------------------------------
    "I couldn't find that state. Please type the full name, "
    "for example: _Uttar Pradesh_, _Kerala_, _Delhi_":
        "मुझे वह राज्य नहीं मिला। कृपया पूरा नाम लिखिए, "
        "जैसे: _उत्तर प्रदेश_, _राजस्थान_, _बिहार_",

    "Please reply with a number from *1* to *12*, or type *skip*.":
        "कृपया *1* से *12* तक कोई नंबर भेजिए, या *छोड़ो* लिखें।",

    "I couldn't read that amount. Try _2 lakh_ or _250000_, or type *skip*.":
        "मुझे वह राशि समझ नहीं आई। _2 लाख_ या _250000_ लिखिए, या *पता नहीं*।",

    "Reply with a result *number* for details, or type *restart* to search again.":
        "किसी नतीजे का *नंबर* भेजिए विवरण के लिए, या फिर से खोजने के लिए *restart*।",

    "I can't listen to voice notes just yet — please type your answer instead.":
        "मैं अभी वॉइस नोट नहीं सुन सकता — कृपया अपना जवाब लिखकर भेजिए।",

    "Sorry, I couldn't make out that voice note. Could you type it, "
    "or record it again somewhere quieter?":
        "माफ़ कीजिए, वह वॉइस नोट मुझे समझ नहीं आया। कृपया लिखकर भेजिए, "
        "या किसी शांत जगह पर दोबारा रिकॉर्ड कीजिए।",

    "Sorry, something went wrong on my side. Let's start again — type *hi*.":
        "माफ़ कीजिए, मेरी तरफ़ से कुछ गड़बड़ हुई। फिर से शुरू करें — *hi* लिखें।",
}


import re

import copy_hinglish

_DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Hindi words that no English sentence contains, written the way people type
# them on a Roman keyboard. One of these is enough to call it Hinglish.
_HINGLISH_STRONG = re.compile(
    r"\b(?:hai|hain|hoon|hun|kya|kaise|kaisa|kitna|kitni|kitne|mujhe|mera|meri|"
    r"mere|nahi|nahin|chahiye|batao|bataye|bataiye|padhai|padhta|padhti|"
    r"padhrahi|padhraha|saal|saalana|ghar|paise|paisa|theek|thik|accha|achha|"
    r"kaun|kahan|kab|kyun|kyu|aapka|aapki|aapke|hoga|hogi|honge|raha|rahi|"
    r"rahe|karna|karta|karti|karke|liye|wala|wali|jaise|abhi|dobara|"
    r"scholarship ?chahiye|madad|mila|milegi|milega|bhejiye|likhiye|dijiye)\b",
    re.I)

# Weaker markers — real Hindi particles, but short enough to collide with names
# and abbreviations. Two of these together are evidence; one is not.
_HINGLISH_WEAK = re.compile(
    r"\b(?:aap|main|mai|hum|tum|yeh|ye|woh|wo|ka|ki|ke|se|ko|mein|par|aur|to|"
    r"bhi|ji|na)\b", re.I)


def detect_language(text: str) -> str | None:
    """Which language to answer in — decided from the script and the words.

    Never from the person's name. A name is not a language preference: plenty of
    people with Hindi names write only English, and guessing wrong means
    answering someone in a language they have to work to read. The live signal
    on every message is the only thing trusted here, so a student who switches
    mid-conversation is followed rather than corrected.

    Returns "hi", "hinglish", "en" or None (nothing to go on — keep whatever
    the session already had).
    """
    if not text:
        return None
    if _DEVANAGARI.search(text):
        return "hi"
    words = re.findall(r"[A-Za-z']+", text)
    if not words:
        return None                     # digits, emoji, punctuation only
    if _HINGLISH_STRONG.search(text):
        return "hinglish"
    if len(_HINGLISH_WEAK.findall(text)) >= 2:
        return "hinglish"
    # A one-word reply ("Rajasthan", "OBC", "3") says nothing about language;
    # switching to English on it would undo a Hindi conversation.
    return "en" if len(words) >= 3 else None


def already_in(text: str, language: str) -> bool:
    """True if the text is already in the target language.

    ask_level() and friends build their output in Hindi directly. Sending those
    to a translator wastes a call and risks mangling text that was already
    correct — and on a 20-call quota, waste is the difference between a working
    bot and a dead one.
    """
    if language not in ("hi", "hinglish"):
        return False
    # Devanagari anywhere means this was built for an Indian-language reader
    # already — including the deliberately bilingual welcome.
    return bool(_DEVANAGARI.search(text))


_ACK_TEMPLATES = {
    "hi": ("समझ गया — *{v}* ✅", "बदल दिया: {v} ✅"),
    "hinglish": ("Samajh gaya — *{v}* ✅", "Badal diya: {v} ✅"),
}


def lookup(text: str, language: str) -> str | None:
    """Return pre-translated copy, or None if the model should handle it."""
    table = {"hi": HI, "hinglish": copy_hinglish.HINGLISH}.get(language)
    if table is None:
        return None
    stripped = text.strip()
    hit = table.get(stripped)
    if hit is not None:
        return hit
    if already_in(stripped, language):
        return stripped
    # Short acknowledgements are formulaic; template them rather than translate.
    got, updated = _ACK_TEMPLATES[language]
    m = re.fullmatch(r"Got it — \*(.+?)\* ✅", stripped)
    if m:
        return got.format(v=m.group(1))
    m = re.fullmatch(r"Updated: (.+) ✅", stripped)
    if m:
        return updated.format(v=m.group(1))
    return None


# --------------------------------------------------- per-language accessors
# messages.py used to branch on `lang == "hi"` in five places. With a third
# language that becomes fifteen branches, so the tables are looked up instead.

def level_labels(lang: str) -> dict:
    return {"hi": LEVEL_LABELS_HI,
            "hinglish": copy_hinglish.LEVEL_LABELS}.get(lang, {})


def category_labels(lang: str) -> dict:
    return {"hi": CATEGORY_LABELS_HI,
            "hinglish": copy_hinglish.CATEGORY_LABELS}.get(lang, {})


def headers(lang: str) -> dict | None:
    if lang == "hi":
        return {"level": ASK_LEVEL_HI_HEADER,
                "category": ASK_CATEGORY_HI_HEADER,
                "category_footer": ASK_CATEGORY_HI_FOOTER,
                "income": ASK_INCOME_HI}
    if lang == "hinglish":
        return {"level": copy_hinglish.ASK_LEVEL_HEADER,
                "category": copy_hinglish.ASK_CATEGORY_HEADER,
                "category_footer": copy_hinglish.ASK_CATEGORY_FOOTER,
                "income": copy_hinglish.ASK_INCOME}
    return None


# Built dynamically because the option lists live in conversation.py and would
# otherwise drift out of sync with these translations.
LEVEL_LABELS_HI = {
    "School (Class 1-12)": "स्कूल (कक्षा 1-12)",
    "ITI": "आईटीआई (ITI)",
    "Diploma / Polytechnic": "डिप्लोमा / पॉलिटेक्निक",
    "Graduation (BA, BSc, BCom, BTech)": "स्नातक (BA, BSc, BCom, BTech)",
    "Post-graduation (MA, MSc, MTech)": "स्नातकोत्तर (MA, MSc, MTech)",
    "PhD / Research": "पीएचडी / शोध",
    "Professional (Medical, Engineering, Law)": "प्रोफेशनल (मेडिकल, इंजीनियरिंग, लॉ)",
}

CATEGORY_LABELS_HI = {
    "SC": "अनुसूचित जाति (SC)",
    "ST": "अनुसूचित जनजाति (ST)",
    "OBC": "अन्य पिछड़ा वर्ग (OBC)",
    "EWS": "आर्थिक रूप से कमज़ोर (EWS)",
    "Minority": "अल्पसंख्यक",
    "Disability (PwD)": "दिव्यांग (PwD)",
    "DNT / Nomadic": "विमुक्त / घुमंतू (DNT)",
    "General / None of these": "सामान्य / इनमें से कोई नहीं",
}

# Headers for the two list questions, rendered with the labels above.
ASK_LEVEL_HI_HEADER = "*2 / 4* — आप अभी क्या पढ़ रहे हैं?"
ASK_CATEGORY_HI_HEADER = "*3 / 4* — आप किस श्रेणी से हैं?"
ASK_CATEGORY_HI_FOOTER = (
    "इससे मुझे आपकी श्रेणी के लिए आरक्षित छात्रवृत्तियाँ ढूँढने में मदद मिलेगी।")
ASK_INCOME_HI = (
    "*4 / 4* — आपके परिवार की *सालाना* आय कितनी है?\n\n"
    "आप लिख सकते हैं: _2 लाख_ या _250000_ या _50k_\n\n"
    "अगर पता न हो तो *पता नहीं* लिखें — मैं फिर भी छात्रवृत्तियाँ दिखाऊँगा, "
    "पर आपको उनकी आय-सीमा खुद देखनी होगी।")


# Devanagari state names -> the canonical English spelling the dataset uses.
# Without these a Hindi-speaking student cannot answer the very first question
# unless the model is available, which defeats the point of pre-translating the
# question into Hindi in the first place.
STATES_HI = {
    "आंध्र प्रदेश": "Andhra Pradesh", "अरुणाचल प्रदेश": "Arunachal Pradesh",
    "असम": "Assam", "आसाम": "Assam", "बिहार": "Bihar",
    "छत्तीसगढ़": "Chhattisgarh", "छत्तीसगढ": "Chhattisgarh",
    "गोवा": "Goa", "गुजरात": "Gujarat", "हरियाणा": "Haryana",
    "हिमाचल प्रदेश": "Himachal Pradesh", "हिमाचल": "Himachal Pradesh",
    "झारखंड": "Jharkhand", "झारखण्ड": "Jharkhand",
    "कर्नाटक": "Karnataka", "केरल": "Kerala", "केरला": "Kerala",
    "मध्य प्रदेश": "Madhya Pradesh", "मध्यप्रदेश": "Madhya Pradesh",
    "महाराष्ट्र": "Maharashtra", "मणिपुर": "Manipur", "मेघालय": "Meghalaya",
    "मिज़ोरम": "Mizoram", "मिजोरम": "Mizoram", "नागालैंड": "Nagaland",
    "ओडिशा": "Odisha", "उड़ीसा": "Odisha", "पंजाब": "Punjab",
    "राजस्थान": "Rajasthan", "सिक्किम": "Sikkim",
    "तमिलनाडु": "Tamil Nadu", "तमिल नाडु": "Tamil Nadu",
    "तेलंगाना": "Telangana", "त्रिपुरा": "Tripura",
    "उत्तर प्रदेश": "Uttar Pradesh", "उत्तरप्रदेश": "Uttar Pradesh",
    "उत्तराखंड": "Uttarakhand", "उत्तराखण्ड": "Uttarakhand",
    "पश्चिम बंगाल": "West Bengal", "बंगाल": "West Bengal",
    "दिल्ली": "Delhi", "नई दिल्ली": "Delhi",
    "जम्मू कश्मीर": "Jammu and Kashmir", "जम्मू और कश्मीर": "Jammu and Kashmir",
    "लद्दाख": "Ladakh", "पुडुचेरी": "Puducherry", "पांडिचेरी": "Puducherry",
    "चंडीगढ़": "Chandigarh", "लक्षद्वीप": "Lakshadweep",
    # Common cities students name instead of their state.
    "जयपुर": "Rajasthan", "जोधपुर": "Rajasthan", "उदयपुर": "Rajasthan",
    "कोटा": "Rajasthan", "अजमेर": "Rajasthan", "बाड़मेर": "Rajasthan",
    "पटना": "Bihar", "लखनऊ": "Uttar Pradesh", "मुंबई": "Maharashtra",
    "बेंगलुरु": "Karnataka", "चेन्नई": "Tamil Nadu", "कोलकाता": "West Bengal",
    "हैदराबाद": "Telangana", "अहमदाबाद": "Gujarat", "भोपाल": "Madhya Pradesh",
}

# Devanagari digits, so "१२" reads as class 12.
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")

# Category words a student may type instead of picking a number.
CATEGORIES_HI = {
    "अनुसूचित जाति": "SC", "एससी": "SC",
    "अनुसूचित जनजाति": "ST", "एसटी": "ST", "जनजाति": "ST", "आदिवासी": "ST",
    "पिछड़ा": "OBC", "ओबीसी": "OBC", "अन्य पिछड़ा वर्ग": "OBC",
    "सामान्य": "general", "जनरल": "general",
    "अल्पसंख्यक": "minority", "दिव्यांग": "PwD", "विकलांग": "PwD",
    "ईडब्ल्यूएस": "EWS",
}
