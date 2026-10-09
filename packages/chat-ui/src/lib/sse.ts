/**
 * Minimal parser for the gateway's Server-Sent Events (`event:` + one `data:` line per event).
 * Feed it text as it arrives; it calls `onEvent` for every complete event and keeps partial
 * input until the rest comes in.
 */
export type SSEEvent = { event: string; data: string };

export function createSSEParser(onEvent: (e: SSEEvent) => void) {
  let buffer = "";
  return {
    feed(chunk: string) {
      buffer += chunk.replace(/\r\n/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
        let event = "message";
        const data: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) data.push(line.slice(5).replace(/^ /, ""));
        }
        if (data.length) onEvent({ event, data: data.join("\n") });
      }
    },
  };
}
