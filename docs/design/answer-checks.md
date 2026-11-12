# How an answer is checked: the rules, the languages they read, and a proposal for meaning

A design note, 11 November 2026, written with the founder. It says how sūveryn checks what the model writes
against the documents, where the words of each language live, and what is proposed for what rules can't see. It
extends [harness.md](../harness.md) §4. The measurements behind it are in suveryn-docs,
[Answer checks, November 2026](https://github.com/suveryn/suveryn-docs/blob/main/benchmarks/2026-11-answer-checks.md).

| Part | State |
|---|---|
| The checks by rule, the one reader, the planted-error benchmark | Built |
| Number words and month names generated from the standard, one file per language | Built |
| The other words of each language in one file per language, none in the code | Built |
| A second look by the model at what a sentence means | **Proposed, not decided, not built** |
| Knowing the language of each passage | Proposed |

## Two kinds of question

Checking an answer against its sources asks two different things.

1. **Is this exact thing in the source?** An amount, a date, a name, a percentage, the source cited. There is one
   right answer, the same every time, and the reason can be shown: "412.500 is not in source 1".
2. **Does the source say what the answer says?** Who pays, whether something is allowed, at the latest or at the
   earliest. This is a question of meaning.

## 1. The checks: by rule

Design principle 3 holds as written: checks are rules that give the same result every time, not a model's
judgement. What they are ([harness.md](../harness.md) §4): a figure in no passage, each citation's figures, dates,
names and units against its own passage, calculations done by the server, passages that address an AI. They need no
model call, say what they found, and can have an answer asked again once. They read every amount, number and date
through one reader (`values.py`), so two checks can't disagree about the same text.

What rules can't see is measured, not guessed. On the planted-error benchmark they catch every changed amount, date,
percentage, misspelled name and wrong source, and flag no correct answer of 45. They catch none of a "not" taken
out or put in, of the other party named, or of ten wrong answers written by hand that no figure shows ("at the
latest" told as "at the earliest", informing told as obtaining).

Two rules for a "not" and for the other party were built on 10 November and taken out again: they caught 7 of 12
and 12 of 20, and needed word lists per language in the code.

## 2. The languages the checks read

The reader knows words: months, numbers in words, abbreviations, "circa", units. The rule of
[translations.md](../translations.md) holds for them as for the interface: **one list of languages, one file per
language per place, a test that fails when one is missing, and no word of a language in the code.**

- **Generated words** (`lang/<lang>.numbers.json`). Number words and month names come from the standard spelling
  rules (num2words, Unicode CLDR), written by a developer's tool with pinned libraries. The appliance needs neither.
  Typed by hand, they had read French "cent quatre-vingt-trois" as 2 083; 2 490 numbers spelled by the standard are
  now a test.
- **Words by hand** (`lang/<lang>.json`). What no standard holds, as lists a translator can read, never patterns.
- **Test cases** about a language are data beside the tests, never in the code.
- **All languages are read together**, because one file mixes them: a Dutch deed with a French annex, an English
  question about a Dutch contract. Figures compare by value, so a number in Dutch words, in French words and in
  figures is one number. A word that means two different things in two languages stops the load.
- **Known limit.** A word that is a number in one language and an ordinary word in another needs an exception each
  (`number_only_near`), and their number grows with every language. Knowing the language of each passage would end
  that; it is proposed, not designed.

Adding a language: add it to the list, run the tool, have a native speaker fill and review the short file
([translations.md](../translations.md), *Adding a language*). The logic is not touched.

## 3. What belongs to a pack

What depends on a profession or a country, not on a language: the calendar of working days (`calendar.yaml` in the
pack).

## 4. Proposed: a second look by the model

Not decided. It would change design principle 3, which only the founder does, in a handbook decision, and the
evidence so far is not enough for that.

**The idea.** The model on the appliance reads each cited sentence of an answer beside the passages it cites and
names the kind of difference: none, leaves something out, adds something, contradicts. The code decides: only
*adds* and *contradicts* count. It would be labelled as the model's reading and shown apart from the checks; it
could flag a sentence and never clear one, never change an answer, and never have one asked again.

**What was measured** (an experiment, `packages/harness/tests/meaning_experiment.py`, on a GPU machine): the model
caught all 77 planted mistakes and all ten wrong answers by hand, flagged one correct answer of 52 (an answer that
adds "euro" to a bare number), at about a second a sentence. Asked for a verdict instead of the kind of
difference, it flagged right answers that merely shorten their source.

**Why that is not enough.** The cases and the question were written by the same author, the passages are short, 52
correct answers are few, and it was one model. A wrong flag costs trust, and a model's reading can't show its
reason as a rule can.

**On real answers** (11 November 2026, the same model and question, 106 answers on real contracts and deeds, 861
cited sentences): it said 166 sentences (19%) are not carried by their passage, in 58 of the 106 answers; the rules
flag 20. Of 12 of its flags read by hand, about 3 were real mistakes (a figure from a table given the wrong
meaning), 2 unclear and 7 wrong: a nitpick on wording, or the model misreading a table or a form. It took 1.4
seconds a sentence, about 11 an answer. As it stands it flags too much to show to a user.

**What decides it.** The French real-deed benchmark (suveryn-tracker#50) and the GPU round's own answers, read by
both models sūveryn ships. If the founder then decides for it, what must hold is written here so it isn't
rediscovered: it goes through the harness like every model call (client, usage, audit: kinds and counts, never
text); passage text is made inert as in the grounded prompt; it runs after the answer is shown, at low priority,
so it never slows an answer; when it can't run the answer says so; its place on the screen has a board first. Marking
by meaning is not part of that decision: it marks a sentence for the reader and checks nothing, and it is on since
12 November 2026 (suveryn-tracker#123).

## What was rejected

- **Rules for meaning.** Word lists per language for "not" and for each party: 7 of 12, and every language again.
- **The model for everything.** A second per sentence, no reason shown, and a check that can be exact should be.
- **Open-source libraries as the reader.** Measured before the one reader was written: far below it on our cases.
  They are the source of the word lists only.
- **One file with all languages.** Against the rule above, and a translator can't review it.

## Open, for the founder

1. Whether to take the second look further, after the measurement on real deeds.
2. If so: whether a bare number told with its unit earns a flag, how good it must be to be on by default, whether
   it also reads a playbook's facts, and what it is called on the screen.
