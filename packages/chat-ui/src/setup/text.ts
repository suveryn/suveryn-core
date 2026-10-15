/**
 * The web setup's text in English, Dutch and French (suveryn-tracker#37). English is the approved
 * design's copy (suveryn-appliance docs/design/first-boot-setup); Dutch (formal u/uw) and French
 * (vous) follow the console installer's wording, still to be reviewed by native speakers. The
 * tagline stays in English. TypeScript checks that every language has every string.
 *
 * The language is the one chosen at installation (the appliance says which), else the one chosen in
 * the language menu (remembered in this browser, like the chat's), else the browser's, else English.
 */
import { useSyncExternalStore } from "react";

export type Lang = "en" | "nl" | "fr";
export const LANGS: Lang[] = ["en", "nl", "fr"];
export const LOCALES: Record<Lang, string> = { en: "en-GB", nl: "nl-BE", fr: "fr-BE" };

const en = {
  languageName: "English",
  language: "Language",
  tagline: "AI for work that can't leave the premises.",
  pageTitle: (screen: string) => `Sūveryn setup · ${screen}`,
  step: (n: number, total: number) => `Setup · Step ${n} of ${total}`,
  back: "Back",
  continue: "Continue",
  loading: "Loading…",
  unreachable: "The appliance doesn't answer. Check that this computer is on the same network, then reload the page.",

  networkTitle: "Network",
  networkLead: "The name and address were set during installation. Here you choose how much internet access this appliance gets.",
  setDuringInstallation: "Set during installation",
  name: "Name",
  address: "Address",
  addressDetail: (dhcp: boolean, gateway: string, dns: string) =>
    `${dhcp ? "DHCP" : "Fixed"} · gateway ${gateway} · DNS ${dns}`,
  changeOnConsole: "To change these, choose option 2 on the appliance console.",
  internetAccess: "Internet access",
  internetAccessLead: "How far this appliance may reach beyond your own network.",
  connected: "Connected",
  connectedDesc: "Reaches only what it needs, such as sūveryn updates. You decide what is allowed.",
  airGapped: "Air-gapped",
  airGappedDesc: "No outgoing connections at all. Your office network stays reachable.",
  outgoing: "Outgoing connections",
  approvedOnly: "Approved destinations only (recommended)",
  approvedOnlyDesc: "The appliance blocks everything else itself.",
  approvedList: "Approved destinations",
  approvedUpdates: "Sūveryn updates and models",
  approvedConnectors: "Connectors you enable",
  allowAll: "Allow all outgoing traffic",
  allowAllDesc: "Only if your own firewall decides what this appliance may reach.",
  changeLater: "You can change this and the list later in the admin dashboard.",

  adminTitle: "Administrator account",
  adminLead: "The first account on this appliance. Use it to sign in once setup finishes, and to manage users and settings afterwards.",
  fullName: "Full name",
  fullNamePlaceholder: "Filip Tack",
  email: "Email address",
  emailPlaceholder: "filip@yourfirm.example",
  emailHint: "Used to sign in. It stays on this appliance.",
  password: "Password",
  passwordPlaceholder: "At least 15 characters",
  showPassword: "Show password",
  confirmPassword: "Confirm password",
  confirmPlaceholder: "Repeat the password",
  adminNote: "This account only manages this sūveryn appliance. It does not need to match an account you use elsewhere.",
  errNameMissing: "Enter your full name.",
  errEmailMissing: "Enter an email address.",
  errEmailInvalid: "Enter an email address like name@example.com.",
  errPasswordShort: (min: number) => `Use at least ${min} characters.`,
  errPasswordCommon: "This password is too common. Choose one that is harder to guess.",
  errPasswordPersonal: "Don't use your name, your email address or the appliance's name in the password.",
  errConfirm: "The passwords don't match.",

  spikeEnd: "This is as far as the component spike goes (suveryn-tracker#44). Steps 3 to 6 follow in #37.",
};

export type Text = typeof en;

