"""Which cheap model can do the bot's actual jobs? Measured, not assumed."""
import json, os, pathlib, sys, time
for line in pathlib.Path(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1); os.environ.setdefault(k.strip(), v.strip())
sys.path.insert(0, "bot")
from google import genai
from google.genai import types
import llm as L

client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

CANDIDATES = ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite",
              "gemini-2.5-flash-lite", "gemini-2.0-flash-lite",
              "gemini-3.6-flash", "gemma-4-31b-it"]

EXTRACT_CASES = [
    ("Schedule caste", {"category": "SC"}),
    ("mai anusuchit jati se hu", {"category": "SC"}),
    ("baarahvi paas kar li hai, ab college jaana hai", {"class_level": 12}),
    ("मैं राजस्थान से हूँ, कक्षा 12 में पढ़ती हूँ, ओबीसी, आय ढाई लाख",
     {"state": "Rajasthan", "class_level": 12, "category": "OBC",
      "family_income_inr": 250000}),
    ("my father earns about 20 thousand a month", {"family_income_inr": 240000}),
]

TRANSLATE = "What is your family's yearly income?"

def call(model, system, prompt, json_out=False):
    cfg = types.GenerateContentConfig(
        system_instruction=system, temperature=0.0,
        response_mime_type="application/json" if json_out else None)
    r = client.models.generate_content(model=model, contents=prompt, config=cfg)
    return (r.text or "").strip()

for model in CANDIDATES:
    hits = total = 0
    lat = []
    err = None
    for text, want in EXTRACT_CASES:
        try:
            t0 = time.time()
            # gemma has no system_instruction support; fold it into the prompt
            if model.startswith("gemma"):
                out = call(model, None, L.EXTRACT_SYSTEM + "\n\n" + text, False)
            else:
                out = call(model, L.EXTRACT_SYSTEM, text, True)
            lat.append(time.time() - t0)
            got = L._loads(out) or {}
            for k, v in want.items():
                total += 1
                if got.get(k) == v:
                    hits += 1
        except Exception as e:
            err = str(e)[:90]
            break
    if err:
        print(f"{model:26s} ERROR {err}")
        continue
    try:
        hi = call(model, L.TRANSLATE_SYSTEM if hasattr(L, 'TRANSLATE_SYSTEM')
                  else "Translate to Hindi. Reply with the translation only.",
                  TRANSLATE)
    except Exception as e:
        hi = f"ERR {e}"[:40]
    print(f"{model:26s} extract {hits}/{total}  "
          f"p50 {sorted(lat)[len(lat)//2]:.2f}s   hi: {hi[:52]}")
