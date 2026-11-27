/**
 * What a screen reader says for a chart's column, in each language (the code review of 25 November: it was joined
 * by hand, with English punctuation). The screen words it; the kit only gives the values.
 */
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import en from "../i18n/en";
import fr from "../i18n/fr";
import nl from "../i18n/nl";
import { whole } from "../i18n/format";
import { ColumnChart } from "../ui";
import { chartText } from "./UsageView";

const said = (m: typeof en, locale: string) => {
  const html = renderToStaticMarkup(
    <ColumnChart label="Tokens" series={[{ id: "input", label: m.inputTokens }, { id: "output", label: m.outputTokens }]}
                 data={[{ key: "a", label: "Tue 14:00", values: [1200, 300] }]} format={(n) => whole(n, locale)}
                 tick={String} text={chartText(m, m.chartTime, locale)} />);
  return [...html.matchAll(/<span class="ui-visually-hidden">([^<]*)<\/span>/g)]
    .map((x) => x[1].replace(/[\u00a0\u202f]/g, " ").replace(/&#x27;/g, "'"));
};

describe("a chart's column, read out", () => {
  it.each([
    // a label and its value (labelValue), the values listed the way the language lists them (decision of 13 November)
    [en, "en-GB", `Tue 14:00: ${en.inputTokens} 1,200, ${en.outputTokens} 300 and ${en.chartTotal} 1,500`],
    [nl, "nl-BE", `Tue 14:00: ${nl.inputTokens} 1.200, ${nl.outputTokens} 300 en ${nl.chartTotal} 1.500`],
    [fr, "fr-BE", `Tue 14:00 : ${fr.inputTokens} 1 200, ${fr.outputTokens} 300 et ${fr.chartTotal} 1 500`],
  ])("is worded in the reader's language", (m, locale, expected) => {
    expect(said(m as typeof en, locale)).toEqual([expected]);
  });

  it("has no total when there is one series", () => {
    const html = renderToStaticMarkup(
      <ColumnChart label="Tokens" series={[{ id: "input", label: en.inputTokens }]} data={[{ key: "a", label: "Tue 14:00", values: [1200] }]}
                   format={(n) => whole(n, "en-GB")} tick={String} text={chartText(en, en.chartTime, "en-GB")} />);
    expect(html).toContain(`Tue 14:00: ${en.inputTokens} 1,200<`);
  });
});
