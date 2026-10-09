/**
 * Display names for the model tag in the composer. The gateway reports the served model's file
 * name; vendor logos are not used (they are the vendors' trademarks), only the name as text.
 */
export function modelName(file: string | null | undefined): { full: string; family: string } | null {
  if (!file) return null;
  const base = file.replace(/\.gguf$/i, "");
  if (/^mistral-small-3\.2/i.test(base)) return { full: "Mistral Small 3.2", family: "Mistral" };
  if (/^qwen/i.test(base)) {
    const m = base.match(/^(Qwen[\d.]+-\d+B)/i);
    return { full: m ? m[1] : "Qwen", family: "Qwen" };
  }
  // Unknown model: strip quantisation suffixes such as -Q4_K_M or -UD-Q4_K_M.
  const full = base.replace(/(-UD)?-(I?Q\d.*|F16|BF16)$/i, "");
  return { full, family: full.split(/[-\s]/)[0] };
}
