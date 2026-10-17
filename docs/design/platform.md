# The platform: capabilities, profession packs, playbooks, connectors

A design note, October 2026, written after two outside reviews of the repositories and a
discussion of what "features, playbooks and connectors" (the [manifesto](https://github.com/suveryn/suveryn-docs/blob/main/MANIFESTO.md))
mean once they have to be built. It records decisions, not code: `packages/mcp-host`,
`packages/connectors` and `packages/playbooks` are still placeholders, and this note says what
has to be known before they stop being placeholders. What exists today is in
[architecture.md](../architecture.md); cases are in [cases.md](cases.md).

## The four layers

The manifesto's three words are business language. As an architecture there are four layers,
and the one that isn't in the manifesto is the one that holds the other three together.

| Layer | What it is | Who makes it | Ships how |
|---|---|---|---|
| **Capabilities** | What every office gets and what works with nothing installed on top: asking, answers grounded in documents with checked citations, server-side calculations, export, cases with members, closing and the keep period, the access log, usage | Sūveryn, in the open core | With every release of the platform; never sold separately |
| **The case and what is in it** | The container (cases.md): members and roles, open or closed, the keep period, the access log; its documents with their origin; the facts read from them (suveryn-tracker#27); the named subject fields of its type (#29); the playbook runs in it (#28) | The core defines the shape; a profession pack fills in the case types, their subject fields and their keep periods | With the platform (the shape) and with the pack (the content) |
| **Playbooks** | Declarative recipes for one profession's kind of work: steps, prompts, templates, checkpoints where a person confirms, tool calls; each run is a record in its case | Sūveryn, and certified partners | Signed content in a profession pack; proprietary content on the open core is allowed and intended |
| **Connectors** | Doors to other systems: documents in, and (only from a playbook step) data out to a declared destination | Sūveryn, and certified partners | Signed, sandboxed, with an egress declaration; off until an office switches one on |

The rule that keeps "capabilities" from swallowing everything: a capability works for any
profession with no pack installed; a playbook encodes how one profession does one job and uses
capabilities to do it. Generating a Word document is a capability; drafting a deed from an
intake is a playbook that ends in one.

## The case is the container, not the state machine

A reviewer proposed making the case record the typed contract everything sits on, with stages
and a state model. The cases design decided otherwise (decision 9: open or closed, and nothing
else; deadlines and stages live in the practice software and would disagree), and that holds.
A playbook is a state machine over its own **run**, keyed by `case_id`: it reads the case's
documents and facts, pauses at checkpoints, and writes its results back as documents with
origin `playbook`. The case stays what it is, and a playbook's progress is in the run. Three
things the reviewer was reaching for are real and are already on the tracker, next to the case
rather than inside it: the subject fields per case type (#29), the facts layer (#27), and the
playbook run with its checkpoints (#28).

## Profession packs

Sūveryn is for confidentiality-bound professions, plural: notaries first, then lawyers,
healthcare, government units. The unit that makes the platform fit one of them is a
**profession pack**, identified by profession and jurisdiction (`be-notary`, `be-lawyer`,
`nl-notary`): a deed-intake playbook for Belgium is wrong in the Netherlands, and the law
behind a keep period differs per country. A pack contains:

- the case types with their named subject fields (#29) and their vocabulary in the three languages;
- the keep periods the office may choose from, with the legal basis the pack assumes (the
  current list, six months to five years or manual, is notary-sized; medical records are kept
  for decades, lawyers' files for years after a matter ends: the list is the pack's, not the core's);
- which **access model** the pack uses (see below);
- its playbooks and its connectors, signed.

Several packs can be installed on one appliance (a law firm with a notarial department).

What is profession-neutral today, and what isn't:

- Neutral: the case and the personal space, members and roles, the two access defaults
  (office-wide for notaries, where all staff share one secrecy; members only for law firms with
  conflict walls, healthcare, government), closing and the keep period, the access log, case
  types as data.
- Not yet: the keep-period list (above); the example case types, demo values and some wording,
  which speak notary (cosmetic, and the pack mechanism fixes it); and the access model, which is
  one model, the notarial one.

**Access models.** "Member of the case" is the notary's and the lawyer's idea. In healthcare
the right to open a record follows from a treating relationship, with break-glass access in an
emergency that must be logged and reviewed afterwards; government units have classification
levels. `cases.may` covers the first; it does not cover the other two, and this note says so
rather than pretending. The intended posture: the core supports a small set of access models,
each pack declares which one it uses, and the notarial one never becomes the platform's
implicit default. The access log is the foundation for all of them. Nothing of this is built
until a second pack is.

## Connectors are the most security-critical component

The product's promise is that nothing leaves the building, and the appliance enforces it at the
network level ([network-mode](https://github.com/suveryn/suveryn-appliance/blob/main/network-mode/README.md):
approved destinations, the egress rules, the resolver; air-gapped mode). A connector is a hole
in that wall by construction, so it gets more discipline than the core, not less. The shape
already exists in the repository: an uploaded PDF is untrusted input opened in an isolated
process with a JSON-only protocol, a secret-stripped environment and no core dumps
(`suveryn_rag.isolation`). A connector is untrusted input, untrusted code and an outbound
channel, and is treated as all three:

1. **Sandboxed adapters only.** Never third-party code in the gateway process. A connector runs
   as a separate process behind the same kind of boundary as the reader.
2. **An egress declaration**, signed with the connector: "sends these fields to this system".
   The appliance turns it into an egress rule, so the connector can reach that destination and
   no other; the office sees the declaration and agrees to it, per connector, before the rule
   is written (the web setup or the dashboard).
3. **Data, never instructions.** What comes back through a door enters a prompt the way
   retrieved passages do (`suveryn_chat.grounding`: excerpts framed as data, the reminder near
   the question, control tokens neutralised, instruction-like content audited). The audit
   extends to connector output.
4. **Off by default**, per pack, per office; every use logged in the case's access log.
5. **Not all doors are the same.** A door that only brings documents in (mail, a file share) is a
   capability of the edition. A door that sends client data out is a pack-level connector with
   a declaration, a partner agreement and, in healthcare, possibly an accreditation from the
   national platform. The promise then reads "nothing leaves except what you explicitly
   allowed, and here is the list"; that sentence is written here before marketing writes the
   other one.
6. **Which connectors can exist on an air-gapped appliance at all** is decided per connector in
   its declaration (none that need a network, by definition), not discovered at install.

## MCP: host it, don't depend on it

The platform will be an MCP host; that is table stakes. The connector story must not assume
capable free-form tool use: a 24B model on one card is mediocre at deciding on its own to call
an outside system with the right arguments, and an office's tolerance for one wrong call to the
cadastral registry is zero. Connectors are reachable from playbook steps, with arguments
validated before the call and a person confirming before anything leaves, plus a small set of
user-invocable tools. The playbook layer is what makes tool use safe on the models that fit.

## Curated, not an app store

About 1,400 notary offices in Belgium is not a two-sided market. The model: Sūveryn-authored
packs and playbooks as the paid content; a small set of certified partners for custom
playbooks; connector partnerships with the incumbent practice-software vendors, who own the
relationship and face integrate-or-die; a curated, signed registry rather than an open store.
The licence asymmetry that makes this work, open infrastructure with proprietary declarative
content allowed on top, is already how the repositories are licensed and belongs in the
manifesto in one sentence.

Governance exists before the first third-party anything: a bad playbook creates legal liability
for the office, so playbook certification, revocation in the registry, and the separation of
platform-API versioning from pack-content versioning are written down first. The egress
declaration is part of what the registry signs.

## Identifiers

They end up in the registry, the licence, the appliance's checks and the invoice, so they are
chosen once. The version is separate from the id, so an entitlement can cover "deed intake, any 1.x".

```
pack/be-notary                        a profession pack: profession and jurisdiction
playbook/be-notary/deed-intake        a playbook inside it
connector/<vendor>-<product>          a connector; the egress declaration travels with it
```

## Sequencing

None of the three packages is built, which is the right state: the biggest risk now is designing
the platform from a specification. The order:

1. **Three hand-built playbooks for notaries**, hard-coded and plain: deed intake first (it
   exercises everything at once: documents in a case, facts read and checked against their
   passages, a checkpoint where the notary confirms, a Word document out with origin
   `playbook`, and the facts it needs are what the French benchmark, suveryn-tracker#50, needs
   to score), then a mandate or proxy check, then a closing checklist on the case lifecycle that
   exists.
2. **Extract** the playbook runtime, the manifest schema, the pack format and the versioning
   rules from what those three actually needed.
3. **Then** the SDK, the registry's signing and revocation, and the first connector, sandboxed,
   with its declaration.

The failure mode this avoids has a name: building the marketplace before the market.

## What is deliberately not here

Pricing and the licence mechanism (editions, entitlements, activation on an air-gapped box,
what enforcement can and cannot mean under AGPL) are a commercial decision and are recorded
separately. Syncing cases with the practice software is a connector, later. Several people in
one live conversation is a separate concept, out of scope as cases.md says.
