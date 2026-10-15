/**
 * What the web setup asks the appliance (suveryn-tracker#37). Same origin, served by the appliance
 * only until setup finishes; no sign-in (setup is what creates the first account).
 *
 * GET /setup/v1/state: what the console installer set (name, address, language). Saving the answers
 * (POST) comes with the rest of the setup in #37; the spike keeps them in the page.
 */
export type SetupState = {
  name: string;               // e.g. notary-brussels-01 (reached as <name>.local)
  address: string;            // with prefix, e.g. 192.168.1.50/24
  dhcp: boolean;
  gateway: string;
  dns: string;
  language: string | null;    // chosen at installation: en, nl or fr
};

/** In development without an appliance, the design's example (npm run dev, then /setup.html). */
const DEMO: SetupState = {
  name: "notary-brussels-01", address: "192.168.1.50/24", dhcp: true, gateway: "192.168.1.1", dns: "192.168.1.1", language: null,
};

export async function getState(): Promise<SetupState> {
  try {
    // Relative: the appliance serves setup at / (or /setup.html), so this is /setup/v1/state either way.
    const r = await fetch("setup/v1/state", { headers: { Accept: "application/json" } });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return (await r.json()) as SetupState;
  } catch (e) {
    if (import.meta.env.DEV) return DEMO;
    throw e;
  }
}

export type NetworkMode = "connected" | "air-gapped";
export type Outgoing = "approved" | "all";
export type Answers = {
  network: { mode: NetworkMode; outgoing: Outgoing };
  administrator: { name: string; email: string } | null;   // the password is never kept in the page's state
};