const nl: Text = {
  languageName: "Nederlands",
  language: "Taal",
  tagline: "AI for work that can't leave the premises.",
  pageTitle: (screen) => `Sūveryn-installatie · ${screen}`,
  step: (n, total) => `Installatie · Stap ${n} van ${total}`,
  back: "Terug",
  continue: "Verder",
  loading: "Laden…",
  unreachable: "De appliance antwoordt niet. Controleer of deze computer op hetzelfde netwerk zit en laad de pagina opnieuw.",

  networkTitle: "Netwerk",
  networkLead: "De naam en het adres zijn tijdens de installatie ingesteld. Hier kiest u hoeveel internettoegang deze appliance krijgt.",
  setDuringInstallation: "Ingesteld tijdens de installatie",
  name: "Naam",
  address: "Adres",
  addressDetail: (dhcp, gateway, dns) => `${dhcp ? "DHCP" : "Vast"} · gateway ${gateway} · DNS ${dns}`,
  changeOnConsole: "Om deze te wijzigen, kiest u optie 2 op de console van de appliance.",
  internetAccess: "Internettoegang",
  internetAccessLead: "Hoe ver deze appliance buiten uw eigen netwerk mag reiken.",
  connected: "Verbonden",
  connectedDesc: "Bereikt alleen wat ze nodig heeft, zoals updates van sūveryn. U bepaalt wat is toegestaan.",
  airGapped: "Air-gapped",
  airGappedDesc: "Helemaal geen uitgaande verbindingen. Uw kantoornetwerk blijft bereikbaar.",
  outgoing: "Uitgaande verbindingen",
  approvedOnly: "Alleen goedgekeurde bestemmingen (aanbevolen)",
  approvedOnlyDesc: "De appliance blokkeert zelf al de rest.",
  approvedList: "Goedgekeurde bestemmingen",
  approvedUpdates: "Updates en modellen van sūveryn",
  approvedConnectors: "Connectoren die u inschakelt",
  allowAll: "Alle uitgaand verkeer toestaan",
  allowAllDesc: "Alleen als uw eigen firewall bepaalt wat deze appliance mag bereiken.",
  changeLater: "U kunt dit en de lijst later wijzigen in het beheerdashboard.",

  adminTitle: "Beheerdersaccount",
  adminLead: "Het eerste account op deze appliance. Hiermee meldt u zich aan zodra de installatie klaar is, en beheert u daarna gebruikers en instellingen.",
  fullName: "Volledige naam",
  fullNamePlaceholder: "Filip Tack",
  email: "E-mailadres",
  emailPlaceholder: "filip@uwkantoor.example",
  emailHint: "Om u aan te melden. Het blijft op deze appliance.",
  password: "Wachtwoord",
  passwordPlaceholder: "Minstens 15 tekens",
  showPassword: "Wachtwoord tonen",
  confirmPassword: "Wachtwoord bevestigen",
  confirmPlaceholder: "Herhaal het wachtwoord",
  adminNote: "Dit account beheert alleen deze sūveryn-appliance. Het hoeft niet overeen te komen met een account dat u elders gebruikt.",
  errNameMissing: "Vul uw volledige naam in.",
  errEmailMissing: "Vul een e-mailadres in.",
  errEmailInvalid: "Vul een e-mailadres in zoals naam@voorbeeld.be.",
  errPasswordShort: (min) => `Gebruik minstens ${min} tekens.`,
  errPasswordCommon: "Dit wachtwoord komt te vaak voor. Kies er een dat moeilijker te raden is.",
  errPasswordPersonal: "Gebruik uw naam, uw e-mailadres of de naam van de appliance niet in het wachtwoord.",
  errConfirm: "De wachtwoorden komen niet overeen.",

  spikeEnd: "Tot hier gaat de proef met de componenten (suveryn-tracker#44). Stap 3 tot 6 volgen in #37.",
};

