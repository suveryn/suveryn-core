// @vitest-environment node
/**
 * The ways to a case's settings (board 80; suveryn-tracker#228, #230): the playbook chip stays in a case when no
 * playbook fits its type, and the strictly confidential band says who can change it.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { setLang } from "../i18n";
import { Composer } from "./Composer";
import { ConfidentialBand } from "./ConfidentialBand";

const none = () => {};
const composer = (over: Partial<Parameters<typeof Composer>[0]>) => renderToStaticMarkup(
  <Composer attachments={[]} models={[]} chosenModel={null} onChooseModel={none} thinking={false} onThinking={none} disabledReason={null}
            busy={false} onAttach={none} onRemoveAttachment={none} onSend={none} {...over} />);

describe("the playbook chip", () => {
  setLang("en");
  it("is there in a case with no playbook for its type, once the list is read", () => {
    expect(composer({ caseReference: "TEST-1", caseType: "Estate", playbooks: [], onPlaybook: none })).toContain("Apply a playbook to this case");
  });
  it("waits for the list, and isn't offered outside a case or without a way to start one (an administrator outside it)", () => {
    expect(composer({ caseReference: "TEST-1", playbooks: null, onPlaybook: none })).not.toContain("Apply a playbook to this case");
    expect(composer({ caseReference: null, playbooks: [], onPlaybook: none })).not.toContain("Apply a playbook to this case");
    expect(composer({ caseReference: "TEST-1", playbooks: [] })).not.toContain("Apply a playbook to this case");
  });
});

describe("the strictly confidential band", () => {
  it("gives the manager Change access, and names the manager to everyone else", () => {
    const manager = renderToStaticMarkup(<ConfidentialBand narrow={false} onChangeAccess={none} manager="Test Nora" />);
    expect(manager).toContain("Change access");
    expect(manager).not.toContain("Only Test Nora");
    const member = renderToStaticMarkup(<ConfidentialBand narrow={false} manager="Test Nora" />);
    expect(member).toContain("Only Test Nora, the case manager, can change this.");
    expect(member).not.toContain("Change access");
  });
});
