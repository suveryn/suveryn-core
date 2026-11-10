"""The documents of the long deed-intake run (deed-intake-long.json): a sale file of real length, fictional.

A private sale agreement of seven pages and the sellers' title deed of 1998, twenty-five pages, together far
longer than one reading takes (the whole-document budget, docs/architecture.md): the read sees their best-matching
passages, and says so. Every name, number, address and amount is made up.

Traps:
- the title deed is an earlier sale of the same house: other sellers, other buyers (today's sellers), a price in
  Belgian francs and the parcel's number before it was split (412H, today 412K). None of it is today's sale;
- the agreement mentions an earlier asking price that is not the price;
- the deposit, the deadline and the occupancy sit late in the agreement, after its general conditions;
- the deed's deadline is a term ("within four months of the signing"), worked out from the agreement's date.
"""

from __future__ import annotations

import random
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

FONT = Path("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf")

AGREEMENT = "compromis-kerkweg-41.pdf"
TITLE_DEED = "eigendomstitel-1998.pdf"
CERTIFICATES = "attesten-kerkweg-41.pdf"


def _pdf(path: Path, title: str, blocks: list[str | None]) -> Path:
    """A born-digital PDF: a title, then paragraphs; None starts a new page."""
    styles = getSampleStyleSheet()
    body, head = styles["BodyText"], styles["Heading2"]
    if FONT.exists():
        pdfmetrics.registerFont(TTFont("Fictional", str(FONT)))
        body.fontName = head.fontName = "Fictional"
    story: list = [Paragraph(title, head), Spacer(1, 8)]
    for block in blocks:
        if block is None:
            story.append(PageBreak())
        elif block.startswith("## "):
            story += [Paragraph(block[3:], head), Spacer(1, 4)]
        else:
            story += [Paragraph(block, body), Spacer(1, 6)]
    path.parent.mkdir(parents=True, exist_ok=True)
    SimpleDocTemplate(str(path), pagesize=A4, title=title).build(story)
    return path


# ------------------------------------------------------------------ general conditions, shared in spirit by both deeds

