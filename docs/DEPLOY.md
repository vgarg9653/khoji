# Deploying Khoji.AI

Target stack — everything except WhatsApp itself runs on Google Cloud:

| Piece | Service | Cost at pilot scale |
|---|---|---|
| Bot server | Cloud Run | ~free (scales to zero; 2M requests/month free) |
| Sessions | Firestore | ~free (50k reads + 20k writes/day free) |
| Secrets | Secret Manager | ~free (6 versions free) |
| Language | Gemini API | free tier, then ~₹0.01 per conversation |
| Weekly data refresh | Cloud Scheduler | free (3 jobs free) |
| WhatsApp | Meta Cloud API | free for user-initiated chats |

Realistically **₹0 for a pilot**, and Google credits cover the rest.

---

## ⚠️ Read this first: your WhatsApp number

**A number currently registered on the normal WhatsApp app cannot be used with
the Business Cloud API until you delete its WhatsApp account.** That deletion is
irreversible — chat history is gone, and you cannot use that number on regular
WhatsApp again while it is on the API.

So do **not** start with your personal number. Options, best first:

1. **Meta's free test number** — issued instantly with your app, no verification.
   Good for everything up to real users. **Start here.**
2. **A second SIM / eSIM** dedicated to the bot. This is what you want for the
   real launch.
3. **Your existing number** — only once you are sure, and only after exporting
   anything you want to keep.

A landline or VoIP number works too, as long as it can receive the verification
call or SMS.

---

## Step 1 — Meta WhatsApp Cloud API

1. Create a Meta Business account: <https://business.facebook.com>
2. At <https://developers.facebook.com/apps> create an app → type **Business**.
3. Add the **WhatsApp** product. Meta gives you a **test number** and a
   temporary 24-hour token immediately.
4. From *WhatsApp → API Setup*, note:
   - **Phone number ID** → `META_PHONE_NUMBER_ID`
   - **WhatsApp Business Account ID**
   - **Temporary access token** → fine for today; replace it in step 5.
5. For a permanent token: *Business Settings → Users → System Users* → add a
   system user with the **whatsapp_business_messaging** and
   **whatsapp_business_management** permissions → *Generate token*, no expiry.
   That value is `META_ACCESS_TOKEN`.
6. Invent any random string for `META_VERIFY_TOKEN` — you will paste the same
   value into Meta and into Cloud Run so the two can recognise each other.

Add your own phone as a **recipient** under *API Setup* so you can message the
test number before Meta approves anything.

---

## Step 2 — Gemini API key

Get one at <https://aistudio.google.com/apikey> (free tier is generous — plenty
for a pilot).

Confirm which models your key can use rather than trusting a default:

```bash
export GEMINI_API_KEY=your_key
python bot/llm.py            # prints every model that supports generateContent
```

Set `GEMINI_MODEL` to one the listing shows. The code defaults to
`gemini-2.5-flash`, which is the right shape for this workload — short
extraction and translation calls where latency matters more than depth. If the
listing does not show it, pick the closest Flash model it does show.

**The bot runs fine without Gemini.** No key means the rule-based flow, English
only. Gemini adds two things: understanding free-form and non-English messages,
and answering follow-up questions grounded in a scholarship record.

---

## Step 3 — Google Cloud setup

```bash
export PROJECT_ID=edudisha          # or your existing project
export REGION=asia-south1                # Mumbai — closest to your users

gcloud auth login
gcloud projects create $PROJECT_ID       # skip if it exists
gcloud config set project $PROJECT_ID

# Link billing (required even though usage stays inside the free tier)
gcloud billing projects link $PROJECT_ID --billing-account=YOUR_BILLING_ID

gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudscheduler.googleapis.com
```

Create the Firestore database (once per project):

```bash
gcloud firestore databases create --location=$REGION
```

Store the secrets:

```bash
printf '%s' "YOUR_META_ACCESS_TOKEN" | \
  gcloud secrets create meta-access-token --data-file=-
printf '%s' "YOUR_VERIFY_TOKEN" | \
  gcloud secrets create meta-verify-token --data-file=-
printf '%s' "YOUR_GEMINI_KEY" | \
  gcloud secrets create gemini-api-key --data-file=-
```

---

## Step 4 — Deploy

```bash
./deploy/deploy.sh
```

That script wraps the following, so you can run it by hand if you prefer:

