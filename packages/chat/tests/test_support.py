"""suveryn-tracker#11: each citation is checked against its own passage (suveryn_chat.support)."""

import pytest
from suveryn_chat.support import citation_issues
from suveryn_engine import Calculation, Citation, SourceRef


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
