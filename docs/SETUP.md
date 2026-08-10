# Getting Khoji.AI live — step by step

Written for someone who has not used Google Cloud or Meta's developer tools
before. Every step says what you are doing, exactly what to click or type, and
what you should see when it worked.

**Total time: about 1 hour.** You can stop after any step and pick up later.

**Lost? Run this any time:**

```bash
cd "/Users/voyager/Desktop/AI Hackathons/Khoji.AI AI"
./deploy/check.sh
```

It tells you what is done and what your single next action is.

---

## Before you start: your phone number

You said this number is only for this work. One thing to check, because it
decides whether you can proceed:

**Is WhatsApp currently installed and registered on that number?**

- **No** → perfect, nothing to do.
- **Yes** → you must delete its WhatsApp account first. Meta will not let a
  number be on both consumer WhatsApp and the Business API.
  On that phone: *WhatsApp → Settings → Account → Delete my account*.
  This is permanent. Chats on that number are gone.

**You do not need to decide today.** Steps 1–8 use Meta's free test number.
You only bring your own number in at Step 9.

---

# PART A — Your laptop (10 minutes)

## Step 1 — Install the Google Cloud tool

`gcloud` is the command that talks to Google Cloud from your terminal.

```bash
brew install --cask google-cloud-sdk
```

