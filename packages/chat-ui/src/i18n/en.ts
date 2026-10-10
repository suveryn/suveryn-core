/**
 * English (UK) interface text. This table defines every string the chat UI shows; nl.ts and fr.ts
 * must have the same keys (TypeScript checks it, so a missing translation fails the build).
 *
 * Rules (also for translations): Dutch is formal (u/uw); "sūveryn" is lower case except at the
 * start of a sentence or as the company. The tagline stays in English in every language, as on
 * the website. Server messages (error details, calculation errors) arrive in English.
 */
const en = {
  languageName: "English",
  language: "Language",

  // sign-in
  signIn: "Sign in",
  signInCaption: "Your office's own sign-in. Documents and answers stay on this server.",
  sessionEnded: "Your session has ended. Sign in to continue.",
  signInUnavailable: (why: string) => `Sign-in isn't available right now: ${why}`,

  // health and availability
  serverUnreachable: "Can't reach the sūveryn server.",
  modelStarting: "The model is starting. This takes up to a minute.",
  modelUnavailable: "The model isn't available right now.",
  documentsStarting: "Document handling is starting…",
  documentsUnavailable: "Document handling isn't available on this server.",
  documentsFailed: "Document handling failed to start.",
  documentsCantBeAdded: "Documents can't be added right now: document handling isn't available on this server.",
  historyFailed: "Conversations can't be saved right now.",
  historyUnavailable: "Conversations aren't saved on this server; they end when you close the page.",

  // problems (the server's reason follows)
  saveFailed: (why: string) => `This conversation couldn't be saved: ${why}`,
  openFailed: (why: string) => `Couldn't open that conversation: ${why}`,
  deleteConversationFailed: (why: string) => `Couldn't delete that conversation: ${why}`,
  deleteDocumentFailed: (file: string, why: string) => `Couldn't delete ${file}: ${why}`,
  sessionEndedError: "your session has ended; sign in again",
  uploadInterrupted: "the upload was interrupted",
  streamCutOff: "the connection closed before the answer was complete",

  // empty state
  emptyIntro: "Attach a deed or another PDF and ask about it. Answers cite the page they come from, so you can check every figure.",

  // sidebar
  newChat: "New chat",
  conversations: "Conversations",
  conversationsEmpty: "Your conversations are saved here after each answer.",
  conversationFallbackTitle: "Conversation",
  deleteConversationLabel: (title: string) => `Delete the conversation "${title}"`,
  deleteConversationTitle: "Delete this conversation",
  delete: "Delete",
  keep: "Keep",
  documents: "Documents",
  documentsEmpty: "No documents yet. Attach a PDF to a message to add one.",
  pages: (n: number) => `${n} ${n === 1 ? "page" : "pages"}`,
  checkPages: (pages: string) => ` · check ${pages}`,
  checkNeeded: " · check needed",
  inUse: " · in use",
  alreadyInConversation: "Already in this conversation",
  useInConversation: "Use in this conversation",
  useInConversationReview: (hint: string) => `Use in this conversation. ${hint}`,
  deleteDocumentLabel: (file: string) => `Delete ${file}`,
  deleteDocumentTitle: "Delete from this server",
  jobFailed: "Couldn't be read",
  jobQueued: "Waiting…",
  jobProcessing: "Reading…",
  signOut: "Sign out",
  staysOnServer: "Documents and answers stay on this server.",
  today: "Today",
  yesterday: "Yesterday",

  // sign-out dialog
  keepHistoryTitle: "Keep your chat history?",
  keepHistoryBody: "Your conversations are saved on this server, where only you can see them. Keep them to pick up where you left off next time, or delete them now.",
  keepAndSignOut: "Keep and sign out",
  deleteAndSignOut: "Delete history and sign out",
  deleting: "Deleting…",
  cancel: "Cancel",
  deleteHistoryFailed: (why: string) => `Your history couldn't be deleted, so you are still signed in: ${why}`,

  // composer
  attachPdf: "Attach a PDF",
  yourQuestion: "Your question",
  askPlaceholder: "Ask about your documents…",
  send: "Send message",
  waitingForDocuments: "Waiting for your documents to be read…",
  composerHint: "Answers come from the documents in this conversation and cite the page they come from.",

  // model picker
  modelTag: (model: string) => `Answers come from ${model}, running on this server`,
  modelButton: (model: string) => `Answers come from ${model}, running on this server. Choose another model`,
  model: "Model",
  modelReady: "Ready",
  modelLoadsWhenChosen: "Loads when chosen, up to half a minute",
  modelNotLoaded: (model: string) =>
    `${model} isn't loaded yet: your next answer starts once it is (up to half a minute), and other people's questions wait meanwhile.`,

  // attachment and citation chips
  uploading: "Uploading…",
  uploadingPercent: (pct: number) => `Uploading… ${pct}%`,
  waiting: "Waiting…",
  reading: "Reading…",
  readyCheckNeeded: "Ready · check needed",
  readyCheckPages: (pages: string) => `Ready · check ${pages}`,
  couldntBeRead: "Couldn't be read",
  removeFile: (file: string) => `Remove ${file}`,
  sourceLabel: (n: number, file: string, page: number | null | undefined) => `Source ${n}: ${file}${page ? `, page ${page}` : ""}`,
  pageShort: (page: number) => `p.${page}`,

  // pages to check (documents in needs_review)
  pageList: (pages: number[]) => `${pages.length > 1 ? "pp." : "p."} ${pages.join(", ")}`,
  reviewHint: (pages: number[] | undefined) => {
    const where = !pages?.length ? "on some pages" : pages.length > 1 ? `on pages ${pages.join(", ")}` : `on page ${pages[0]}`;
    return `Ready to use. Some text ${where} may not have been read correctly, so check answers that rely on it against the original.`;
  },

  // waiting status (suveryn-tracker#6)
  sending: "Sending your question…",
  statusSearching: "Searching your documents…",
  statusReadingAll: (passages: string) => `Reading your documents (${passages})…`,
  statusReadingBest: (passages: string) => `Reading the ${passages} that best match your question…`,
  passages: (n: number) => `${n} ${n === 1 ? "passage" : "passages"}`,
  statusLoading: (model: string | null) => `Loading ${model ?? "the model"}, which can take up to half a minute…`,
  statusWriting: "Writing the answer…",

  // answers
  answerFailed: (why: string) => `The answer couldn't be completed: ${why}. Nothing from this attempt is shown, so ask again.`,
  answerInterrupted: "This answer was interrupted.",
  sources: "Sources",
  copySources: "Copy sources",
  allCitedSources: "all cited sources",
  noSourceCited: "No source is cited for this answer. Check it against the documents before relying on it.",
  notGrounded: "Not based on your documents. Attach a document to get answers that cite their source.",
  copy: "Copy",
  copyWhat: (what: string) => `Copy ${what}`,
  copied: "Copied",
  copyFailed: "Couldn't copy",
  download: "Download",
  downloadWhat: (what: string) => `Download ${what}`,
  textFile: "Text (.txt)",
  markdownFile: "Markdown (.md)",
  source: (n: number) => `Source ${n}`,
  sourceWithReference: (n: number) => `source ${n} with its reference`,
  sourceN: (n: number) => `source ${n}`,
  sourceCaption: "The passage as it was read from the document. Check the original page before relying on it.",
  calcFailed: (expression: string, why: string) => `Couldn't calculate ${expression}: ${why}.`,
  calculatedBy: "Calculated by sūveryn, not read from the documents:",
  calcMissing: (figures: string[]) => ` Check ${figures.join(", ")}: ${figures.length === 1 ? "it doesn't" : "they don't"} appear in the sources.`,
  calcAllSourced: " Every figure comes from the sources.",
  unverified: (figures: string[]) => {
    const one = figures.length === 1;
    return `Check ${figures.join(", ")}: ${one ? "this figure isn't" : "these figures aren't"} in the documents and ${one ? "wasn't" : "weren't"} calculated by sūveryn. The model may have worked ${one ? "it" : "them"} out itself, which can be wrong.`;
  },
  unverifiedTitle: "Not in the documents and not calculated by sūveryn. Check this figure.",


  // token usage (suveryn-tracker#7)
  tokensToday: (n: string) => `${n} tokens today`,
  tokensTodayTitle: "Your token usage: open the overview",
  yourUsage: "Your usage",
  usageIntro: "The tokens the model processed for your questions. Only you can see this. It is for information only: nothing is ever limited because of it.",
  rangeLabel: "Period",
  presetHour: "Hour",
  presetDay: "Day",
  presetWeek: "Week",
  presetMonth: "Month",
  presetCustom: "Custom",
  from: "From",
  to: "To",
  requests: "Requests",
  inputTokens: "Input tokens",
  outputTokens: "Output tokens",
  totalTokens: "Total tokens",
  kind: (kind: string) => ({ chat: "Chat", summary: "Summaries", "playbook-step": "Playbook steps" } as Record<string, string>)[kind] ?? kind,
  chartLabel: (total: string, step: string) => `Tokens over time, ${total} in total, in steps of ${step}`,
  stepName: (step: string) => ({ "5 minutes": "5 minutes", "1 hour": "1 hour", "1 day": "1 day", "7 days": "1 week", "30 days": "30 days" } as Record<string, string>)[step] ?? step,
  noUsage: "No usage in this period.",
  usageUnavailable: (why: string) => `Usage can't be shown right now: ${why}`,
  backToChat: "Back to the conversation",
  administration: "Administration",
  adminUsage: "Usage",
  officeUsage: "Office usage",
  adminIntro: "Token usage of everyone in the office, in total and per user. For information only: nothing is ever limited because of it.",
  perUser: "Per user",
  user: "User",
  unknownUser: "Unknown user",
  notionalCost: "Notional cloud cost",
  costExplain: (cost: string, input: string, output: string) =>
    `On a cloud API this usage would have cost about ${cost}, at ${input} per million input tokens and ${output} per million output tokens. Hardware and electricity are not included.`,
  rates: "Rates for the notional cost",
  rateInput: "Per million input tokens",
  rateOutput: "Per million output tokens",
  currency: "Currency",
  save: "Save",
  saved: "Saved",
  ratesChanged: (who: string, when: string) => `Last changed by ${who} on ${when}.`,
  ratesDefault: "Default: the published price of a comparable cloud model.",
  ratesInvalid: "Enter amounts of 0 or more.",
  // downloaded sources
  sourcesHeading: "Sources cited by sūveryn",
  question: "Question",
  date: "Date",
};

export type Messages = typeof en;
export default en;
