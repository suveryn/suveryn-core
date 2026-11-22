/**
 * Sample data for tests and previews of a playbook run: each maker gives what the test is about and gets every
 * member the gateway always sends (the types are generated from its description, src/generated), with the value an
 * empty one has there.
 */
import type { PlaybookInfo, PlaybookStep, RunFact } from "../api";

type Words = PlaybookInfo["text"][string];
type Citation = RunFact["citations"][number];

export const aStep = (step: Pick<PlaybookStep, "id" | "kind"> & Partial<PlaybookStep>): PlaybookStep =>
  ({ needs: [], facts: [], by: "anyone_in_case", allow_none: false, ...step });

export const someWords = (words: Pick<Words, "title" | "labels"> & Partial<Words>): Words =>
  ({ summary: "", questions: {}, checks: {}, steps: {}, facts_title: "", ...words });

export const aCitation = (citation: Pick<Citation, "n" | "document_id" | "filename" | "text"> & Partial<Citation>): Citation =>
  ({ page: null, location: null, context: null, decimals: null, ranges: [], facts: [], ...citation });

export const aFact = (fact: Pick<RunFact, "id"> & Partial<RunFact>): RunFact =>
  ({ value: "", citations: [], issues: [], found: true, confirmed: null, source: "document", by: null, was: null, at: null, needs: null,
     computed: null, alternative: null, ...fact });

export const aPlaybook = (playbook: Pick<PlaybookInfo, "id" | "slug" | "pack" | "version" | "name" | "covered" | "facts"> & Partial<PlaybookInfo>): PlaybookInfo =>
  ({ lists: {}, kinds: {}, choices: {}, case_types: [], active: true, steps: [], text: {}, ...playbook });
