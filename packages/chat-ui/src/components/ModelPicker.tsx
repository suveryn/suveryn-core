/**
 * The model badge in the composer, and a menu to choose which installed model answers
 * (suveryn-tracker#4). The list comes from the gateway (GET /v1/models), so new models appear
 * without a UI change. With one installed model it is a plain tag.
 *
 * The GPU holds one model at a time: choosing one that isn't loaded makes the next answer wait
 * while it loads, and other people's questions wait too. The menu and the note under the
 * composer say so; nothing is hidden.
 */
import { Cpu } from "lucide-react";
import type { ModelInfo } from "../api";
import { t, useT } from "../i18n";
import { modelName } from "../lib/model";
import { MenuButton } from "../ui";

type Props = {
  models: ModelInfo[];
  chosen: string | null;          // null: the appliance's default model
  onChoose: (id: string) => void;
};

/** The model that answers when nothing is chosen. */
export function defaultModel(models: ModelInfo[]): ModelInfo | undefined {
  return models.find((m) => m.default) ?? models.find((m) => m.loaded) ?? models[0];
}

/**
 * On the component library's MenuButton (suveryn-tracker#44): arrow keys move through the models,
 * Enter or Space chooses, Escape closes and the focus returns to the badge; a screen reader hears a
 * menu of radio items with the chosen one checked.
 */
export function ModelPicker({ models, chosen, onChoose }: Props) {
  const m = useT();
  const current = models.find((m) => m.id === chosen) ?? defaultModel(models);

  const name = modelName(current?.id);
  if (!current || !name) return null;
  const label = (
    <>
      <Cpu size={12} aria-hidden />
      <span className="model-full">{name.full}</span>
      <span className="model-family">{name.family}</span>
    </>
  );
  if (models.length < 2) {
    return <span className="chip-model" title={m.modelTag(name.full)}>{label}</span>;
  }
  return (
    <span className="model-picker">
      <MenuButton
        className="chip-model chip-model-button"
        aria-label={m.modelButton(name.full)}
        menuLabel={m.model}
        placement="top end"
        popoverClassName="model-menu"
        selected={current.id}
        onAction={onChoose}
        items={models.map((x) => ({
          id: x.id,
          label: modelName(x.id)?.full ?? x.id,
          description: x.loaded ? m.modelReady : m.modelLoadsWhenChosen,
        }))}
      >
        {label}
      </MenuButton>
    </span>
  );
}

/** A note under the composer when the chosen model isn't loaded yet; null otherwise. */
export function loadingNote(models: ModelInfo[], chosen: string | null): string | null {
  const m = models.find((x) => x.id === chosen) ?? defaultModel(models);
  if (!m || m.loaded) return null;
  return t().modelNotLoaded(modelName(m.id)?.full ?? m.id);
}
