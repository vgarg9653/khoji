"""Roman-script Hindi — the register most Indian students actually type in.

Devanagari and English were the only two options here, and both were wrong for
the largest group of users: people who speak Hindi, read Roman script fastest,
and type "mai class 12 me hu, Rajasthan se". Answering them in Devanagari is not
their language either — many can speak Hindi fluently and read it slowly, having
done most of their typing on a Roman keyboard.

So this is a third copy set, not a transliteration of the second. Same keys as
`copy_hi.HI`, so the same lookup serves all three languages.

Spelling follows what people type, not any transliteration standard: "hai" not
"hai͠", "chhatravritti" not "chātravr̥tti".
"""

from __future__ import annotations

HINGLISH: dict[str, str] = {

    "What should I call you?\n\n"
    "(Type *skip* if you'd rather not say)":
        "Main aapko kya kehkar bulaun?\n\n"
        "(Nahi batana chahte to *chodo* likhiye)",

    # ---- the questions --------------------------------------------------
    "*1 of 4* — Which state or UT do you live in?\n\n"
    "Just type the name, for example: _Bihar_ or _Tamil Nadu_":
        "*1 / 4* — Aap kis state me rehte hain?\n\n"
        "Bas naam likh dijiye, jaise: _Bihar_ ya _Rajasthan_",

    "*2 of 4* — Which class are you in? Reply with a number "
    "from *1* to *12*.\n\n"
    "(Type *skip* if you'd rather not say)":
        "*2 / 4* — Aap kis class me hain? *1* se *12* tak koi number bhejiye.\n\n"
        "(Nahi batana chahte to *chodo* likhiye)",

    # ---- short forms used by the intent layer ----------------------------
    "Which state do you live in?": "Aap kis state me rehte hain?",
    "What are you studying now?": "Abhi aap kya padh rahe hain?",
    "Which class are you in?": "Aap kis class me hain?",
    "Which category do you belong to?": "Aap kis category se hain?",
    "What is your family's yearly income?":
        "Aapke ghar ki saalana aay kitni hai?",

    # ---- acknowledgements ------------------------------------------------
    "No problem.": "Koi baat nahi.",
    "That's fine.": "Theek hai.",
    "No problem — I'll show you what I have, and you can check "
    "each scheme's income limit on its official page.":
        "Koi baat nahi — jo mere paas hai wo dikhata hoon. Har scheme ki "
        "income limit aap uske official page par dekh sakte hain.",

    "Good question — I'll be able to answer that once I've found "
    "your scholarships.":
        "Achha sawaal — aapki scholarships milne ke baad main iska jawab de "
        "sakunga.",

    # ---- errors and retries ----------------------------------------------
    "I couldn't find that state. Please type the full name, "
    "for example: _Uttar Pradesh_, _Kerala_, _Delhi_":
        "Mujhe wo state nahi mili. Poora naam likhiye, "
        "jaise: _Uttar Pradesh_, _Rajasthan_, _Bihar_",

    "Please reply with a number from *1* to *12*, or type *skip*.":
        "Kripya *1* se *12* tak koi number bhejiye, ya *chodo* likhiye.",

    "I couldn't read that amount. Try _2 lakh_ or _250000_, or type *skip*.":
        "Mujhe wo amount samajh nahi aaya. _2 lakh_ ya _250000_ likhiye, "
        "ya *pata nahi*.",

    "Reply with a result *number* for details, or type *restart* to search again.":
        "Kisi result ka *number* bhejiye details ke liye, ya dobara khojne ke "
        "liye *restart* likhiye.",

    "I can't listen to voice notes just yet — please type your answer instead.":
        "Main abhi voice note nahi sun sakta — kripya likhkar bhejiye.",

    "Sorry, I couldn't make out that voice note. Could you type it, "
    "or record it again somewhere quieter?":
        "Maaf kijiye, wo voice note samajh nahi aaya. Likhkar bhejiye, ya "
        "kisi shaant jagah par dobara record kijiye.",

    "Sorry, something went wrong on my side. Let's start again — type *hi*.":
        "Maaf kijiye, meri taraf se kuch gadbad hui. Dobara shuru karein — "
        "*hi* likhiye.",
}

