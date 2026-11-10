"""suveryn-tracker#11: each citation is checked against its own passage (suveryn_harness.support)."""

import pytest
from suveryn_harness import Calculation, Citation, SourceRef
from suveryn_harness.support import citation_issues


def passage(text: str) -> Citation:
    return Citation(text=text, source=SourceRef(document_id="doc", page=1))


SOURCES = [passage("De verkoper, de heer Jan Peeters, wonende te Evergem."),
           passage("De koopprijs bedraagt vierhonderdtienduizend euro (410.000,00 EUR), te betalen op 12 maart 2021."),
           passage("Het goed is gelegen te Evergem, Kluizendorpstraat 29, kadastraal gekend sectie A nummer 123B.")]


def issues(answer, calculations=()):
    return [(i.marker, i.n, i.item, i.found_in, i.written_as) for i in citation_issues(answer, SOURCES, list(calculations))]


@pytest.mark.parametrize("answer", [
    "De verkoper is Jan Peeters [1]. De koopprijs is 410.000 euro [2], te betalen op 12/03/2021 [2].",
    "De verkoper Jan Peeters verkoopt voor 410.000 euro [1][2].",  # several sources: their union counts
    "The seller is Jan Peeters [1].",  # an English answer about a Dutch deed: translated words aren't names
    "Dat is in Maart besproken [1].",  # month names are never names
    "De akte vermeldt geen datum.",  # nothing cited: nothing to check (the UI says so already)
    # The model's bold label names a topic from another passage: a label, not a claim (seen with Qwen on the pod).
    "1. **Ligging en Kluizendorpstraat**: de verkoper is Jan Peeters [1].",
])
def test_supported_claims_are_not_flagged(answer):
    assert issues(answer) == []


def test_a_figure_from_another_source_is_flagged_with_where_it_is():
    assert issues("De koopprijs is 410.000 euro [1].") == [(0, 1, "410.000", [2], None)]


def test_a_misspelled_name_is_flagged_with_the_sources_spelling():
    assert issues("De verkoper is Jan Peters [1].") == [(0, 1, "Peters", [1], "Peeters")]


def test_names_and_dates_from_another_source():
    assert issues("Het goed ligt in de Kluizendorpstraat [1].") == [(0, 1, "Kluizendorpstraat", [3], None)]
    assert issues("Betaling op 12 maart 2021 [3].") == [(0, 3, "12 maart 2021", [2], None)]
    assert issues("Betaling op 12/03/2021 [2].") == []  # written and numeric dates compare as dates


def test_each_claim_is_the_text_before_its_own_markers():
    """Facts before an earlier marker group belong to that group, not to the next one."""
    assert issues("Jan Peeters [1] verkoopt voor 410.000 euro [2].") == []
    assert issues("Jan Peeters [2] verkoopt voor 410.000 euro [1].") == [(0, 2, "Peeters", [1], None),
                                                                         (1, 1, "410.000", [2], None)]


def test_markers_are_counted_as_the_chat_ui_counts_them():
    """Only markers that refer to an existing citation count; markers in bold and list items count too."""
    assert issues("- **Verkoper**: Jan Peeters [1]\n- **Prijs** [9]: 410.000,00 EUR [3]") == [(1, 3, "410.000,00", [2], None)]


def test_calculation_results_and_unknown_figures_are_left_to_the_other_checks():
    calc = Calculation(expression="410.000,00 * 2", result="820.000,00", figures_not_in_sources=[])
    assert issues("Twee keer de prijs is 410.000,00 * 2 = 820.000,00 [2].", [calc]) == []
    assert issues("De prijs is 999.999 euro [1].") == []  # in no passage: unverified_figures reports it


def test_figures_in_bold_are_still_checked():
    assert issues("- **Prijs: 410.000 euro** [1]") == [(0, 1, "410.000", [2], None)]