```bash
gcloud run deploy edudisha \
  --source . \
  --region $REGION \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --min-instances 0 \
  --max-instances 5 \
  --timeout 60 \
  --set-env-vars "USE_FIRESTORE=true,GOOGLE_CLOUD_PROJECT=$PROJECT_ID,META_PHONE_NUMBER_ID=YOUR_ID,GEMINI_MODEL=gemini-2.5-flash" \
  --set-secrets "META_ACCESS_TOKEN=meta-access-token:latest,META_VERIFY_TOKEN=meta-verify-token:latest,GEMINI_API_KEY=gemini-api-key:latest"
```

Grant the runtime service account access to Firestore:

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/datastore.user"
```

Check it came up:

```bash
SERVICE_URL=$(gcloud run services describe khoji --region $REGION --format='value(status.url)')
curl -s $SERVICE_URL/health | python -m json.tool
```

You want `"gemini": true` and `"store": "FirestoreSessionStore"`. If either is
wrong, the service is running degraded — check the env vars and the IAM binding.

`--allow-unauthenticated` is required: Meta's servers call your webhook and
cannot authenticate to Google. The verify token and signature check are what
protect the endpoint, which is why step 5 matters.

---

## Step 5 — Point WhatsApp at it

In *WhatsApp → Configuration → Webhook*:

- **Callback URL**: `https://YOUR-SERVICE-URL/webhook/meta`
- **Verify token**: the `META_VERIFY_TOKEN` from step 1
- Click **Verify and save** — Meta calls `GET /webhook/meta` and expects the
  challenge echoed back. A failure here is almost always a token mismatch.
- Subscribe to the **messages** field. Nothing else is needed.

Then message the test number from the phone you registered as a recipient.
You should get the welcome message back within a second or two.

---

## Step 6 — Keep the data fresh

Deadlines are the thing most likely to be wrong, and a wrong deadline is the
error most likely to hurt a student. Re-run the pipeline and redeploy weekly —
daily during the August–November application season.

The crawler needs Playwright and stays off Cloud Run. Run it wherever you build:

```bash
python pipeline.py crawl && python pipeline.py parse && \
python pipeline.py rank  && python pipeline.py verify && \
python pipeline.py export && python src/make_deliverables.py
gcloud run deploy edudisha --source . --region $REGION
```

If you want it automated, put that in a Cloud Build trigger on a schedule —
Cloud Build has Chromium available, unlike Cloud Run.

To be notified rather than automated, a Cloud Scheduler job hitting `/health`
will at least tell you when the service stops answering.

---

## What it costs once real students use it

At **1,000 conversations/month**, roughly 6 messages each:

| | |
|---|---|
| Cloud Run | free (well under 2M requests) |
| Firestore | free (~12k writes) |
| Gemini Flash | ~₹50–100/month, only if Gemini is enabled |
| WhatsApp | free — user-initiated conversations cost nothing |
| **Total** | **under ₹100/month** |

The cost only becomes real if *you* start the conversation (marketing
templates), which is billed per conversation. Keep the bot reply-only and it
stays effectively free.

---

## Troubleshooting

| Symptom | Cause |
|---|---|
| Webhook verification fails | `META_VERIFY_TOKEN` differs between Meta and Cloud Run |
| Verified, but no replies | Not subscribed to the **messages** field |
| Replies stop after 24h | Temporary token expired — issue a system-user token |
| `"gemini": false` in /health | Key missing, or the model id is not on your key |
| `"store": "InMemorySessionStore"` | `USE_FIRESTORE` unset, or the IAM binding is missing |
| Students lose their place | Same as above — sessions are living in memory |
| Cold start feels slow | Set `--min-instances 1` (a few ₹/month, worth it) |

Logs:

```bash
gcloud run services logs read khoji --region $REGION --limit 50
```

---

## Before real students, not after

1. **Set `--min-instances 1`** so the first message of the day is not slow.
2. **Add a privacy notice.** You are handling a minor's caste, disability and
   family income. Say what you store (sessions expire in 48h), and give a way
   to delete it. This is the right thing to do and it is also what India's DPDP
   Act expects.
3. **Log what students search for, not who they are.** The dataset's gaps are
   best prioritised by real demand; that does not require retaining personal
   data.
4. **Have a human escalation path.** When the bot finds nothing, a student with
   a real problem needs somewhere to go.
