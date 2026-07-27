import { useState } from "react";
import { sendChatMessage, type ChatMessage as ApiChatMessage, type ToolCall } from "./api";
import { formatAmount } from "./format";

interface DisplayMessage {
  role: "user" | "assistant" | "system";
  content: string;
  toolCalls?: ToolCall[];
}

function MiniTable({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto mt-1">
      <table className="text-xs border border-gray-200 rounded">
        <thead>
          <tr className="bg-gray-50 text-gray-600">
            {headers.map((h) => (
              <th key={h} className="px-2 py-1 text-left font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={i} className="border-t border-gray-100">
              {row.map((cell, j) => (
                <td key={j} className="px-2 py-1 text-gray-700 whitespace-nowrap">
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
    return <p className="text-xs text-red-600 mt-1">Tool error: {String((result as { error: unknown }).error)}</p>;
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

  if (name === "get_category_trends" && result && typeof result === "object" && !Array.isArray(result)) {
    const trends = result as Record<string, { category_name: string; total_cents: number }[]>;
    return (
      <div className="space-y-2">
        {Object.entries(trends).map(([month, rows]) => (
          <div key={month}>
            <div className="text-xs font-medium text-gray-500 mt-1">{month}</div>
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

  return <pre className="text-xs text-gray-500 mt-1 whitespace-pre-wrap">{JSON.stringify(result, null, 2)}</pre>;
}

export default function Chat() {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSend() {
    const text = input.trim();
    if (!text || loading) return;

    const history: ApiChatMessage[] = messages
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role as "user" | "assistant", content: m.content }));

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);

    try {
      const reply = await sendChatMessage(text, history);
      setMessages((prev) => [...prev, { role: "assistant", content: reply.reply, toolCalls: reply.tool_calls }]);
    } catch (err) {
      setMessages((prev) => [...prev, { role: "system", content: String(err) }]);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="max-w-3xl">
      <div className="bg-white border border-gray-200 rounded shadow-sm p-4 mb-4 min-h-[300px] space-y-4">
        {messages.length === 0 ? (
          <p className="text-gray-500 text-sm">
            Ask a question about your spending, e.g. &quot;How much did I spend eating out last month?&quot;
          </p>
        ) : (
          messages.map((m, i) => (
            <div key={i} className={m.role === "user" ? "text-right" : "text-left"}>
              <div
                className={`inline-block max-w-[85%] rounded px-3 py-2 text-sm ${
                  m.role === "user"
                    ? "bg-blue-600 text-white"
                    : m.role === "system"
                      ? "bg-red-50 text-red-700 border border-red-200"
                      : "bg-gray-100 text-gray-900"
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
        {loading && <p className="text-gray-400 text-sm">Thinking...</p>}
      </div>

      <div className="flex gap-2">
        <input
          className="flex-1 border border-gray-300 rounded px-3 py-2 text-sm"
          placeholder="Ask about your spending..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSend();
          }}
        />
        <button
          className="px-4 py-2 bg-blue-600 text-white rounded text-sm font-medium hover:bg-blue-700 disabled:opacity-50"
          onClick={handleSend}
          disabled={loading || !input.trim()}
        >
          Send
        </button>
      </div>
    </div>
  );
}
