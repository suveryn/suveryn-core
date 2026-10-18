/** A slider (React Aria): one value in a range, keyboard and pointer. Used for the avatar's zoom. */
import { Label, Slider as AriaSlider, SliderOutput, SliderThumb, SliderTrack } from "react-aria-components";

export function Slider({ label, hideLabel, value, onChange, min = 0, max = 100, step = 1, format }: {
  label: string; hideLabel?: boolean; value: number; onChange: (v: number) => void;
  min?: number; max?: number; step?: number; format?: (v: number) => string;
}) {
  return (
    <AriaSlider className="ui-slider" value={value} onChange={(v) => onChange(Array.isArray(v) ? v[0] : v)}
                minValue={min} maxValue={max} step={step} aria-label={hideLabel ? label : undefined}>
      {!hideLabel && <Label className="ui-label">{label}</Label>}
      <SliderOutput className="ui-slider-output">{({ state }) => (format ? format(state.getThumbValue(0)) : state.getThumbValueLabel(0))}</SliderOutput>
      <SliderTrack className="ui-slider-track">
        {({ state }) => (
          <>
            <span className="ui-slider-fill" style={{ width: `${state.getThumbPercent(0) * 100}%` }} />
            <SliderThumb className="ui-slider-thumb" />
          </>
        )}
      </SliderTrack>
    </AriaSlider>
  );
}