LEVEL_LABELS = {
    "School (Class 1-12)": "School (Class 1-12)",
    "ITI": "ITI",
    "Diploma / Polytechnic": "Diploma / Polytechnic",
    "Graduation (BA, BSc, BCom, BTech)": "Graduation (BA, BSc, BCom, BTech)",
    "Post-graduation (MA, MSc, MTech)": "Post-graduation (MA, MSc, MTech)",
    "PhD / Research": "PhD / Research",
    "Professional (Medical, Engineering, Law)":
        "Professional (Medical, Engineering, Law)",
}

CATEGORY_LABELS = {
    "SC": "SC (Anusuchit Jaati)",
    "ST": "ST (Anusuchit Janjaati)",
    "OBC": "OBC (Pichhda Varg)",
    "EWS": "EWS (Aarthik roop se kamzor)",
    "Minority": "Minority (Alpsankhyak)",
    "Disability (PwD)": "Divyang (PwD)",
    "DNT / Nomadic": "DNT / Ghumantu",
    "General / None of these": "General / Inme se koi nahi",
}

ASK_LEVEL_HEADER = "*2 / 4* — Abhi aap kya padh rahe hain?"
ASK_CATEGORY_HEADER = "*3 / 4* — Aap kis category se hain?"
ASK_CATEGORY_FOOTER = (
    "Isse mujhe aapki category ke liye reserved scholarships dhoondhne me "
    "madad milegi.")
ASK_INCOME = (
    "*4 / 4* — Aapke ghar ki *saalana* aay kitni hai?\n\n"
    "Aap likh sakte hain: _2 lakh_ ya _250000_ ya _50k_\n\n"
    "Pata na ho to *pata nahi* likhiye — main phir bhi scholarships dikhaunga, "
    "par unki income limit aapko khud dekhni hogi.")

RESULTS = {
    "header_some": "✅ *{n}* scholarships mili",
    "header_eligible": "✅ *{n}* mili — *{k}* ke liye aap poori tarah yogya hain",
    "sorted": "_Sabse sahi pehle — ✅ ka matlab aap har batayi gayi shart poori "
              "karte hain._",
    "now": "",
    "later": "🔭 *Aage ke liye — abhi se taiyari*",
    "fallback": "Aapki abhi ki padhai se poori tarah milta kuch nahi mila. "
                "Jo sabse kareeb hai, wo yeh hai:",
    "deadline_none": "Last date abhi tay nahi",
    "days_left": "{d} din bache",
    "check": "Jaanch lein",
    "pick": "Details ke liye *number* bhejiye.",
    "again": "Dobara khojne ke liye *restart* likhiye.",
}

DETAIL = {
    "by": "🏛 Dwara", "who": "*Yeh aap par kyun lagu hoti hai:*",
    "apply_nsp": "📝 *National Scholarship Portal* par apply kijiye",
    "apply": "📝 Apply karne ka tarika",
    "later": "🔭 _Yeh abhi ke liye nahi, aage ke liye hai._",
    "unknown_warn": "⚠️ _Upar ki kuch sharten source ne nahi batayin. Apply "
                    "karne se pehle official page par zaroor dekh lijiye._",
    "checked": "_{d} ko official source se milaan kiya gaya._",
    "unchecked": "_Haal me dobara jaanch nahi hui — official page par pushti "
                 "kar lijiye._",
    "next": "Samajhne ke liye *more* likhiye, zaroori kaagaz ke liye "
            "*documents*, ya koi aur *number*.",
    "more_head": "📖 *Is scholarship ke baare me*",
    "docs_head": "📄 *Zaroori kaagaz*",
    "docs_none": "Source ne kaagazon ki list nahi di. Official page dekhiye.",
    "where": "Kahan se milega",
    "fails": "*Aam taur par kya galat hota hai*",
    "fails_note": "_Yeh is portal ki aam baat hai, isi scheme ki nahi._",
    "renewal": "🔁 *Agle saal*",
    "back": "Kaagazon ke liye *documents*, ya koi aur *number*.",
    "back_docs": "Samajhne ke liye *more*, ya koi aur *number*.",
}
