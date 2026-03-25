import type { ThreadMessage } from "@assistant-ui/react";

export type ApiAssistantPart =
  | { type: "text"; text: string }
  | {
      type: "tool-call";
      tool_call_id: string;
      tool_name: string;
      args: unknown;
    };

export type ApiChatMessage =
  | { role: "user"; content: string }
  | { role: "assistant"; content: ApiAssistantPart[] }
  | {
      role: "tool";
      content: Array<{
        tool_call_id: string;
        tool_name: string;
        result: unknown;
      }>;
    };

export function threadMessagesToApi(
  messages: readonly ThreadMessage[],
): ApiChatMessage[] {
  const out: ApiChatMessage[] = [];
  for (const m of messages) {
    if (m.role === "user") {
      const text = m.content
        .filter((p) => p.type === "text")
        .map((p) => p.text)
        .join("\n");
      out.push({ role: "user", content: text });
    } else if (m.role === "assistant") {
      const assistantParts: ApiAssistantPart[] = [];
      const toolPayloads: Array<{
        tool_call_id: string;
        tool_name: string;
        result: unknown;
      }> = [];

      for (const p of m.content) {
        if (p.type === "text") {
          assistantParts.push({ type: "text", text: p.text });
        } else if (p.type === "tool-call") {
          assistantParts.push({
            type: "tool-call",
            tool_call_id: p.toolCallId,
            tool_name: p.toolName,
            args: p.args,
          });
          if (p.result !== undefined) {
            toolPayloads.push({
              tool_call_id: p.toolCallId,
              tool_name: p.toolName,
              result: p.result,
            });
          }
        }
      }
      if (assistantParts.length) {
        out.push({ role: "assistant", content: assistantParts });
      }
      if (toolPayloads.length) {
        out.push({ role: "tool", content: toolPayloads });
      }
    }
  }
  return out;
}