def test_years_are_checked_against_the_cited_passage():
    """Seen on the pod: years asked for and summed; they were in their source, but years weren't checked at all."""
    sources = [passage("Opgericht in 1989 te Gent."), passage("Statuten gewijzigd op 12 maart 1996.")]
    check = lambda a: [(i.n, i.item, i.found_in) for i in citation_issues(a, sources, [])]  # noqa: E731
    assert check("Opgericht in 1989 [1], gewijzigd in 1996 [2].") == []  # also a year inside a written date
    assert check("Gewijzigd in 1996 [1].") == [(1, "1996", [2])]
    assert check("Opgericht in 1990 [1].") == [(1, "1990", [])]  # in no passage: nothing else reports years
    assert check("Zie artikel 2021 [1].") == [(1, "2021", [])]  # four digits in the year range are taken as years
    assert check("Op 12/03/1996 [2].") == []  # a full date is checked as a date, not again as a year


def test_a_date_in_the_older_notarial_form_is_read_as_a_date():
    """VM regression 9c97d76, finding 3: a passage writing the date as older deeds do ("drie en twintig maart
    negentienhonderd zes en negentig") flagged the right answer in figures."""
    sources = [passage("Verleden te Gent, op drie en twintig maart negentienhonderd zes en negentig."),
               passage("Fait à Bruxelles, le vingt-trois mars mil neuf cent nonante-six."),
               passage("Gedaan op de vijf en twintigste juni tweeduizend en drie.")]
    check = lambda a: [(i.n, i.item) for i in citation_issues(a, sources, [])]  # noqa: E731
    assert check("De akte werd verleden op 23/03/1996 [1].") == []
    assert check("L'acte date du 23 mars 1996 [2].") == []
    assert check("Ondertekend op 25 juni 2003 [3].") == []
    assert check("De akte werd verleden op 24/03/1996 [1].") != []  # a wrong day is still flagged


def _flags(answer: str, *passages: str):
    cits = [Citation(text=p, source=SourceRef(document_id=f"d{i}", page=1)) for i, p in enumerate(passages)]
    return [(i.kind, i.item, i.written_as) for i in citation_issues(answer, cits, [])]


def test_a_restated_sentence_that_differs_in_a_not_or_names_the_other_party_is_flagged():
    """Step 4 of the planted-error benchmark (10 November 2026): by rule, for a claim that restates its passage's sentence."""
    deed = "De koper mag de overeenkomst niet vroegtijdig beëindigen."
    assert _flags("De koper mag de overeenkomst vroegtijdig beëindigen [1].", deed) == [("negation", "niet", None)]
    assert _flags("De verkoper mag de overeenkomst niet vroegtijdig beëindigen [1].", deed) == [("party", "verkoper", "koper")]
    assert _flags("De koper mag de overeenkomst niet vroegtijdig beëindigen [1].", deed) == []
    assert _flags("Le vendeur peut résilier la convention avant le 15 mars 2027 [1].",
                  "Le vendeur ne peut pas résilier la convention avant le 15 mars 2027.") == [("negation", "ne peut pas", None)]
    assert _flags("L'acheteur doit verser le solde à la signature de l'acte [1].",
                  "Le vendeur doit verser le solde du prix à la signature de l'acte.") == [("party", "acheteur", "vendeur")]


def test_a_paraphrase_is_not_flagged_for_its_meaning():
    assert _flags("De koper mag de overeenkomst niet overdragen [1].", "Het is de koper verboden de overeenkomst over te dragen aan een derde.") == []
    assert _flags("De verkoper levert het huis en de garage [1].", "De verkoper levert niet alleen het huis maar ook de garage.") == []
    assert _flags("De koper mag de overeenkomst overdragen met toestemming van de verkoper [1].",
                  "De koper mag de overeenkomst niet overdragen zonder toestemming van de verkoper.") == []
    assert _flags("De koper betaalt de prijs aan de verkoper bij de akte [1].", "De verkoper ontvangt de prijs van de koper bij het verlijden van de akte.") == []
    # one of two cited passages agrees: the claim is supported
    assert _flags("De koper mag de overeenkomst vroegtijdig beëindigen [1][2].", "De koper mag de overeenkomst niet vroegtijdig beëindigen voor 2027.",
                  "Vanaf 2027 mag de koper de overeenkomst vroegtijdig beëindigen.") == []