Takes 3–5 minutes. When it finishes, **close your terminal and open a new one**
(the installer edits your shell config, and the current window won't see it).

Check it worked:

```bash
gcloud --version
```

✅ You should see several lines starting with `Google Cloud SDK 5xx.x.x`.

❌ `command not found` → run this, then reopen the terminal:
```bash
echo 'source "$(brew --prefix)/share/google-cloud-sdk/path.zsh.inc"' >> ~/.zshrc
```

---

# PART B — WhatsApp setup (20 minutes)

You are creating a Meta developer app. This is what gives your bot the ability
to send and receive WhatsApp messages.

## Step 2 — Create a Meta Business account

1. Go to <https://business.facebook.com>
2. Sign in with a Facebook account (make one if needed — it is only used as a
   login, nothing is posted anywhere)
3. **Create account** → enter a business name (e.g. `Khoji.AI`), your name,
   your email

✅ You land on the Business Suite dashboard.

## Step 3 — Create the app

1. Go to <https://developers.facebook.com/apps>
2. **Create App**
3. Use case: choose **Other** → **Next**
4. App type: **Business** → **Next**
5. App name: `Khoji.AI Bot`. Pick the business account from Step 2.
6. **Create app** (it may ask for your password)

✅ You are on the app dashboard.

## Step 4 — Add WhatsApp to the app

1. On the dashboard, scroll to **WhatsApp** → **Set up**
2. It creates a test WhatsApp Business Account for you
3. You are now on the **API Setup** page

On that page, **copy these two things into a notes file** — you need them later:

| What | Where it is | Looks like |
|---|---|---|
| **Phone number ID** | under "From" | `123456789012345` |
| **Temporary access token** | top of the page | `EAAG...` (very long) |

⚠️ That token **expires in 24 hours**. Fine for today. Step 11 replaces it with
a permanent one.

## Step 5 — Add your own phone as a tester

Still on API Setup, under **To**:

1. **Manage phone number list** → **Add phone number**
2. Enter *your personal phone* (the one you'll test from, not the bot's number)
3. Enter the code WhatsApp sends you

✅ Your number appears in the "To" dropdown. Until Meta reviews the app, the bot
can only message numbers on this list — which is exactly what you want for
testing.

---

# PART C — Gemini (5 minutes)

Gemini lets the bot understand Hindi and other Indian languages, and messages
written as normal sentences instead of menu numbers. **The bot works without
it** — just English and numbered menus.

## Step 6 — Get a Gemini API key

1. Go to <https://aistudio.google.com/apikey>
2. Sign in with your Google account
3. **Create API key** → choose or create a project
4. Copy the key (starts with `AIza...`) into your notes file

Check it works and see which models your key can use:

```bash
cd "/Users/voyager/Desktop/AI Hackathons/Khoji.AI AI"
export GEMINI_API_KEY=paste_your_key_here
./.venv/bin/python bot/llm.py
```

✅ You get a list of model names. If you see `gemini-2.5-flash`, you are set.
If not, note the closest `flash` model in the list — you'll use it in Step 10.

---

# PART D — Google Cloud (20 minutes)

This is where the bot actually runs.

## Step 7 — Log in and create a project

```bash
gcloud auth login
```

A browser opens. Sign in and allow access.

```bash
gcloud projects create edudisha-bot --name="Khoji.AI"
gcloud config set project edudisha-bot
```

⚠️ Project IDs must be globally unique. If it says the ID is taken, add digits:
`edudisha-bot-2049`. **Use your actual ID everywhere below.**

## Step 8 — Turn on billing

Google requires a billing account even for free-tier usage. **You will not be
charged** at pilot scale — everything here sits inside the free tiers, and your
credits cover anything beyond.

1. Go to <https://console.cloud.google.com/billing>
2. Link a billing account to `edudisha-bot` (create one if you have none —
   it asks for a card but does not charge it)

Then:

```bash
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

Takes 1–2 minutes. ✅ Finishes with no output, or "Operation finished
successfully".

## Step 9 — Create the session database

This remembers where each student is in the conversation.

```bash
gcloud firestore databases create --location=asia-south1
```

`asia-south1` is Mumbai — closest to your users, so replies are fastest.

## Step 10 — Store your three secrets

Passwords must never sit in code. Secret Manager holds them and gives Cloud Run
access at runtime.

Replace the CAPITALISED parts with your real values:

```bash
# 1. Meta access token (Step 4)
printf '%s' "EAAG_YOUR_LONG_TOKEN" | gcloud secrets create meta-access-token --data-file=-

# 2. A verify token — you invent this. Any random string. Save it in your notes.
printf '%s' "edudisha-verify-8371" | gcloud secrets create meta-verify-token --data-file=-

# 3. Gemini key (Step 6)
printf '%s' "AIza_YOUR_KEY" | gcloud secrets create gemini-api-key --data-file=-
```

✅ Each prints `Created version [1]`.

The **verify token** is just a shared password between Meta and your server, to
prove a webhook call really came from Meta. Invent anything; just use the *same*
value in Step 12.

---

# PART E — Deploy (10 minutes)

## Step 11 — Put the bot online

```bash
cd "/Users/voyager/Desktop/AI Hackathons/Khoji.AI AI"

export PROJECT_ID=edudisha-bot            # your real project ID
export META_PHONE_NUMBER_ID=123456789012345    # from Step 4
export REGION=asia-south1

./deploy/deploy.sh
```

First deploy takes 5–8 minutes (it builds a container). Later ones are faster.

✅ It ends by printing your service URL and a health check like:

```json
{"status":"ok","gemini":true,"store":"FirestoreSessionStore","records":100}
```

**Copy the webhook URL it prints** — `https://edudisha-xxxxx.a.run.app/webhook/meta`

Two things to confirm in that health output:
- `"gemini": true` → language support is on
- `"store": "FirestoreSessionStore"` → sessions will survive restarts

If either is wrong the bot still runs, but degraded. Run `./deploy/check.sh` to
see which one to fix.

## Step 12 — Connect WhatsApp to your bot

Back in the Meta app (<https://developers.facebook.com/apps>):

1. **WhatsApp → Configuration**
2. Next to **Webhook**, click **Edit**
3. **Callback URL**: the `/webhook/meta` URL from Step 11
4. **Verify token**: the exact string you invented in Step 10
5. **Verify and save**

✅ The dialog closes with no error. That means Meta called your server and your
server answered correctly.

❌ "The callback URL couldn't be validated" → almost always the verify token
doesn't match. Check for a trailing space.

6. Still on Configuration, next to **Webhook fields** click **Manage**
7. Find **messages** → tick **Subscribe** → done

⚠️ This last click is the one people forget. Without it Meta accepts your
webhook but never sends you anything.

---

# PART F — Test it (5 minutes)

## Step 13 — Say hi

From the phone you added in Step 5, send `hi` to the test number shown on
Meta's API Setup page.

✅ Within a couple of seconds you get the Khoji.AI welcome message.

Walk the whole flow: `hi` → `Assam` → `1` → `10` → `2` → `1.5 lakh` → `1`

If Gemini is on, try Hindi: `मैं बिहार से हूं, कक्षा 10 में पढ़ता हूं`

❌ No reply? In this order:

```bash
# 1. Is the service alive?
curl -s https://YOUR-URL/health

# 2. What did it see?
gcloud run services logs read edudisha --region asia-south1 --limit 50
```

- No log lines at all → Meta isn't calling you. Re-check Step 12, especially
  the **messages** subscription.
- Log lines but no reply → the access token is wrong or expired (Step 14).

---

# PART G — Make it last

## Step 14 — Replace the 24-hour token

The token from Step 4 dies tomorrow. Get a permanent one:

1. <https://business.facebook.com/settings/system-users>
2. **Add** → name it `edudisha-bot` → role **Admin** → Create
3. **Add Assets** → **Apps** → your app → toggle **Manage app** → Save
4. **Generate new token** → select your app → set **Token expiration: Never**
5. Tick **whatsapp_business_messaging** and **whatsapp_business_management**
6. **Generate token** → copy it

Store it as a new version and restart:

```bash
printf '%s' "YOUR_PERMANENT_TOKEN" | \
  gcloud secrets versions add meta-access-token --data-file=-

gcloud run services update edudisha --region asia-south1
```

## Step 15 — Bring in your own number

Only now, once everything works on the test number.

1. Confirm WhatsApp is deleted from that number (see the top of this document)
2. Meta app → **WhatsApp → API Setup** → **Add phone number**
3. Enter the number, business details, verify by SMS or call
4. Copy its **new Phone number ID**
5. Redeploy with it:

```bash
export META_PHONE_NUMBER_ID=your_new_id
./deploy/deploy.sh
```

## Step 16 — Keep the data fresh

Scholarship deadlines change constantly, and a wrong deadline is the mistake
most likely to hurt a student. Weekly — and daily from August to November:

```bash
cd "/Users/voyager/Desktop/AI Hackathons/Khoji.AI AI"
./.venv/bin/python pipeline.py crawl
./.venv/bin/python pipeline.py parse
./.venv/bin/python pipeline.py rank
./.venv/bin/python pipeline.py verify
./.venv/bin/python pipeline.py export
./.venv/bin/python src/make_deliverables.py
./deploy/deploy.sh
```

The deploy script warns you if the dataset is more than 7 days old.

---

# Quick reference

| Task | Command |
|---|---|
| Where am I? | `./deploy/check.sh` |
| Test locally, no WhatsApp | `./.venv/bin/python bot/simulate.py` |
| Is it alive? | `curl -s https://YOUR-URL/health` |
| What went wrong? | `gcloud run services logs read edudisha --region asia-south1 --limit 50` |
| Redeploy | `./deploy/deploy.sh` |
| Which Gemini models? | `./.venv/bin/python bot/llm.py` |

## Words you'll see

- **Cloud Run** — runs your bot. Sleeps when unused, so it costs nothing idle.
- **Firestore** — remembers each student's place in the conversation.
- **Secret Manager** — a safe for passwords and tokens.
- **Webhook** — the URL Meta calls when someone messages your bot.
- **Verify token** — a password you invent, proving a call came from Meta.
- **Phone number ID** — a number identifying your WhatsApp sender. Not the
  phone number itself.

## What this will cost

Effectively **₹0** for a pilot. At ~1,000 conversations/month, under **₹100**,
and only from Gemini. Cloud Run, Firestore and Secret Manager stay inside their
free tiers, and WhatsApp is free when the student messages first.

It only gets expensive if *you* start conversations (marketing templates). This
bot only ever replies, so that does not apply.
