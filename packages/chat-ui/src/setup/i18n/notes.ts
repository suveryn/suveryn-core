/**
 * Notes for the translator of the web setup's text: where an entry appears and what its values stand for
 * (src/i18n/notes.ts says how they work). The setup speaks to the person installing the appliance, once.
 */
import type { Notes } from "../../i18n/message";
import type en from "./en";

export const notes: Notes<typeof en> = {
  labelValue: "A label and its value on one line. Only the punctuation between them is yours (French puts a space before the colon).",
  addressDetail: "Under the appliance's address on the network screen. {dhcp} is true when the network gave the address (DHCP), false when it was set by hand.",
  messages: "What the appliance refused, by its code. Whole sentences, shown under the field they are about or at the top of the screen. Say what is wrong and what to enter instead.",
  messagesBare: "The same code's sentence when the appliance didn't say which step stopped.",
  messageKinds: "What is said when a code isn't known. Whole sentences.",
  messageInternalRef: "An unplanned failure. {ref} is the code the partner finds in the appliance's log; keep it at the end.",
};
