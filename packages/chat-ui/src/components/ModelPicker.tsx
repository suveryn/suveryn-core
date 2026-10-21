/**
 * The model chip in the composer (suveryn-tracker#4, docs/design/sidebar.md §5). It opens one small
 * dialog: the installed models (GET /v1/models, so a new model appears without a UI change) and the
 * thinking mode, *Fast* or *Thorough*. The chip shows the model and, when thinking is on, the brain
 * and "· Thorough". With one model that can't think there is nothing to choose: a plain tag.
 *
 * The GPU holds one model at a time: choosing one that isn't loaded makes the next answer wait
 * while it loads, and other people's questions wait too. The list and the note under the composer
 * say so; nothing is hidden.
 */
import { Brain, Cpu } from "lucide-react";
import type { ModelInfo } from "../api";
import { t, useT } from "../i18n";
import { modelName } from "../lib/model";
import { canThink } from "../lib/thinking";
import { ChipDialog, RadioList, Segmented } from "../ui";

type Props = {
  models: ModelInfo[];
  chosen: string | null;          // null: the appliance's default model
  onChoose: (id: string) => void;
  /** *Thorough*: the conversation's mode (applies only with a model that can think). */
  thinking: boolean;
  onThinking: (on: boolean) => void;
  /** A sheet from the bottom instead of a popover (narrow screens). */
  narrow?: boolean;
};

/** The model that answers when nothing is chosen. */
export function defaultModel(models: ModelInfo[]): ModelInfo | undefined {
  return models.find((m) => m.default) ?? models.find((m) => m.loaded) ?? models[0];
}

/**
 * On the component library's ChipDialog and RadioGroups: Enter or Space on the chip opens it, the
 * arrow keys move within the models and within Fast and Thorough, Tab goes from one to the other,
 * Escape closes and the focus returns to the chip, which says what is chosen.
 */
export function ModelPicker({ models, chosen, onChoose, thinking, onThinking, narrow = false }: Props) {
  const m = useT();
  const current = models.find((m) => m.id === chosen) ?? defaultModel(models);

  const name = modelName(current?.id);
  if (!current || !name) return null;
  const thinks = canThink(current);
  const thorough = thinking && thinks;
  const label = (
    <>
      {thorough ? <Brain size={12} aria-hidden /> : <Cpu size={12} aria-hidden />}
      <span className="model-full">{name.full}</span>
      <span className="model-family">{name.family}</span>
      {thorough && <span className="model-mode">· {m.thorough}</span>}
    </>
  );
  if (models.length < 2 && !thinks) {
    return <span className="chip-model" title={m.modelTag(name.full)}>{label}</span>;
  }
  return (
    <span className="model-picker">
      <ChipDialog className="chip-model chip-model-button" triggerLabel={m.modelChipLabel(name.full, thorough ? m.thorough : m.fast)}
                  title={m.modelDialog} hideTitle narrow={narrow} doneLabel={m.askAboutDone} trigger={label}>
        {models.length > 1 && (
          <div className="model-section">
            <p className="label model-section-label">{m.model}</p>
            <RadioList label={m.model} value={current.id} onChange={onChoose}
                       choices={models.map((x) => ({
                         value: x.id, title: modelName(x.id)?.full ?? x.id,
                         description: (x.loaded ? m.modelReady : m.modelLoadsWhenChosen) + (x.thinks ? ` · ${m.modelThinks}` : ""),
                       }))} />
          </div>
        )}
        <div className="model-section">
          <p className="label model-section-label">{m.thinkingLabel}</p>
          <Segmented label={m.thinkingLabel} value={thorough ? "thorough" : "fast"} onChange={(v) => onThinking(v === "thorough")}
                     options={[{ value: "fast", label: m.fast }, { value: "thorough", label: m.thorough, disabled: !thinks }]}
                     description={!thinks ? m.thinkingUnavailable(name.full) : thorough ? m.thoroughHint : m.fastHint} />
        </div>
      </ChipDialog>
    </span>
  );
}

/** A note under the composer when the chosen model isn't loaded yet; null otherwise. */
export function loadingNote(models: ModelInfo[], chosen: string | null): string | null {
  const m = models.find((x) => x.id === chosen) ?? defaultModel(models);
  if (!m || m.loaded) return null;
  return t().modelNotLoaded(modelName(m.id)?.full ?? m.id);
}
