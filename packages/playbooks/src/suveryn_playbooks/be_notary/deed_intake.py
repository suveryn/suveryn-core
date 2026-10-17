"""Deed intake for a Belgian sale (``playbook/be-notary/deed-intake``, docs/design/playbooks.md).

The facts a notarial deed of sale needs, read from the case's uploaded documents (the private sale
agreement, the earlier title deed, the certificates) and checked by a person at the checkpoint.
Thirteen facts, no more: every fact is a line the notary has to check.
"""

from .. import Fact, Playbook

FACTS = (
    Fact("sellers", "the selling party or parties, as named in the agreement (full names as written)"),
    Fact("buyers", "the buying party or parties (full names as written)"),
    Fact("property", "the property sold: its address and description"),
    Fact("cadastral", "the cadastral identification of the property: municipality, division, section, number"),
    Fact("price", "the sale price", "amount"),
    Fact("deposit", "the advance or guarantee paid at signing, and to whom it was paid", "amount"),
    Fact("agreement_date", "the date the private agreement was signed", "date"),
    Fact("deed_deadline", "the date by which the notarial deed must be signed", "date"),
    Fact("conditions", "the suspensive conditions (financing, permits, other), each with its term"),
    Fact("title", "the seller's title: the earlier deed, its date and the notary who passed it"),
    Fact("epc", "the energy performance certificate: its reference and result"),
    Fact("soil", "the soil certificate: its reference and conclusion"),
    Fact("occupancy", "the occupancy at delivery: free, let or occupied, and by whom"),
)

INSTRUCTIONS = (
    "You are preparing the intake of a sale for a notarial deed. Read the excerpts and fill in the "
    "table below: one row per fact, in this order, with the fact's id in the first column exactly as "
    "given, the value in the second column, copied as the documents write it (names, amounts, dates, "
    "references), and in the third column the excerpt numbers the value comes from, as [n]. A fact "
    "the excerpts do not contain gets an empty second column and an empty third column: never guess, "
    "never fill in from general knowledge. Answer with the table only, no text before or after it, "
    "in the language of the documents.\n\n"
    "| id | value | source |\n|---|---|---|\n"
)

LABELS = {
    "en": {"sellers": "Seller(s)", "buyers": "Buyer(s)", "property": "Property", "cadastral": "Cadastral data",
           "price": "Price", "deposit": "Advance or guarantee", "agreement_date": "Agreement signed on",
           "deed_deadline": "Deed to be signed by", "conditions": "Suspensive conditions", "title": "Title",
           "epc": "Energy certificate", "soil": "Soil certificate", "occupancy": "Occupancy at delivery"},
    "nl": {"sellers": "Verkoper(s)", "buyers": "Koper(s)", "property": "Goed", "cadastral": "Kadastrale gegevens",
           "price": "Prijs", "deposit": "Voorschot of waarborg", "agreement_date": "Compromis getekend op",
           "deed_deadline": "Akte te verlijden tegen", "conditions": "Opschortende voorwaarden", "title": "Eigendomstitel",
           "epc": "Energieprestatiecertificaat", "soil": "Bodemattest", "occupancy": "Bewoning bij levering"},
    "fr": {"sellers": "Vendeur(s)", "buyers": "Acquéreur(s)", "property": "Bien", "cadastral": "Données cadastrales",
           "price": "Prix", "deposit": "Acompte ou garantie", "agreement_date": "Compromis signé le",
           "deed_deadline": "Acte à passer pour le", "conditions": "Conditions suspensives", "title": "Titre de propriété",
           "epc": "Certificat PEB", "soil": "Attestation du sol", "occupancy": "Occupation à la délivrance"},
}

DEED_INTAKE = Playbook(
    id="playbook/be-notary/deed-intake",
    pack="pack/be-notary",
    version="1.0",
    name="Deed intake",
    case_types=("sale",),
    facts=FACTS,
    instructions=INSTRUCTIONS + "".join(f"| {f.id} | | |\n" for f in FACTS),
    languages=LABELS,
)