# Original wording, written for this test: general clauses of the kind every Belgian deed of sale carries. None is
# a fact the playbook asks for; together they are the bulk a reader has to get through.
CLAUSES = [
    ("Staat van het goed", "Het goed wordt verkocht in de staat waarin het zich bevindt, goed gekend door de koper, die "
     "verklaart het te hebben bezichtigd. De verkoper staat niet in voor zichtbare of verborgen gebreken, tenzij hij die "
     "kende en ze niet heeft meegedeeld. Verschillen in oppervlakte, ook al bedragen ze meer dan een twintigste, geven "
     "geen aanleiding tot verhoging of vermindering van de prijs."),
    ("Erfdienstbaarheden", "De koper neemt het goed over met alle zichtbare en verborgen, voortdurende en niet-voortdurende "
     "erfdienstbaarheden die het kunnen bezwaren of bevoordelen. Hij kan die op eigen kosten en risico doen gelden of zich "
     "ertegen verzetten, zonder tussenkomst van de verkoper en zonder verhaal op hem."),
    ("Gemene muren", "De muren die het goed scheiden van de aanpalende eigendommen worden verkocht met de rechten die "
     "eraan verbonden zijn. Er is geen vergoeding verschuldigd voor de gemeenheid van muren, behalve wat hierna wordt "
     "bepaald. De koper treedt in alle rechten en plichten van de verkoper ten aanzien van de buren."),
    ("Verzekering", "De verkoper verklaart dat het goed verzekerd is tegen brand en aanverwante risico's. De koper zorgt "
     "zelf voor de verzekering vanaf de eigendomsoverdracht. De verkoper blijft verantwoordelijk voor de risico's tot op "
     "die dag, ook bij overmacht."),
    ("Nutsvoorzieningen", "De meters en de contracten voor water, gas, elektriciteit en telecommunicatie worden door de "
     "koper overgenomen op de dag van de ingenottreding. De meterstanden worden samen opgenomen. De kosten van de "
     "overname van de contracten zijn voor de koper."),
    ("Belastingen", "De onroerende voorheffing van het lopende jaar wordt tussen partijen verdeeld naar rata van de tijd "
     "dat elk van hen het genot van het goed heeft gehad. Alle andere belastingen en heffingen op het goed zijn voor de "
     "koper vanaf de ingenottreding."),
    ("Stedenbouw", "Er werd voor het goed geen stedenbouwkundige vergunning afgeleverd die nog niet werd uitgevoerd. Het "
     "goed is niet getroffen door een rooilijnplan, een onteigeningsbesluit of een voorkooprecht, voor zover de verkoper "
     "weet. Er werd geen bouwmisdrijf vastgesteld. De koper verklaart de stedenbouwkundige inlichtingen te hebben "
     "ontvangen."),
    ("Bodem", "De verkoper verklaart dat er op het goed, voor zover hij weet, geen risico-inrichting gevestigd is of was. "
     "Het bodemattest werd aan de koper meegedeeld voor de ondertekening van deze overeenkomst. De koper verklaart de "
     "inhoud ervan te kennen."),
    ("Overstromingsgevoeligheid", "Het goed ligt niet in een effectief of mogelijk overstromingsgevoelig gebied en niet in "
     "een afgebakend overstromingsgebied of oeverzone, volgens de kaarten die op de dag van de ondertekening beschikbaar "
     "waren. De watertoets werd geraadpleegd."),
    ("Elektrische installatie", "De elektrische installatie werd onderzocht. Het proces-verbaal werd aan de koper "
     "overhandigd. De koper is ertoe gehouden de vastgestelde inbreuken te laten herstellen binnen achttien maanden na de "
     "akte en daarna een nieuw onderzoek te laten uitvoeren."),
    ("Stookolietank", "Er bevindt zich geen ondergrondse stookolietank op het goed. Een bovengrondse tank van minder dan "
     "vijfduizend liter werd buiten gebruik gesteld en gereinigd. Het attest daarvan wordt bij de akte gevoegd."),
    ("Postinterventiedossier", "Voor de werken die na 1 mei 2001 werden uitgevoerd, overhandigt de verkoper het "
     "postinterventiedossier aan de koper uiterlijk bij de akte. De koper verklaart het te zullen bewaren en bij een "
     "latere overdracht aan de volgende eigenaar te zullen geven."),
    ("Asbest", "De verkoper overhandigt het asbestinventarisattest aan de koper uiterlijk bij de akte. De koper neemt "
     "kennis van de aanbevelingen die erin staan en verklaart niet te zullen opkomen tegen de verkoper voor wat erin "
     "werd vermeld."),
    ("Hypothecaire toestand", "Het goed wordt verkocht voor vrij en onbelast van alle schulden, voorrechten, hypotheken "
     "en inschrijvingen. De verkoper verbindt zich ertoe de bestaande inschrijvingen op eigen kosten te laten doorhalen, "
     "zo nodig met de verkoopprijs."),
    ("Kosten", "Alle kosten, rechten en erelonen van de akte zijn voor rekening van de koper, behalve de kosten van "
     "doorhaling van inschrijvingen en de kosten van de attesten die de verkoper moet voorleggen, die voor rekening van "
     "de verkoper zijn."),
    ("Woonstkeuze", "Voor de uitvoering van deze overeenkomst kiezen partijen woonst in hun woonplaats hierboven vermeld. "
     "Elke kennisgeving gebeurt per aangetekende brief of per e-mail met ontvangstbevestiging."),
    ("Ontbinding", "Indien een partij haar verplichtingen niet nakomt, kan de andere partij, na ingebrekestelling die "
     "vijftien dagen zonder gevolg blijft, ofwel de uitvoering vorderen, ofwel de ontbinding met schadevergoeding van tien "
     "ten honderd van de prijs."),
    ("Bemiddeling", "Partijen verklaren dat de verkoop tot stand kwam zonder bemiddeling van een vastgoedmakelaar, of dat "
     "de vergoeding van de makelaar door de verkoper wordt gedragen. Er is geen andere commissie verschuldigd."),
    ("Bevoegdheid", "Elk geschil over deze overeenkomst wordt voorgelegd aan de rechtbanken van het arrondissement waar "
     "het goed gelegen is. Het Belgisch recht is van toepassing."),
    ("Taal", "Partijen verklaren de Nederlandse taal machtig te zijn en deze overeenkomst in die taal te hebben gelezen "
     "en begrepen. Zij hebben een ontwerp ervan ten minste vijf werkdagen voor de ondertekening ontvangen."),
]


def _clauses(rng: random.Random, first: int, count: int, flavour: str) -> list[str]:
    """``count`` numbered clauses from CLAUSES, each with a sentence of its own so no two pages read alike."""
    out = []
    for i in range(count):
        title, text = CLAUSES[(i + first) % len(CLAUSES)]
        day, month = rng.randint(1, 28), rng.choice(["januari", "maart", "mei", "juli", "september", "november"])
        extra = (f" Deze bepaling werd in het {flavour} opgenomen op verzoek van partijen en besproken op {day} {month}; "
                 f"zij doet geen afbreuk aan artikel {rng.randint(1, 40)} van de bijzondere voorwaarden.")
        out.append(f"<b>Artikel {first + i + 1}. {title}.</b> {text}{extra}")
    return out


