/**
 * The model badge in the composer, and a menu to choose which installed model answers
 * (suveryn-tracker#4). The list comes from the gateway (GET /v1/models), so new models appear
 * without a UI change. With one installed model it is a plain tag.
 *
 * The GPU holds one model at a time: choosing one that isn't loaded makes the next answer wait
 * while it loads, and other people's questions wait too. The menu and the note under the
 * composer say so; nothing is hidden.
 */
import { Check, ChevronDown, Cpu } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { ModelInfo } from "../api";
import { modelName } from "../lib/model";

type Props = {
  models: ModelInfo[];
  chosen: string | null;          // null: the appliance's default model
  onChoose: (id: string) => void;
};

/** The model that answers when nothing is chosen. */
export function defaultModel(models: ModelInfo[]): ModelInfo | undefined {
  return models.find((m) => m.default) ?? models.find((m) => m.loaded) ?? models[0];
}

export function ModelPicker({ models, chosen, onChoose }: Props) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLSpanElement>(null);
  const current = models.find((m) => m.id === chosen) ?? defaultModel(models);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !root.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
  }, [open]);

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
    return <span className="chip-model" title={`Answers come from ${name.full}, running on this server`}>{label}</span>;
  }
  return (
    <span className="model-picker" ref={root}>
      <button type="button" className="chip-model chip-model-button" aria-haspopup="listbox" aria-expanded={open}
              title={`Answers come from ${name.full}, running on this server. Choose another model`}
              onClick={() => setOpen((o) => !o)}>
        {label}
        <ChevronDown size={12} aria-hidden />
      </button>
      {open && (
        <span className="model-menu" role="listbox" aria-label="Model">
          {models.map((m) => {
            const n = modelName(m.id);
            const selected = m.id === current.id;
            return (
              <button key={m.id} type="button" role="option" aria-selected={selected}
                      onClick={() => { onChoose(m.id); setOpen(false); }}>
                <span className="model-option-name">{n?.full ?? m.id}</span>
                <span className="model-option-state">
                  {m.loaded ? "Ready" : "Loads when chosen, up to half a minute"}
                </span>
                {selected && <Check size={14} aria-hidden className="model-option-check" />}
              </button>
            );
          })}
        </span>
      )}
    </span>
  );
}

/** A note under the composer when the chosen model isn't loaded yet; null otherwise. */
export function loadingNote(models: ModelInfo[], chosen: string | null): string | null {
  const m = models.find((x) => x.id === chosen) ?? defaultModel(models);
  if (!m || m.loaded) return null;
  const n = modelName(m.id)?.full ?? m.id;
  return `${n} isn't loaded yet: your next answer starts once it is (up to half a minute), and other people's questions wait meanwhile.`;
}
