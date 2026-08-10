"""Firestore-backed session storage.

Cloud Run containers are stateless and scale to zero, so an in-memory store
loses every conversation on a cold start and gives each instance its own view of
the world. Firestore fixes both, costs nothing at this volume, and needs no
server to run.

Sessions carry a TTL field so abandoned conversations expire rather than
accumulating; set a Firestore TTL policy on `expires_at` to have Google delete
them for you.
"""

from __future__ import annotations

import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone

from dataclasses import fields as _dc_fields

from conversation import Session, Step
from matching import StudentProfile

log = logging.getLogger("bot.store")

COLLECTION = os.environ.get("FIRESTORE_COLLECTION", "khoji_sessions")
SESSION_TTL_HOURS = int(os.environ.get("SESSION_TTL_HOURS", "48"))

# Session fields that cross the storage boundary, derived from the dataclass so
# adding a field to Session is enough — no second place to remember.
#
# `phone` is excluded because storing it would undo the pseudonymisation the
# document id exists for. `profile` and `step` need conversion and are handled
# by hand. `last_results` holds whole MatchResult objects and is rebuilt from
# `last_result_ids` instead.
_NOT_CARRIED = {"phone", "profile", "step", "last_results"}
_CARRIED = tuple(f.name for f in _dc_fields(Session) if f.name not in _NOT_CARRIED)


def hash_phone(phone: str) -> str:
    """Pseudonymise a WhatsApp number before it is stored (PRD 12.2).

    A phone number is directly identifying, and these users are often minors.
    We key sessions on a salted SHA-256 instead, so the database never holds a
    readable number: anyone reading the store sees an opaque id and cannot dial
    it, look it up, or link it to another dataset.

    The salt lives in PHONE_HASH_SALT and must be secret and stable. Without a
    salt, the space of Indian phone numbers is small enough to brute-force a
    plain hash in seconds, so an unset salt is a warning, not a default.
    """
    salt = os.environ.get("PHONE_HASH_SALT", "")
    if not salt:
        log.warning("PHONE_HASH_SALT is not set - phone hashes are brute-forceable. "
                    "Generate one: openssl rand -hex 32")
    digest = hashlib.sha256(f"{salt}:{(phone or '').strip()}".encode()).hexdigest()
    return digest[:40]


class FirestoreSessionStore:
    """Same get/save/reset interface as InMemorySessionStore.

    Full `MatchResult` objects are not persisted — they would bloat every
    document. Their ids are, so the shortlist is rebuilt from the catalogue on
    the next message and the student can still reply "2" to open a result.
    """

    def __init__(self, project: str | None = None, collection: str = COLLECTION):
        from google.cloud import firestore
        self.db = firestore.Client(project=project or
                                   os.environ.get("GOOGLE_CLOUD_PROJECT"))
        self.collection = collection
        log.info("firestore session store ready (collection=%s)", collection)

    def _doc(self, phone: str):
        return self.db.collection(self.collection).document(hash_phone(phone))

    def get(self, phone: str) -> Session:
        # `phone` stays in memory for the length of one request so we can reply;
        # only its hash is ever persisted.
        try:
            snap = self._doc(phone).get()
        except Exception as e:
            log.warning("firestore read failed for %s: %s", hash_phone(phone)[:8], e)
            return Session(phone=phone)

        if not snap.exists:
            return Session(phone=phone)

        data = snap.to_dict() or {}
        try:
            profile = StudentProfile(**(data.get("profile") or {}))
            step = Step(data.get("step", Step.WELCOME.value))
        except (TypeError, ValueError) as e:
            # A schema change should not strand a student mid-conversation.
            log.warning("stale session for %s (%s); starting fresh", hash_phone(phone)[:8], e)
            return Session(phone=phone)

        s = Session(phone=phone, step=step, profile=profile)
        for f in _CARRIED:
            if f in data:
                setattr(s, f, data[f])
        return s

    def save(self, s: Session) -> None:
        payload = {
            # The raw number is deliberately absent; the document id is the
            # salted hash. Storing it here would undo the pseudonymisation.
            "phone_hash": hash_phone(s.phone),
            "step": s.step.value,
            "profile": s.profile.__dict__,
            "updated_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc)
                          + timedelta(hours=SESSION_TTL_HOURS),
        }
        # Everything else on the Session, discovered rather than listed. The
        # hand-written list this replaces was correct on the day it was written
        # and silently wrong every time a field was added after — first
        # `last_result_ids`, then `last_detail_index`, each showing up only in
        # production because the in-memory store keeps the whole object.
        for f in _CARRIED:
            payload[f] = getattr(s, f, None)
        # Ids only. The full records are rebuilt from the catalogue, so a
        # session document stays small while the student can still pick a
        # result on their next message.
        payload["last_result_ids"] = list(s.last_result_ids or [])[:10]
        try:
            self._doc(s.phone).set(payload)
        except Exception as e:
            # Losing a session is bad; failing the whole reply is worse.
            log.warning("firestore write failed for %s: %s", hash_phone(s.phone)[:8], e)

    def reset(self, phone: str) -> Session:
        s = Session(phone=phone)
        self.save(s)
        return s

    def __len__(self) -> int:
        try:
            return sum(1 for _ in self.db.collection(self.collection)
                       .limit(1000).stream())
        except Exception:
            return -1


def build_store():
    """Pick a store from the environment.

    Firestore when a GCP project is configured, in-memory otherwise, so local
    development needs no cloud credentials.
    """
    from engine import InMemorySessionStore
    if os.environ.get("USE_FIRESTORE", "").lower() in ("1", "true", "yes"):
        try:
            return FirestoreSessionStore()
        except Exception as e:
            log.error("firestore unavailable (%s); falling back to memory", e)
    return InMemorySessionStore()