# ------------------------------------------------------------------ today's agreement (2026): the facts

def _agreement(rng: random.Random) -> list[str | None]:
    return [
        "<b>Tussen ondergetekenden.</b>",
        "1. De heer Marc Veldhoek, geboren te Testdorp op 3 maart 1961, rijksregisternummer 61.03.03-123.45, en zijn "
        "echtgenote mevrouw Ingrid Lammens, geboren te Proefbeke op 19 juli 1963, rijksregisternummer 63.07.19-234.56, "
        "samen wonende te 9999 Testdorp, Kerkweg 41. Hierna samen de verkoper.",
        "2. De heer Tom Akkerman, geboren te Proefbeke op 8 februari 1990, rijksregisternummer 90.02.08-345.67, en "
        "mevrouw Lien Dewaal, geboren te Testdorp op 27 oktober 1991, rijksregisternummer 91.10.27-456.78, samen "
        "wonende te 9998 Proefbeke, Molenstraat 7. Hierna samen de koper.",
        "Werd het volgende overeengekomen.",
        "## Beschrijving van het goed",
        "De verkoper verkoopt aan de koper, die aanvaardt, het volgende goed: een woning met tuin en garage, gelegen te "
        "9999 Testdorp, Kerkweg 41, gekend ten kadaster Testdorp, eerste afdeling, sectie B, nummer 412K, met een "
        "oppervlakte volgens kadaster van 6 are 12 centiare.",
        "Het perceel 412K is ontstaan uit de splitsing van het vroegere perceel 412H in 2009; het afgesplitste deel, "
        "nummer 412L, behoort niet tot de verkoop.",
        "## Oorsprong van eigendom",
        "De verkoper is eigenaar van het goed door aankoop, bij akte verleden voor notaris Jan Desmedt te Proefbeke op "
        "14 april 1998, overgeschreven op het hypotheekkantoor te Testdorp.",
        None,
        *_clauses(rng, 0, 8, "compromis"),
        None,
        "## Prijs",
        "Het goed werd door de verkoper eerder te koop gesteld voor EUR 395.000,00. Na onderhandeling komen partijen "
        "het volgende overeen.",
        "De verkoop wordt toegestaan en aanvaard voor de prijs van driehonderdachtenzestigduizend vijfhonderd euro "
        "(EUR 368.500,00).",
        *_clauses(rng, 8, 8, "compromis"),
        None,
        "## Opschortende voorwaarde",
        "De verkoop gebeurt onder de opschortende voorwaarde dat de koper een hypothecaire lening van EUR 290.000,00 "
        "verkrijgt, binnen zes weken na de ondertekening van deze overeenkomst. Verkrijgt de koper de lening niet binnen "
        "die termijn, dan meldt hij dat aan de verkoper met een weigeringsattest van twee kredietinstellingen.",
        *_clauses(rng, 16, 4, "compromis"),
        "## Waarborg",
        "Bij de ondertekening betaalt de koper een waarborg van zesendertigduizend achthonderdvijftig euro "
        "(EUR 36.850,00) op de derdenrekening van notaris Els Pieters te Testdorp, die hem bewaart tot de akte.",
        "## Akte en ingenottreding",
        "De authentieke akte wordt verleden binnen vier maanden na de ondertekening van deze overeenkomst, voor notaris "
        "Els Pieters te Testdorp.",
        "De koper krijgt het genot van het goed bij het verlijden van de akte. Het goed is dan vrij van gebruik en "
        "bewoning: de verkoper verklaart dat het niet verhuurd is en dat hij het uiterlijk een week voor de akte "
        "ontruimt.",
        "## Attesten",
        "Het energieprestatiecertificaat nummer 20260611-0003141-RES-1 vermeldt een energiescore van 287 kWh/m² per "
        "jaar, label C. Het bodemattest nummer 2026-0815-77 van 15 augustus 2026 vermeldt dat er geen gegevens over de "
        "grond beschikbaar zijn.",
        "Opgemaakt te Testdorp op 12 september 2026, in drie exemplaren, waarvan elke partij erkent het hare te hebben "
        "ontvangen.",
    ]


# ------------------------------------------------------------------ the title deed (1998): an earlier sale, the traps

OWNERS = [("Petrus Vandamme", 1931), ("Maria Vandamme-De Lille", 1952), ("Paul en Rita Vandamme", 1979)]