const fr: Text = {
  languageName: "Français",
  language: "Langue",
  tagline: "AI for work that can't leave the premises.",
  pageTitle: (screen) => `Configuration de sūveryn · ${screen}`,
  step: (n, total) => `Configuration · Étape ${n} sur ${total}`,
  back: "Retour",
  continue: "Continuer",
  loading: "Chargement…",
  unreachable: "L'appliance ne répond pas. Vérifiez que cet ordinateur est sur le même réseau, puis rechargez la page.",

  networkTitle: "Réseau",
  networkLead: "Le nom et l'adresse ont été définis lors de l'installation. Ici, vous choisissez l'accès à Internet de cette appliance.",
  setDuringInstallation: "Définis lors de l'installation",
  name: "Nom",
  address: "Adresse",
  addressDetail: (dhcp, gateway, dns) => `${dhcp ? "DHCP" : "Fixe"} · passerelle ${gateway} · DNS ${dns}`,
  changeOnConsole: "Pour les modifier, choisissez l'option 2 sur la console de l'appliance.",
  internetAccess: "Accès à Internet",
  internetAccessLead: "Jusqu'où cette appliance peut aller au-delà de votre propre réseau.",
  connected: "Connectée",
  connectedDesc: "N'atteint que ce dont elle a besoin, comme les mises à jour de sūveryn. Vous décidez de ce qui est autorisé.",
  airGapped: "Air-gapped",
  airGappedDesc: "Aucune connexion sortante. Le réseau de votre bureau reste accessible.",
  outgoing: "Connexions sortantes",
  approvedOnly: "Destinations approuvées uniquement (recommandé)",
  approvedOnlyDesc: "L'appliance bloque elle-même tout le reste.",
  approvedList: "Destinations approuvées",
  approvedUpdates: "Mises à jour et modèles de sūveryn",
  approvedConnectors: "Connecteurs que vous activez",
  allowAll: "Autoriser tout le trafic sortant",
  allowAllDesc: "Uniquement si votre propre pare-feu décide de ce que cette appliance peut atteindre.",
  changeLater: "Vous pourrez modifier ce choix et la liste plus tard dans le tableau de bord d'administration.",

  adminTitle: "Compte administrateur",
  adminLead: "Le premier compte de cette appliance. Il vous sert à vous connecter une fois la configuration terminée, puis à gérer les utilisateurs et les paramètres.",
  fullName: "Nom complet",
  fullNamePlaceholder: "Filip Tack",
  email: "Adresse e-mail",
  emailPlaceholder: "filip@votrecabinet.example",
  emailHint: "Pour vous connecter. Elle reste sur cette appliance.",
  password: "Mot de passe",
  passwordPlaceholder: "Au moins 15 caractères",
  showPassword: "Afficher le mot de passe",
  confirmPassword: "Confirmer le mot de passe",
  confirmPlaceholder: "Répétez le mot de passe",
  adminNote: "Ce compte gère uniquement cette appliance sūveryn. Il n'a pas besoin de correspondre à un compte que vous utilisez ailleurs.",
  errNameMissing: "Saisissez votre nom complet.",
  errEmailMissing: "Saisissez une adresse e-mail.",
  errEmailInvalid: "Saisissez une adresse e-mail comme nom@exemple.be.",
  errPasswordShort: (min) => `Utilisez au moins ${min} caractères.`,
  errPasswordCommon: "Ce mot de passe est trop courant. Choisissez-en un plus difficile à deviner.",
  errPasswordPersonal: "N'utilisez pas votre nom, votre adresse e-mail ni le nom de l'appliance dans le mot de passe.",
  errConfirm: "Les mots de passe ne correspondent pas.",

  spikeEnd: "L'essai des composants (suveryn-tracker#44) s'arrête ici. Les étapes 3 à 6 suivent dans #37.",
};

export const TEXT: Record<Lang, Text> = { en, nl, fr };

const KEY = "suveryn.lang"; // the same key as the chat's language menu
let current: Lang = "en";
const listeners = new Set<() => void>();

/** The first supported language in a list of BCP 47 tags, else English. */
export function pickLang(preferred: readonly string[]): Lang {
  for (const tag of preferred) {
    const base = tag.toLowerCase().split("-")[0];
    if ((LANGS as string[]).includes(base)) return base as Lang;
  }
  return "en";
}

/** The starting language: the appliance's (chosen at installation), else this browser's choice, else
 *  the browser's languages. */
export function initialLang(appliance: string | null): Lang {
  if (appliance && (LANGS as string[]).includes(appliance)) return appliance as Lang;
  try {
    const saved = localStorage.getItem(KEY);
    if (saved && (LANGS as string[]).includes(saved)) return saved as Lang;
  } catch { /* storage blocked */ }
  return pickLang(typeof navigator === "undefined" ? [] : navigator.languages ?? [navigator.language]);
}

export function setLang(next: Lang, remember = true): void {
  current = next;
  if (remember) { try { localStorage.setItem(KEY, next); } catch { /* this page only */ } }
  if (typeof document !== "undefined") document.documentElement.lang = LOCALES[next];
  listeners.forEach((l) => l());
}

export const lang = (): Lang => current;
const subscribe = (l: () => void) => { listeners.add(l); return () => { listeners.delete(l); }; };

/** The current language's text; the component re-renders when the language changes. */
export function useText(): Text {
  return TEXT[useSyncExternalStore(subscribe, lang, lang)];
}
export function useLang(): Lang {
  return useSyncExternalStore(subscribe, lang, lang);
}
