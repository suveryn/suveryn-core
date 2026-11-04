# Templates: from confirmed facts to a draft deed (suveryn-tracker#22)

A design note, 4 November 2026, written with the founder before anything is built. Nothing here is decided yet:
the questions at the end go to the first notary conversation, and what survives them becomes the plan. It extends
[playbooks.md](playbooks.md), where a playbook ends today with sūveryn's own summary of the confirmed facts
("products beyond the summary" and "the Word document from the office's own template" are deferred there).

## The question

A playbook gathers the facts a deed needs and a notary confirms them. The next step a notary asks for is the
deed itself: the office's wording, with this client's facts and choices in it. How far may sūveryn go towards
writing it, given that the deed is an authentic act the notary answers for, and that sūveryn's first principle is
that nothing reaches a document unseen?

The answer this note proposes: in stages, each useful on its own, each keeping one rule. **Every word of a draft
comes from the office's own text or from a confirmed fact, unless it is marked as the model's and a person has
accepted it.**

## The stages, lowest risk first

### 1. Check a draft the notary wrote

The template used the other way round: the notary drafts as today, and sūveryn compares the draft with the
confirmed facts and the office's model deed. Nothing is written by sūveryn; points to look at are shown, as the
playbook's checks are. It needs no template format, and the same comparison later checks sūveryn's own drafts.

### 2. Hand the facts to the deed software

Many offices draft in their own deed software, with its own templates, and use it for the formalities (the
repertory, registration, the central registers). sūveryn exports the confirmed facts as structured data for that
software to merge. The office keeps the tool it trusts; sūveryn takes no responsibility for the deed's wording.
Which formats offices' software accepts is a question for the notary.

### 3. Fill the office's model deed

The office's deed with the parts that change per client marked:

- **fill-ins:** a fact by its path (`principals[1].name`, `disposal_threshold`);
- **repeats:** one passage per entry of a list (an agent, a founder);
- **alternatives:** one passage per option of a choice (`gift_power`: the gift clause, or the sentence that there
  is none), picked by the confirmed value.