def _title_deed(rng: random.Random) -> list[str | None]:
    blocks: list[str | None] = [
        "Het jaar negentienhonderd achtennegentig, op veertien april. Voor ons, meester Jan Desmedt, notaris te "
        "Proefbeke.",
        "<b>Zijn verschenen.</b> De heer Paul Vandamme, wonende te 9997 Oudland, Stationsstraat 3, en mevrouw Rita "
        "Vandamme, wonende te 9997 Oudland, Beekstraat 15, hierna samen de verkoper.",
        "Die verklaren te verkopen aan de heer Marc Veldhoek en zijn echtgenote mevrouw Ingrid Lammens, samen wonende "
        "te 9998 Proefbeke, Nieuwstraat 22, hierna samen de koper, die aanvaarden, het volgende goed.",
        "## Beschrijving van het goed",
        "Een woning met tuin, gelegen te Testdorp, Kerkweg 41, gekend ten kadaster Testdorp, eerste afdeling, sectie "
        "B, nummer 412H, met een oppervlakte van 6 are 40 centiare.",
        "## Oorsprong van eigendom",
    ]
    for name, year in OWNERS:
        blocks.append(
            f"Oorspronkelijk behoorde het goed toe aan {name}, die het verkreeg in {year} door "
            f"{rng.choice(['aankoop', 'erfopvolging', 'schenking'])}, bij akte verleden voor notaris "
            f"{rng.choice(['Verhaeghe', 'Cools', 'Baert', 'Maes'])} te {rng.choice(['Oudland', 'Testdorp', 'Proefbeke'])}. "
            f"De akte werd overgeschreven op het hypotheekkantoor te Testdorp, boek {rng.randint(1000, 9999)}, nummer "
            f"{rng.randint(1, 99)}. Er werden toen geen bijzondere voorwaarden opgelegd die vandaag nog gelden, behalve "
            f"wat hierna onder de erfdienstbaarheden wordt vermeld.")
    blocks.append(None)
    for chapter in range(1, 11):
        blocks.append(f"## Hoofdstuk {chapter}. Algemene voorwaarden")
        blocks += _clauses(rng, chapter * 5, 9, "lastenkohier van 1998")
        blocks.append(None)
    blocks += [
        "## Prijs",
        "De verkoop wordt toegestaan en aanvaard voor de prijs van vier miljoen tweehonderdvijftigduizend frank "
        "(BEF 4.250.000), die de verkoper verklaart te hebben ontvangen van de koper, waarvoor kwijting.",
        "## Erfdienstbaarheden",
        "Ten voordele van het aanpalende perceel 413 bestaat een recht van doorgang van drie meter breed langs de "
        "oostelijke grens, voor voetgangers en fietsers, gevestigd bij akte van 1952.",
        *_clauses(rng, 3, 12, "lastenkohier van 1998"),
        None,
        "## Fiscale verklaringen",
        *[f"De verkoper verklaart dat {line}" for line in (
            "hij geen btw-plichtige is en dat de verkoop niet onder de btw valt.",
            "er op het goed geen andere belasting verschuldigd is dan de onroerende voorheffing van het lopende jaar.",
            "hij niet in staat van faillissement verkeert en geen collectieve schuldenregeling heeft aangevraagd.",
            "het goed niet het voorwerp uitmaakt van een beslag of een lopende procedure.",
        )],
        *_clauses(rng, 11, 10, "lastenkohier van 1998"),
        "Waarvan akte, verleden te Proefbeke, op datum als voormeld. Na voorlezing hebben partijen met ons, notaris, "
        "getekend.",
    ]
    return blocks


def _certificates() -> list[str | None]:
    return [
        "## Energieprestatiecertificaat",
        "Certificaat nummer 20260611-0003141-RES-1, opgemaakt op 11 juni 2026 voor de woning Kerkweg 41, 9999 "
        "Testdorp. Energiescore: 287 kWh/m² per jaar. Label: C.",
        "## Bodemattest",
        "Bodemattest nummer 2026-0815-77, afgeleverd op 15 augustus 2026 voor het perceel Testdorp, eerste afdeling, "
        "sectie B, nummer 412K. Over deze grond zijn geen gegevens beschikbaar.",
    ]


def build_documents(folder: Path) -> None:
    rng = random.Random(41)  # the same documents every time
    _pdf(folder / AGREEMENT, "Onderhandse verkoopovereenkomst", _agreement(rng))
    _pdf(folder / TITLE_DEED, "Akte van verkoop van 14 april 1998", _title_deed(rng))
    _pdf(folder / CERTIFICATES, "Attesten bij de verkoop van Kerkweg 41", _certificates())
