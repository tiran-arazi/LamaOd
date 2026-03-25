import type {
  ChatModelAdapter,
  ThreadAssistantMessagePart,
  ToolCallMessagePart,
} from "@assistant-ui/react";
import { threadMessagesToApi } from "./threadToApi";

type StreamPayload =
  | { type: "text_delta"; text: string }
  | { type: "tool_call"; tool_call_id: string; tool_name: string; args: unknown }
  | { type: "tool_result"; tool_call_id: string; tool_name: string; result: unknown }
  | { type: "done" }
  | { type: "error"; message: string; traceback?: string };

type ToolEntry = {
  toolCallId: string;
  toolName: string;
  args: unknown;
  argsText: string;
  result?: unknown;
};

function toArgsText(args: unknown): string {
  try {
    return typeof args === "string" ? args : JSON.stringify(args ?? {});
  } catch {
    return "{}";
  }
}

function mergeContent(
  textBuffer: string,
  toolsInOrder: string[],
  toolMap: Map<string, ToolEntry>,
): readonly ThreadAssistantMessagePart[] {
  const parts: ThreadAssistantMessagePart[] = [];
  if (textBuffer) {
    parts.push({ type: "text", text: textBuffer });
  }
  for (const id of toolsInOrder) {
    const t = toolMap.get(id);
    if (!t) continue;
    parts.push({
      type: "tool-call",
      toolCallId: t.toolCallId,
      toolName: t.toolName,
      args: t.args,
      argsText: t.argsText,
      result: t.result,
    } as ToolCallMessagePart);
  }
  return parts;
}

export const explorerChatAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const apiBody = { messages: threadMessagesToApi(messages) };
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
        "Cache-Control": "no-cache",
      },
      body: JSON.stringify(apiBody),
      signal: abortSignal,
    });

    if (!res.ok) {
      const errText = await res.text();
      yield {
        content: [
          {
            type: "text",
            text: `Request failed (${res.status}): ${errText || res.statusText}`,
          },
        ],
        status: { type: "incomplete", reason: "error", error: errText },
      };
      return;
    }

    const reader = res.body?.getReader();
    if (!reader) {
      yield {
        content: [{ type: "text", text: "No response body" }],
        status: { type: "incomplete", reason: "error" },
      };
      return;
    }

    const decoder = new TextDecoder();
    let carry = "";
    let textBuffer = "";
    const toolMap = new Map<string, ToolEntry>();
    const toolsInOrder: string[] = [];

    const applyPayload = (payload: StreamPayload) => {
      if (payload.type === "text_delta") {
        const chunk = payload.text;
        if (chunk != null && chunk !== "") {
          textBuffer += typeof chunk === "string" ? chunk : String(chunk);
        }
      } else if (payload.type === "tool_call") {
        const argsText = toArgsText(payload.args);
        toolMap.set(payload.tool_call_id, {
          toolCallId: payload.tool_call_id,
          toolName: payload.tool_name,
          args: payload.args,
          argsText,
        });
        if (!toolsInOrder.includes(payload.tool_call_id)) {
          toolsInOrder.push(payload.tool_call_id);
        }
      } else if (payload.type === "tool_result") {
        const existing = toolMap.get(payload.tool_call_id);
        if (existing) {
          existing.result = payload.result;
        } else {
          toolMap.set(payload.tool_call_id, {
            toolCallId: payload.tool_call_id,
            toolName: payload.tool_name,
            args: {},
            argsText: "{}",
            result: payload.result,
          });
          toolsInOrder.push(payload.tool_call_id);
        }
      }
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      carry += decoder.decode(value, { stream: true });
      const lines = carry.split("\n");
      carry = lines.pop() ?? "";
      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed.startsWith("data:")) continue;
        const raw = trimmed.slice(5).trim();
        if (!raw) continue;
        let payload: StreamPayload;
        try {
          payload = JSON.parse(raw) as StreamPayload;
        } catch {
          continue;
        }
        if (payload.type === "error") {
          const tb =
            "traceback" in payload && payload.traceback
              ? `\n\n[DEBUG] traceback\n${payload.traceback}`
              : "";
          const debugText = `\n\n[DEBUG] chat stream error: ${payload.message}${tb}\n`;
          yield {
            content: mergeContent(
              textBuffer + debugText,
              toolsInOrder,
              toolMap,
            ),
            status: {
              type: "incomplete",
              reason: "error",
              error: payload.message,
            },
          };
          return;
        }
        if (payload.type === "done") {
          yield {
            content: mergeContent(textBuffer, toolsInOrder, toolMap),
            status: { type: "complete", reason: "stop" },
          };
          return;
        }
        applyPayload(payload);
        yield { content: mergeContent(textBuffer, toolsInOrder, toolMap) };
      }
    }

    yield {
      content: mergeContent(textBuffer, toolsInOrder, toolMap),
      status: { type: "complete", reason: "unknown" },
    };
  },
};