The filling is mechanical, by the server. Amounts and dates are written the notarial way ("vijfduizend euro
(€ 5.000,00)", "het jaar tweeduizend zesentwintig") by fixed rules per language, never by the model. The draft is
a Word file in the case's documents, made by sūveryn (never a source, `originKind`), marked out of date when a
fact it used changes. A final step of the playbook (`produce` with the office's template) makes it, after the
checkpoint.

### 4. The model proposes edits, marked

On top of the filled model deed the model may propose edits, within a fixed scope:

- agreement: he or she, one principal or two, one agent or several (where templates fail and deeds show "zijn/haar");
- the client's own wishes put into clause language (the wishes about living and care in a care mandate);
- picking or combining variants where the choices call for it.

The server, not the model, marks the edits: it compares the model's text with the filled model deed and sorts
every difference.

- **Fact:** a changed span that is a confirmed fact's value is shown as that fact, linked, already checked.
- **Model edit:** everything else is shown in teal, with the model's reason ("plural: two agents"); deletions are
  struck through. Each one is accepted or rejected by a person.
- A draft with an unresolved edit can't be marked final, as a run can't pass its checkpoint unconfirmed.

In the Word file the model's edits are tracked changes under the author "sūveryn", not coloured text: notaries
work with tracked changes, and they can't stay in a final deed unnoticed, which a colour can.

A model that wrote without a base text would write legal clauses from its training, which a notary can't rely on;
it is never given a blank page.

## When the office has no deed software

Then sūveryn is the drafting tool, and the base text matters more. In order of preference:

1. **The office's model deed per type**, made once from its own past deeds (below) and approved by the notary,
   with every client's details taken out. The safest base.
2. **The closest past deed** of that type, until there is a model deed. It works, but it is another client's deed.
3. **A reference model deed in the pack**, written or licensed through a partner notary, for an office with no
   deeds of that type yet.

One rule is hard here, whichever base is used: **nothing of another client survives.** Before a draft can be marked
final, every name, register number, address, date and amount in it is compared with this case's confirmed facts;
one that isn't among them blocks the draft until a person resolves it. Starting from the office's model deed
rather than a past deed avoids the risk at the source, and spares a colleague who drafts a new deed access to
other clients' cases.

What stays outside sūveryn either way: signing, the repertory number, registration and its duties, and the
registration in the central registers. sūveryn prepares the text.

## Making templates cheaply, and keeping them right

- **From past deeds.** An office has many deeds of each type. Given five to ten, sūveryn proposes the model deed:
  what they share is fixed text, what differs is a fill-in, a repeat or an alternative. The notary reviews it once.
  It also brings the alternative clauses one deed alone never shows. It runs on the office's appliance, on its own
  documents, like any reading.
- **Every variant read once.** Before a template is used, sūveryn fills it for every combination of the choices
  that changes the deed's structure, for a fictional client (as the trap deed is fictional), and the notary reads
  them once. A broken alternative is found then, not in a client's deed.
- **Each clause with its version, source and legal basis.** Where it comes from (the office, or a model-deed
  service under licence), the article it rests on, when a notary last reviewed it. When the law changes, sūveryn
  lists the templates and the open drafts that use an affected clause.
- **The languages aligned.** A clause is paired across Dutch and French, so a variant chosen in one is the same in
  the other, and a change to one shows the other needs it too.

The office's clauses are the office's (or its model-deed service's). Templates are uploaded by an office to its own
appliance; a pack ships at most a reference model deed whose wording sūveryn may use.

## Applied to the two notarial playbooks

### Care mandate (zorgvolmacht, `playbook/be-notary/care-mandate`)

- **From past deeds:** a good first candidate. One office's care mandates are uniform, and what varies follows the
  playbook's choices: when it takes effect, the gift clause, the powers over the person, the signatures, the
  threshold.
- **Checks on a draft:** every agent and successor with the confirmed name and register number; the threshold as
  confirmed; no gift clause when there is no power to give; a clause on proving incapacity when it waits for
  incapacity; no clauses on the person when it covers only the assets; the registration in the central register of
  mandates and the notice on conflicting interests present; the statement that the agents are family
  administrators only when every agent's bond says so.
- **Variants:** about a dozen that change the structure (start, scope, gift power, trusted person, signatures).
- **Clauses to watch:** the family-administrator statement depends on the law of 8 November 2023 (its professional
  obligations from 1 September 2027) and on a bill of 28 October 2026 that would lift the distinction for care
  mandates.
- **Language:** usually the principal's.
- **Order:** checks, then drafts. Short and uniform, it is the place to try the model's marked edits first.

### Company formation (Foundation, `playbook/be-notary/company-formation`)

- **From past deeds:** longer: the articles of association are most of the deed. Past deeds separate the standard
  articles from the variable ones (object, contribution, one or several directors, representation, financial
  year, general meeting) and the passages on a contribution in kind from those on cash.
- **Checks on a draft:** the shares in the articles are the shares issued, and the founders' add up; the
  contribution is the certified amount; seat, object, financial year and meeting as confirmed; directors and
  representation as confirmed; the auditor's report mentioned when there is a contribution in kind. Most are the
  playbook's checks again, run on the draft's text.
- **Variants:** cash, in kind or mixed, by one founder or several, by one director or a board: about a dozen.
- **Clauses to watch:** the Code of Companies and Associations; the financial plan, the auditor's report and the
  standard articles follow its changes.
- **Language:** the articles' language follows the region of the registered office, not the notary's preference.
- **Order:** checks and the export first; drafts later, as the articles are long and every office has its own.

## Questions for the notary

1. What does the office draft in, and what could it take in (a format, a merge)?
2. Would a check of a draft already help, before any drafting?
3. Five to ten past deeds of one type, on the office's appliance, to propose a model deed: acceptable?
4. Who owns the office's clauses: the office, or a model-deed service under licence?
5. For the care mandate: the threshold's usual amount and whether it has a default; how the agents' bond with the
   principal is recorded; whether the statement of preference for an administrator belongs in the same deed.
6. For the company formation: which articles vary between clients, which never do.
7. Tracked changes in Word, or another way to see the model's edits?

## What is not proposed

- A model writing a deed without a base text.
- Coloured text as the only mark of the model's edits in the Word file.
- sūveryn doing the formalities: signing, the repertory, registration, the central registers.
- Templates shipped in a pack under wording sūveryn has no right to.
