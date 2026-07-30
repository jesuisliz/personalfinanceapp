import { useEffect, useState } from "react";
import {
  fetchConversationMessages,
  fetchConversations,
  renameConversation,
  sendChatMessage,
  type ChatConversationSummary,
  type ChatMessage as ApiChatMessage,
  type ToolCall,
} from "./api";
import { formatAmount, formatRelativeTime } from "./format";
import { Card, PrimaryButton, SecondaryButton, inputClass } from "./ui";

const CONVERSATION_ID_KEY = "chat_conversation_id";

interface DisplayMessage {
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls?: ToolCall[];
}

function MiniTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto mt-1">
      <table className="text-xs border border-hairline rounded-lg overflow-hidden">
        <thead>
          <tr className="bg-surface-2 text-ink-secondary">
            {headers.map((h) => (
              <th key={h} className="px-2 py-1 text-left font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-hairline">
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1 text-ink-secondary whitespace-nowrap">
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ToolResultTable({ toolCall }: { toolCall: ToolCall }) {
  const { name, result } = toolCall;

  if (result && typeof result === "object" && !Array.isArray(result) && "error" in result) {
    return <p className="text-xs text-critical mt-1">Tool error: {String((result as { error: unknown }).error)}</p>;
  }

  if (name === "get_monthly_summary" && Array.isArray(result)) {
    return (
      <MiniTable
        headers={["Month", "Income", "Expenses", "Net"]}
        rows={result.map((r) => [r.month, formatAmount(r.income_cents), formatAmount(r.expense_cents), formatAmount(r.net_cents)])}
      />
    );
  }

  if (name === "get_category_breakdown" && Array.isArray(result)) {
    return (
      <MiniTable
        headers={["Category", "Total"]}
        rows={result.map((r) => [r.category_name, formatAmount(r.total_cents)])}
      />
    );
  }

  if (name === "get_top_merchants" && Array.isArray(result)) {
    return (
      <MiniTable
        headers={["Merchant", "Total", "Count"]}
        rows={result.map((r) => [r.merchant, formatAmount(r.total_cents), String(r.transaction_count)])}
      />
    );
  }

  if (name === "get_category_transactions" && Array.isArray(result)) {
    return (
      <MiniTable
        headers={["Date", "Description", "Amount"]}
        rows={result.map((r) => [r.date, r.description, formatAmount(r.amount_cents)])}
      />
    );
  }

  if (name === "get_merchant_transactions" && result && typeof result === "object" && !Array.isArray(result)) {
    const r = result as {
      total_cents: number;
      transaction_count: number;
      transactions: { date: string; description: string; amount_cents: number }[];
    };
    return (
      <div>
        <p className="text-xs text-ink-muted mt-1">
          {formatAmount(r.total_cents)} across {r.transaction_count} transaction{r.transaction_count === 1 ? "" : "s"}
        </p>
        <MiniTable
          headers={["Date", "Description", "Amount"]}
          rows={r.transactions.map((t) => [t.date, t.description, formatAmount(t.amount_cents)])}
        />
      </div>
    );
  }

  if (name === "get_category_trends" && result && typeof result === "object" && !Array.isArray(result)) {
    const trends = result as Record<string, { category_name: string; total_cents: number }[]>;
    return (
      <div className="space-y-2">
        {Object.entries(trends).map(([month, rows]) => (
          <div key={month}>
            <div className="text-xs font-medium text-ink-muted mt-1">{month}</div>
            <MiniTable headers={["Category", "Total"]} rows={rows.map((r) => [r.category_name, formatAmount(r.total_cents)])} />
          </div>
        ))}
      </div>
    );
  }

  if (name === "estimate_category_reduction_savings" && result && typeof result === "object" && !Array.isArray(result)) {
    const r = result as {
      avg_monthly_cents: number;
      monthly_savings_cents: number;
      annual_savings_cents: number;
      months_considered: number;
    };
    return (
      <MiniTable
        headers={["Avg monthly spend", "Monthly savings", "Annual savings", "Months averaged"]}
        rows={[
          [
            formatAmount(r.avg_monthly_cents),
            formatAmount(r.monthly_savings_cents),
            formatAmount(r.annual_savings_cents),
            String(r.months_considered),
          ],
        ]}
      />
    );
  }

  return <pre className="text-xs text-ink-muted mt-1 whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>;
}

export default function Chat() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [conversationId, setConversationId] = useState<number | null>(null);
  const [conversations, setConversations] = useState<ChatConversationSummary[]>([]);
  const [editingConversationId, setEditingConversationId] = useState<number | null>(null);
  const [editingTitleValue, setEditingTitleValue] = useState("");

  function refreshConversations() {
    fetchConversations()
      .then(setConversations)
      .catch(() => {
        // Non-critical: the list is a convenience, not required for chatting.
      });
  }

  function loadConversation(id: number) {
    return fetchConversationMessages(id)
      .then((history) => {
        setConversationId(id);
        localStorage.setItem(CONVERSATION_ID_KEY, String(id));
        setMessages(history.map((m) => ({ role: m.role, content: m.content, toolCalls: m.tool_calls })));
      })
      .catch(() => {
        // Stale/deleted conversation (e.g. the DB was reset) -- fall back to a clean chat
        // rather than surfacing an error for something the user didn't do.
        localStorage.removeItem(CONVERSATION_ID_KEY);
        setConversationId(null);
        setMessages([]);
      });
  }

  useEffect(() => {
    refreshConversations();

    const savedId = localStorage.getItem(CONVERSATION_ID_KEY);
    if (savedId === null) {
      setHistoryLoading(false);
      return;
    }

    loadConversation(Number(savedId)).finally(() => setHistoryLoading(false));
  }, []);

  function handleNewConversation() {
    setConversationId(null);
    setMessages([]);
    localStorage.removeItem(CONVERSATION_ID_KEY);
  }

  function handleSelectConversation(id: number) {
    if (id === conversationId || loading || historyLoading) return;
    setHistoryLoading(true);
    loadConversation(id).finally(() => setHistoryLoading(false));
  }

  function startEditingTitle(c: ChatConversationSummary) {
    setEditingConversationId(c.id);
    setEditingTitleValue(c.title);
  }

  async function saveConversationTitle(id: number) {
    const trimmed = editingTitleValue.trim();
    setEditingConversationId(null);
    if (!trimmed) return;

    await renameConversation(id, trimmed);
    refreshConversations();
  }

  async function handleSend() {
    const text = input.trim();
    if (!text || loading || historyLoading) return;

    const history: ApiChatMessage[] = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);

    try {
      const reply = await sendChatMessage(text, history, conversationId);
      setConversationId(reply.conversation_id);
      localStorage.setItem(CONVERSATION_ID_KEY, String(reply.conversation_id));
      setMessages((prev) => [...prev, { role: "assistant", content: reply.reply, toolCalls: reply.tool_calls }]);
      refreshConversations();
    } catch (err) {
      setMessages((prev) => [...prev, { role: "system", content: String(err) }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-5xl flex gap-4">
      <div className="w-56 shrink-0">
        <div className="text-xs font-semibold tracking-widest uppercase text-ink-muted mb-2">Conversations</div>
        <SecondaryButton className="w-full mb-2" onClick={handleNewConversation} disabled={loading || historyLoading}>
          New Conversation
        </SecondaryButton>
        <div className="space-y-1">
          {conversations.map((c) => (
            <div
              key={c.id}
              onClick={() => handleSelectConversation(c.id)}
              className={`w-full text-left rounded-lg px-2 py-1.5 text-sm transition-colors cursor-pointer ${
                c.id === conversationId ? "bg-surface-2 text-ink" : "text-ink-secondary hover:bg-surface-2"
              }`}
            >
              {editingConversationId === c.id ? (
                <input
                  autoFocus
                  className={`${inputClass} w-full`}
                  value={editingTitleValue}
                  onChange={(e) => setEditingTitleValue(e.target.value)}
                  onClick={(e) => e.stopPropagation()}
                  onBlur={() => saveConversationTitle(c.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") saveConversationTitle(c.id);
                    if (e.key === "Escape") setEditingConversationId(null);
                  }}
                />
              ) : (
                <div
                  className="truncate hover:text-accent transition-colors"
                  title="Click to rename"
                  onClick={(e) => {
                    e.stopPropagation();
                    startEditingTitle(c);
                  }}
                >
                  {c.title}
                </div>
              )}
              <div className="text-xs text-ink-muted">{formatRelativeTime(c.updated_at)}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="flex-1">
        <Card className="mb-4 min-h-[300px] space-y-4">
          {historyLoading ? (
            <p className="text-ink-muted text-sm">Loading conversation...</p>
          ) : messages.length === 0 ? (
            <p className="text-ink-muted text-sm">
              Ask a question about your spending, e.g. &quot;How much did I spend eating out last month?&quot;
            </p>
          ) : (
            messages.map((m, i) => (
              <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
                <div
                  className={`inline-block max-w-[85%] rounded-xl px-3 py-2 text-sm ${
                    m.role === "user"
                      ? "bg-accent text-canvas"
                      : m.role === "system"
                        ? "bg-critical/15 text-critical border border-critical/40"
                        : "bg-surface-2 text-ink"
                  }`}
                >
                  {m.content}
                </div>
                {m.toolCalls && m.toolCalls.length > 0 && (
                  <div className="mt-1 text-left">
                    {m.toolCalls.map((tc, j) => (
                      <ToolResultTable key={j} toolCall={tc} />
                    ))}
                  </div>
                )}
              </div>
            ))
          )}
          {loading && <p className="text-ink-muted text-sm">Thinking...</p>}
        </Card>

        <div className="flex gap-2">
          <input
            className={`${inputClass} flex-1 px-3 py-2`}
            placeholder="Ask about your spending..."
            value={input}
            disabled={historyLoading}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSend();
            }}
          />
          <PrimaryButton className="px-4 py-2" onClick={handleSend} disabled={loading || historyLoading || !input.trim()}>
            Send
          </PrimaryButton>
        </div>
      </div>
    </div>
  );
}
