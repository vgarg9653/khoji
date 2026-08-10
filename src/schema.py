"""Canonical scholarship record schema, SQLite DDL, and controlled vocabularies.

The rule this whole project turns on: a field we could not read from the source
is None. It is never inferred, never defaulted to a plausible value. Field
completeness is computed from that honesty, so a low score is information, not
a defect to be papered over.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, fields, asdict
from typing import Any

# ---------------------------------------------------------------- vocabularies

PROVIDER_TYPES = {"central_govt", "state_govt", "psu", "private", "ngo", "university"}

COURSE_TYPES = {"school", "ITI", "diploma", "UG", "PG", "PhD", "professional",
                "postdoc", "certificate"}

CATEGORIES = {"SC", "ST", "OBC", "EWS", "minority", "general", "all", "PwD", "DNT"}

GENDERS = {"any", "female", "male", "transgender"}

BENEFIT_TYPES = {"tuition", "maintenance", "one-time", "mixed", "mentorship",
                 "loan_subsidy", "stipend"}

APPLICATION_MODES = {"NSP", "state_portal", "provider_website", "offline", "email",
                     "university"}

SELECTION_PROCESS = {"merit", "means", "merit_cum_means", "interview", "test",
                     "lottery", "first_come"}

STATUS = {"active", "unknown", "expired"}

CONFIDENCE = {"high", "medium", "low"}

# Controlled document list. Parsers normalize free text onto these keys; anything
# unmatched is preserved verbatim in documents_other so nothing is silently lost.
DOCUMENTS = {
    "aadhaar", "income_certificate", "caste_certificate", "bonafide", "marksheet",
    "bank_passbook", "photo", "domicile_certificate", "disability_certificate",
    "admission_proof", "fee_receipt", "signature", "ration_card", "birth_certificate",
    "transfer_certificate", "gap_certificate", "parent_death_certificate",
    "minority_certificate", "self_declaration", "id_proof", "study_certificate",
    "employment_certificate", "medical_certificate",
}

INDIAN_STATES = {
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chhattisgarh", "Goa",
    "Gujarat", "Haryana", "Himachal Pradesh", "Jharkhand", "Karnataka", "Kerala",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland",
    "Odisha", "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura",
    "Uttar Pradesh", "Uttarakhand", "West Bengal",
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Jammu and Kashmir",
    "Ladakh", "Lakshadweep", "Puducherry",
}

# Fields counted toward field_completeness_percent. Identity/meta fields we always
# populate ourselves are excluded, since including them would inflate every score.
COMPLETENESS_FIELDS = [
    "provider_name", "provider_type", "administering_body", "scheme_year",
    "education_levels", "class_min", "class_max", "course_types", "field_of_study",
    "states", "categories", "gender", "income_ceiling_inr", "min_marks_percent",
    "age_min", "age_max", "parent_occupation_specific",
    "benefit_amount_min_inr", "benefit_amount_max_inr", "benefit_amount_text",
    "benefit_type", "duration_years", "renewable", "number_of_awards",
    "application_mode", "application_url", "application_deadline",
    "selection_process", "documents_required", "official_url", "description_short",
]

LIST_FIELDS = {
    "aliases", "education_levels", "course_types", "field_of_study", "states",
    "districts", "categories", "documents_required", "documents_other",
    "languages_of_official_page", "source_urls",
}

BOOL_FIELDS = {
    "servable",
    "religion_specific", "disability", "entrance_exam_required",
    "orphan_or_single_parent", "renewable", "deadline_is_tentative", "needs_review",
}


@dataclass
class Scholarship:
    """One scholarship. Every optional field defaults to None, never to a guess."""

    # --- identity ---
    id: str | None = None
    name: str | None = None
    name_normalized: str | None = None
    aliases: list[str] = field(default_factory=list)
    provider_name: str | None = None
    provider_type: str | None = None
    administering_body: str | None = None
    scheme_year: str | None = None

    # --- eligibility ---
    education_levels: list[str] = field(default_factory=list)
    class_min: int | None = None
    class_max: int | None = None
    course_types: list[str] = field(default_factory=list)
    field_of_study: list[str] = field(default_factory=list)
    states: list[str] = field(default_factory=list)
    districts: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    religion_specific: str | None = None
    gender: str | None = None
    income_ceiling_inr: int | None = None
    # Verbatim sentence the ceiling was read from, so a reviewer can confirm the
    # number in seconds instead of re-reading the whole guideline PDF.
    income_evidence: str | None = None
    disability: bool | None = None
    disability_type: str | None = None
    min_marks_percent: float | None = None
    grade_criteria: str | None = None
    entrance_exam_required: bool | None = None
    entrance_exam_name: str | None = None
    age_min: int | None = None
    age_max: int | None = None
    orphan_or_single_parent: bool | None = None
    parent_occupation_specific: str | None = None
    other_criteria: str | None = None

    # --- benefit ---
    benefit_amount_min_inr: int | None = None
    benefit_amount_max_inr: int | None = None
    benefit_amount_text: str | None = None
    benefit_type: str | None = None
    duration_years: float | None = None
    renewable: bool | None = None
    renewal_criteria: str | None = None
    number_of_awards: int | None = None

    # --- application ---
    application_mode: str | None = None
    application_url: str | None = None
    application_start_date: str | None = None
    application_deadline: str | None = None
    deadline_is_tentative: bool | None = None
    selection_process: str | None = None
    typical_announcement_month: str | None = None

    # --- documents ---
    documents_required: list[str] = field(default_factory=list)
    documents_other: list[str] = field(default_factory=list)

    # --- trust & meta ---
    official_url: str | None = None
    source_url: str | None = None
    source_urls: list[str] = field(default_factory=list)
    source_name: str | None = None
    extraction_date: str | None = None
    last_verified_date: str | None = None
    status: str = "unknown"
    confidence: str = "medium"
    needs_review: bool = False
    needs_review_reason: str | None = None
    reach_score: float | None = None
    # Quality gate (src/quality.py). Withheld records stay in the database with
    # a reason, so nothing is silently lost and a rule can be relaxed later.
    servable: bool | None = None
    not_servable_reason: str | None = None
    rank: int | None = None
    tier: str = "backlog"                    # 'top100' | 'backlog'
    field_completeness_percent: float | None = None
    description_short: str | None = None
    languages_of_official_page: list[str] = field(default_factory=list)
    raw_text_path: str | None = None

    # --- verification bookkeeping ---
    verify_http_status: int | None = None
    verify_redirected_to: str | None = None
    verify_notes: str | None = None

    def completeness(self) -> float:
        filled = 0
        for f in COMPLETENESS_FIELDS:
            v = getattr(self, f, None)
            if isinstance(v, (list, tuple, set)):
                if len(v) > 0:
                    filled += 1
            elif v is not None and v != "":
                filled += 1
        return round(100.0 * filled / len(COMPLETENESS_FIELDS), 1)

    def to_row(self) -> dict[str, Any]:
        import json as _json
        d = asdict(self)
        for k in LIST_FIELDS:
            d[k] = _json.dumps(d.get(k) or [], ensure_ascii=False)
        for k in BOOL_FIELDS:
            v = d.get(k)
            d[k] = None if v is None else int(bool(v))
        return d


FIELD_NAMES = [f.name for f in fields(Scholarship)]

_SQL_TYPES = {
    "class_min": "INTEGER", "class_max": "INTEGER", "income_ceiling_inr": "INTEGER",
    "age_min": "INTEGER", "age_max": "INTEGER", "benefit_amount_min_inr": "INTEGER",
    "benefit_amount_max_inr": "INTEGER", "number_of_awards": "INTEGER",
    "rank": "INTEGER", "verify_http_status": "INTEGER",
    "min_marks_percent": "REAL", "duration_years": "REAL", "reach_score": "REAL",
    "field_completeness_percent": "REAL",
}
for _b in BOOL_FIELDS:
    _SQL_TYPES[_b] = "INTEGER"


def create_schema(conn: sqlite3.Connection) -> None:
    cols = []
    for name in FIELD_NAMES:
        typ = _SQL_TYPES.get(name, "TEXT")
        if name == "id":
            cols.append("id TEXT PRIMARY KEY")
        else:
            cols.append(f"{name} {typ}")
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS scholarships ({", ".join(cols)});
        CREATE INDEX IF NOT EXISTS idx_sch_norm ON scholarships(name_normalized);
        CREATE INDEX IF NOT EXISTS idx_sch_tier ON scholarships(tier);
        CREATE INDEX IF NOT EXISTS idx_sch_rank ON scholarships(rank);
        CREATE INDEX IF NOT EXISTS idx_sch_status ON scholarships(status);

        CREATE TABLE IF NOT EXISTS crawl_log (
            url TEXT, domain TEXT, source_name TEXT, status TEXT,
            outcome TEXT, reason TEXT, fetched_at TEXT, cache_path TEXT
        );
        CREATE TABLE IF NOT EXISTS review_queue (
            scholarship_id TEXT, name TEXT, reason TEXT, snippet TEXT,
            field TEXT, stored_value TEXT, found_value TEXT,
            official_url TEXT, flagged_at TEXT
        );
        CREATE TABLE IF NOT EXISTS run_meta (
            key TEXT PRIMARY KEY, value TEXT
        );
    """)

    # Adding a field to Scholarship must not require deleting the database.
    # CREATE TABLE IF NOT EXISTS silently leaves an older table alone, so we
    # reconcile the columns explicitly on every connect.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(scholarships)")}
    for name in FIELD_NAMES:
        if name not in existing:
            typ = _SQL_TYPES.get(name, "TEXT")
            conn.execute(f"ALTER TABLE scholarships ADD COLUMN {name} {typ}")
    conn.commit()


def connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    return conn


def upsert(conn: sqlite3.Connection, s: Scholarship) -> None:
    row = s.to_row()
    placeholders = ", ".join("?" for _ in FIELD_NAMES)
    conn.execute(
        f"INSERT OR REPLACE INTO scholarships ({', '.join(FIELD_NAMES)}) "
        f"VALUES ({placeholders})",
        [row[f] for f in FIELD_NAMES],
    )


def row_to_scholarship(row: sqlite3.Row) -> Scholarship:
    import json as _json
    d = dict(row)
    for k in LIST_FIELDS:
        try:
            d[k] = _json.loads(d.get(k) or "[]")
        except Exception:
            d[k] = []
    for k in BOOL_FIELDS:
        v = d.get(k)
        d[k] = None if v is None else bool(v)
    return Scholarship(**{k: v for k, v in d.items() if k in FIELD_NAMES})
