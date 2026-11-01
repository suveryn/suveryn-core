"""A question that names one document reads only that one (VM regression 03c8f74, question 2; Filip, 1 November 2026)."""

from suveryn_rag.naming import kinds_in, language_of, named_document

DOCS = {
    "poa-fr": ("46. Power of Attorney (FR) - final execution version.pdf", "Le soussigné donne procuration à la société pour"),
    "poa-nl": ("Volmacht Algemene Vergadering.pdf", "De ondergetekende geeft volmacht aan de voorzitter van de vergadering om"),
    "issue": ("Uitgifte_2150512.pdf", "Het jaar tweeduizend en de vennootschap van de"),
    "care": ("zvlm Van der Linden.docx", "De zorgvolmacht van de lastgever voor het beheer van zijn goederen"),
    "sha": ("Company - SHA - Final.pdf", "This agreement shall be governed by the laws of Belgium and any"),
    "warrant": ("Warrantovereenkomst 24032017.pdf", "De warranthouder heeft het recht om aandelen te verwerven van de"),
}


def test_a_named_kind_and_language_narrow_to_the_one_document_that_fits():
    assert named_document("Wie geeft de Franstalige volmacht, en aan wie?", DOCS) == "poa-fr"
    assert named_document("Wat zegt de aandeelhoudersovereenkomst over een goede leaver?", DOCS) == "sha"
    assert named_document("Wat bepaalt de zorgvolmacht?", DOCS) == "care"   # not the powers of attorney
    assert named_document("Wat zegt de warrantovereenkomst over de prijs?", DOCS) == "warrant"


def test_nothing_is_narrowed_when_several_fit_or_the_question_names_no_document():
    assert named_document("Wie geeft een volmacht?", DOCS) is None        # two powers of attorney: search them all
    assert named_document("Hoeveel warrants werden uitgegeven?", DOCS) is None  # what it asks about, not which file
    assert named_document("Wat is het kapitaal?", DOCS) is None
    assert named_document("Wat zegt de warrantovereenkomst?", {"warrant": DOCS["warrant"]}) is None  # one document: nothing to narrow


def test_a_documents_kind_and_language_come_from_its_name_and_its_own_words():
    assert kinds_in("zvlm Van der Linden.docx", in_file_name=True) == {"care_mandate"}
    assert kinds_in("Warrantovereenkomst 24032017.pdf", in_file_name=True) == {"warrant"}
    assert language_of("", "Power of Attorney (FR).pdf") == "fr"
    assert language_of("De ondergetekende geeft volmacht aan de voorzitter van de vergadering om het een en ander te doen voor de "
                       "vennootschap met de leden die niet aanwezig zijn bij deze") == "nl"
