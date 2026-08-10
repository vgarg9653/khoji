"""Extractor tests.

The point of these is not coverage for its own sake. Every case below is a real
failure mode seen in an actual guideline PDF, and each one asserts the same
principle: when the text does not clearly state a value, the extractor must
return None rather than a number that looks plausible.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

import enrich as E          # noqa: E402
import normalize as N       # noqa: E402


# ------------------------------------------------------------------ age

def test_age_ignores_course_duration():
    # Seen in AICTE Swanath: "maximum 4 years duration" was read as age <= 4.
    assert E.parse_age("Rs. 50,000 per annum for maximum 4 years duration.") == (None, None)
    assert E.parse_age("Duration of the award is 3 years.") == (None, None)


def test_age_reads_explicit_ranges():
    assert E.parse_age("The age of the candidate should be between 16 to 25 years.") == (16, 25)
    assert E.parse_age("Age should not exceed 30 years as on 1st July.") == (None, 30)
    assert E.parse_age("Candidates below 35 years of age are eligible.") == (None, 35)


# --------------------------------------------------------------- awards

def test_awards_requires_award_noun():
    assert E.parse_awards("A total of 100,000 fresh scholarships are awarded.") == 100_000
    assert E.parse_awards("Number of scholarships: 5,000 per year.") == 5_000


def test_awards_rejects_money_and_years():
    assert E.parse_awards("Scholarship of Rs. 12,000 per annum is paid to each student.") is None
    assert E.parse_awards("Rs. 82,000 per annum shall be paid.") is None
    assert E.parse_awards("The scheme covers 2026 and 2027 academic years.") is None


# --------------------------------------------------------------- classes

def test_class_range_roman_and_arabic():
    assert E.parse_class_range("Applicable to classes IX to XII") == (9, 12)
    assert E.parse_class_range("students of class 11 and 12") == (11, 12)
    assert E.parse_class_range("no class mentioned here") == (None, None)


# ----------------------------------------------------------------- dates

def test_dates_are_day_first():
    assert N.parse_date("Open till : 31-10-2026") == "2026-10-31"
    assert N.parse_date("01-06-2026") == "2026-06-01"
    assert N.parse_date("15th August, 2026") == "2026-08-15"
    assert N.parse_date("no date at all") is None


def test_impossible_dates_rejected():
    assert N.parse_date("32-13-2026") is None


def test_tentative_markers():
    assert N.is_tentative("Deadline to be announced shortly")
    assert N.is_tentative("Last date (tentative): 30-09-2026")
    assert not N.is_tentative("Last date: 30-09-2026")


# --------------------------------------------------------------- amounts

def test_amounts_handle_indian_units():
    assert N.parse_amounts("Rs. 2 lakh per annum")[1] == 200_000
    assert N.parse_amounts("₹ 50,000")[1] == 50_000
    assert N.parse_amounts("no money here") == (None, None)


def test_bare_year_is_not_money():
    assert N.parse_amounts("valid for 2026") == (None, None)


def test_income_ceiling_needs_income_context():
    assert N.parse_income_ceiling("Family income should not exceed Rs. 2,50,000") == 250_000
    # An award amount is not an income ceiling.
    assert N.parse_income_ceiling("Scholarship of Rs. 50,000 per annum") is None


# ------------------------------------------------------------ classification

def test_category_detection():
    assert "SC" in N.detect_categories("Pre-Matric Scholarship for SC Students")
    assert "minority" in N.detect_categories("Scholarship for minority students")


def test_gender_detection():
    assert N.detect_gender("Pragati Scholarship for Girl Students") == "female"
    assert N.detect_gender("Post Matric Scholarship") is None


def test_state_detection_handles_aliases():
    assert "Chhattisgarh" in N.detect_states("BPL scheme - Chattisgarh")
    assert "Odisha" in N.detect_states("Scheme for Orissa students")


def test_name_normalization_dedups_variants():
    a = N.normalize_name("Post Matric Scholarship Scheme for SC Students")
    b = N.normalize_name("Post-Matric Scholarship for SC students")
    assert a == b


def test_basis_suffix_split():
    name, sel = N.strip_basis_suffix("AICTE Pragati Scholarship (Merit Based Scheme)")
    assert name == "AICTE Pragati Scholarship"
    assert sel == "merit"


# ------------------------------------------------------------------ status

def test_status_from_deadline():
    from datetime import date
    ref = date(2026, 8, 7)
    assert N.infer_status("2026-10-31", ref) == "active"
    assert N.infer_status("2026-01-31", ref) == "expired"
    assert N.infer_status(None, ref) == "unknown"


# ------------------------------------------------------------- completeness

def test_completeness_counts_only_filled_fields():
    from schema import Scholarship
    s = Scholarship(name="x")
    empty = s.completeness()
    s.provider_name = "AICTE"
    s.income_ceiling_inr = 800000
    assert s.completeness() > empty


def test_renewable_detection():
    assert E.parse_renewable("The scholarship is renewable every year.") is True
    assert E.parse_renewable("This is a one-time grant.") is False
    assert E.parse_renewable("Nothing relevant.") is None


# --------------------------------------- serial numbers are not rupee amounts

def test_table_row_numbers_are_not_money():
    # From DEPDGuidelines: "Sl. No. 2" was being read as a ₹2 benefit minimum.
    assert N.parse_amounts("Sl. No. 2 Components of Scholarship") == (None, None)
    lo, hi = N.parse_amounts("Sl. No. 2 a) Reimbursement of Rs. 2,00,000 per annum")
    assert lo == 200_000 and hi == 200_000


# ------------------------------- one PDF covering many schemes must not bleed

def test_shared_guidelines_pdf_leaves_scheme_specific_fields_null():
    from schema import Scholarship
    text = (
        "ELIGIBILITY: Students of classes IX and X are eligible.\n"
        "VALUE OF SCHOLARSHIP: Rs. 12,000 per annum.\n"
        "NUMBER OF SCHOLARSHIPS: 5,000 awards.\n"
        "DOCUMENTS REQUIRED: aadhaar, income certificate, marksheet.\n"
    )
    shared = Scholarship(name="Top Class Education")
    E.enrich_from_text(shared, text, shared_with=3)
    # Scheme-specific values must not be attributed to one of three schemes.
    assert shared.class_min is None and shared.class_max is None
    assert shared.benefit_amount_max_inr is None
    assert shared.number_of_awards is None
    assert shared.needs_review is True
    # Non-specific values are still safe to take.
    assert "aadhaar" in shared.documents_required

    sole = Scholarship(name="Top Class Education")
    E.enrich_from_text(sole, text, shared_with=1)
    assert (sole.class_min, sole.class_max) == (9, 10)
    assert sole.benefit_amount_max_inr == 12_000
    assert sole.number_of_awards == 5_000


# ------------------------- regiment names are not the states they contain

def test_regiment_names_are_not_states():
    # "Assam Rifles" is a paramilitary regiment recruiting nationally. Reading
    # it as the state of Assam hid a national scheme from every other state.
    assert N.detect_states(
        "Prime Minister's Scholarship Scheme For Central Armed Police Forces "
        "And Assam Rifles") == []
    # The real state is still detected in ordinary usage.
    assert "Assam" in N.detect_states("Post Matric Scholarship To ST Students - Assam")


def test_region_restricted_central_scheme_is_not_national():
    assert "Ladakh" in N.detect_states(
        "PM USP Special Scholarship Scheme For Jammu Kashmir And Ladakh")


def test_jammu_kashmir_without_conjunction():
    # NSP titles write "Jammu Kashmir And Ladakh"; without this alias the scheme
    # resolved to Ladakh only and J&K students never saw their own scholarship.
    got = N.detect_states("PM USP Special Scholarship Scheme For Jammu Kashmir And Ladakh")
    assert "Jammu and Kashmir" in got and "Ladakh" in got


# ------------------------------------------------- income ceiling extraction

def test_income_ceiling_real_phrasings():
    # Every string below is copied verbatim from a cached guideline PDF.
    cases = [
        ("meritorious students whose parental income is not more than { 3,50,000/- per annum", 350_000),
        ("Her/his Parents' income should not exceed Rs. 2.00 lakh per annum", 200_000),
        ("household annual income of less than Rs. 2.5 lakhs would be eligible", 250_000),
        ("Family income from all sources should not be more than Rs. 8 lakh per annum", 800_000),
        ("The family income of student from all sources should not exceed Rs.2.50 lakh", 250_000),
    ]
    for text, expected in cases:
        got, evidence = E.extract_income_ceiling(text)
        assert got == expected, f"{text!r} -> {got}, expected {expected}"
        assert evidence, "a ceiling must carry the sentence it came from"


def test_income_ceiling_ignores_award_amounts():
    # An award amount is not an income cap, and neither is a slot count.
    assert E.extract_income_ceiling(
        "Scholarship of Rs. 50,000 per annum shall be paid to each student")[0] is None
    assert E.extract_income_ceiling(
        "A total of 100000 scholarships are awarded every year")[0] is None


def test_income_ceiling_takes_the_lowest_when_several():
    # Erring low never tells a student they qualify when they do not.
    text = ("Family income should not exceed Rs. 8 lakh per annum for OBC. "
            "Family income should not exceed Rs. 2.5 lakh per annum for others.")
    assert E.extract_income_ceiling(text)[0] == 250_000


# --------------------------------------------- shared-document scheme slicing

def test_slice_by_scheme_isolates_each_scheme():
    text = (
        "GUIDELINES\n"
        "Pre Matric Scholarship for Disabilities\n"
        + "Eligibility: students of classes IX and X. " * 12 +
        "\nPost Matric Scholarship for Disabilities\n"
        + "Eligibility: students pursuing graduation. " * 12
    )
    spans = E.slice_by_scheme(text, ["Pre Matric Scholarship for Disabilities",
                                     "Post Matric Scholarship for Disabilities"])
    assert len(spans) == 2
    assert "classes IX and X" in spans["Pre Matric Scholarship for Disabilities"]
    assert "graduation" in spans["Post Matric Scholarship for Disabilities"]


def test_slice_declines_when_schemes_cannot_be_isolated():
    # No per-scheme headings -> must return nothing rather than guess a split.
    text = "General guidelines applying to several schemes. " * 30
    spans = E.slice_by_scheme(text, ["Scheme Alpha Fellowship", "Scheme Beta Fellowship"])
    assert spans == {}


# ------------------------------- OCR figures must clear a plausibility gate

def test_ocr_income_ceiling_must_be_a_standard_figure():
    """A real scan produced 'Rs 24,000', which would exclude nearly everyone."""
    from schema import Scholarship
    text = "Family income should not exceed Rs. 24,000 per annum."

    ocr = Scholarship(name="x")
    E.enrich_from_text(ocr, text * 4, low_confidence_text=True)
    assert ocr.income_ceiling_inr is None, "implausible OCR figure must be dropped"

    native = Scholarship(name="x")
    E.enrich_from_text(native, text * 4, low_confidence_text=False)
    assert native.income_ceiling_inr == 24_000, "native text is trusted as-is"


def test_ocr_income_ceiling_accepted_when_standard():
    from schema import Scholarship
    text = "Family income should not exceed Rs. 2,50,000 per annum."
    s = Scholarship(name="x")
    E.enrich_from_text(s, text * 4, low_confidence_text=True)
    assert s.income_ceiling_inr == 250_000


# ---------------------------------- Rajasthan beachhead (PRD V1 §7.3)

def test_rajasthan_title_case_keeps_acronyms_and_drops_shouting():
    import sources.rajasthan as raj
    assert raj._title_case("ECONOMIC HELP TO TRIBAL GIRLS FOR EDUCATION") == \
        "Economic Help to Tribal Girls for Education"
    # Compound acronyms must survive intact.
    assert "SC/ST" in raj._title_case("POST MATRIC SCHOLARSHIP FOR SC/ST STUDENTS")
    assert "CM" in raj._title_case("CM HIGHER EDUCATION SCHOLARSHIP SCHEME")


def test_rajasthan_bilingual_cell_split():
    import sources.rajasthan as raj
    en, hi = raj._split_bilingual(
        "CM HIGHER EDUCATION SCHOLARSHIP SCHEME मुख्यमंत्री उच्च शिक्षा छात्रवृत्ति योजना")
    assert en == "CM HIGHER EDUCATION SCHOLARSHIP SCHEME"
    assert hi.startswith("मुख्यमंत्री")


def test_rajasthan_records_claim_no_deadline_they_did_not_read():
    """The master table publishes no dates. Inventing one would be the single
    most harmful thing this parser could do."""
    import sources.rajasthan as raj
    html = """<table>
      <tr><th>Sr. No.</th><th>DEPARTMENTS NAME</th><th>SCHEMES NAME</th></tr>
      <tr><td>1</td><td>COLLEGE EDUCATION</td>
          <td>CM HIGHER EDUCATION SCHOLARSHIP SCHEME मुख्यमंत्री उच्च शिक्षा</td></tr>
      <tr><td>2</td><td>TAD</td>
          <td>ECONOMIC HELP TO TRIBAL GIRLS FOR EDUCATION जनजाति छात्राओं</td></tr>
      <tr><td>3</td><td>MINORITY</td><td>ANUPRATI SCHEME अनुप्रति योजना</td></tr>
      <tr><td>4</td><td>X</td><td>Y</td></tr>
      <tr><td>5</td><td>X</td><td>Z</td></tr>
    </table>"""
    recs = raj.parse_master(html)
    assert len(recs) >= 3
    for r in recs:
        assert r.application_deadline is None
        assert r.status == "unknown"
        assert r.states == ["Rajasthan"]
        assert r.provider_type == "state_govt"
    tad = next(r for r in recs if "Tribal" in r.name)
    assert "ST" in tad.categories          # department implies the category
    assert tad.aliases and tad.aliases[0].startswith("जनजाति")


def test_department_is_not_treated_as_eligibility():
    """Rajasthan lists Anuprati under the Minority department, but it is open to
    SC/ST/OBC/EBC/minority. Inferring category from department excluded OBC
    students from a scheme they qualify for."""
    import sources.rajasthan as raj
    html = """<table>
      <tr><th>Sr. No.</th><th>DEPARTMENTS NAME</th><th>SCHEMES NAME</th></tr>
      <tr><td>1</td><td>MINORITY</td><td>ANUPRATI SCHEME अनुप्रति योजना</td></tr>
      <tr><td>2</td><td>TAD</td><td>ECONOMIC HELP TO TRIBAL GIRLS जनजाति छात्राओं</td></tr>
      <tr><td>3</td><td>MINORITY</td><td>SCHOLARSHIP FOR MINORITY STUDENTS अल्पसंख्यक</td></tr>
      <tr><td>4</td><td>X</td><td>Y scheme</td></tr>
      <tr><td>5</td><td>X</td><td>Z scheme</td></tr>
    </table>"""
    recs = {r.name: r for r in raj.parse_master(html)}
    anuprati = next(r for n, r in recs.items() if "Anuprati" in n)
    assert anuprati.categories == [], "department must not imply a restriction"
    tribal = next(r for n, r in recs.items() if "Tribal" in n)
    assert "ST" in tribal.categories, "the scheme's own name does state ST"
    minority = next(r for n, r in recs.items() if "Minority" in n)
    assert "minority" in minority.categories


def test_tribal_in_a_name_means_st():
    assert "ST" in N.detect_categories("Economic Help to Tribal Girls")
    assert "ST" in N.detect_categories("Janjati Chhatravriti Yojana")


# ------------------------------------------------ quality gate (src/quality.py)

def test_quality_gate_withholds_page_furniture():
    import quality
    for junk in ("Overview", "Welcome", "Navigation", "Student Services",
                 "Our Scholars 2009", "अल्पसंख्यक कार्य मंत्रालय"):
        ok, reason = quality.assess({"name": junk, "official_url": "http://x",
                                     "source_name": "official"})
        assert not ok, f"{junk!r} should be withheld"
        assert reason


def test_quality_gate_keeps_real_schemes_with_unusual_names():
    """Rejecting a real scheme is worse than serving a slightly noisy catalogue:
    a withheld scheme is invisible to every student."""
    import quality
    # Descriptive name, no keyword — must survive.
    ok, _ = quality.assess({
        "name": "Opportunity Cost To Parents Of SC Girl Students - Puducherry",
        "official_url": "http://x", "source_name": "official"})
    assert ok

    # Cryptic acronym, but it came from a registry of schemes.
    ok, _ = quality.assess({"name": "PM-USPY (SSSJKL)",
                            "official_url": "http://x", "source_name": "NSP"})
    assert ok, "a row on NSP's scheme list is a scheme by construction"

    # The same cryptic name from an arbitrary crawled page is not trusted.
    ok, _ = quality.assess({"name": "PM-USPY (SSSJKL)",
                            "official_url": "http://x", "source_name": "official"})
    assert not ok


def test_quality_gate_requires_somewhere_to_send_the_student():
    import quality
    ok, reason = quality.assess({"name": "Some Big Scholarship Scheme",
                                 "source_name": "NSP"})
    assert not ok and "URL" in reason


def test_shared_pdf_shares_a_single_income_ceiling():
    """One ceiling in a shared document is one policy for every scheme in it.

    Blocking it alongside the genuinely scheme-specific fields discarded values
    the source stated plainly.
    """
    from schema import Scholarship
    one = ("ELIGIBILITY: The family income of the student from all sources "
           "should not exceed Rs. 2.50 lakh per annum. " * 3)
    s = Scholarship(name="x")
    E.enrich_from_text(s, one, shared_with=3)
    assert s.income_ceiling_inr == 250_000
    # Scheme-specific fields stay blocked.
    assert s.number_of_awards is None


def test_shared_pdf_with_conflicting_ceilings_declines():
    """Two figures means they differ per scheme, and we cannot tell which."""
    from schema import Scholarship
    two = ("Family income should not exceed Rs. 2.50 lakh per annum for Class IX. "
           "Family income should not exceed Rs. 8 lakh per annum for college. " * 3)
    s = Scholarship(name="x")
    E.enrich_from_text(s, two, shared_with=3)
    assert s.income_ceiling_inr is None


def test_income_ceiling_survives_pdf_line_wrapping():
    """PDFs wrap mid-sentence, splitting a figure from its unit.

    Real text from a scheme guideline: "...family income from all sources up to
    Rs. 8.00\nlakh per annum". Treating the newline as a sentence end left
    "Rs. 8.00" alone, which is not a plausible amount, and the ceiling vanished.
    """
    wrapped = ("a. Those SC students having total annual family income from all "
               "sources up to Rs. 8.00\nlakh per annum are eligible.")
    assert E.extract_income_ceiling(wrapped)[0] == 800_000
    assert E.distinct_income_ceilings(wrapped) == [800_000]


def test_unwrapping_keeps_paragraph_breaks():
    """Joining wrapped lines must not merge genuinely separate statements."""
    text = ("Family income should not exceed Rs. 2.50\nlakh per annum.\n\n"
            "Family income should not exceed Rs. 8\nlakh per annum for others.")
    assert E.distinct_income_ceilings(text) == [250_000, 800_000]
