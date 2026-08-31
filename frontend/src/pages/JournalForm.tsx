/**
 * Journal entry form — dynamic double-entry lines with a live
 * debit/credit balance indicator.
 *
 * Backend enforces balance at the RPC level; this UI mirrors that
 * rule with a live indicator and a disabled submit button while
 * unbalanced (PRD: "Submit disabled if SUM(debit) != SUM(credit)").
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "@/lib/api";
import type { AccountOut, JournalCreateResponse } from "@/lib/types";
import { Button, Card, Input, Label, Badge } from "@/components/ui";
import { useUiStore } from "@/stores/ui";
import { CheckCircle2, Loader2, Plus, Save, Trash2, XCircle } from "lucide-react";

/* ------------------------------- helpers -------------------------------- */

/** Fixed-point string math via BigInt — safe for money values. */
function toCents(value: string): bigint {
  const trimmed = value.trim();
  if (!trimmed) return 0n;
  const [rawInt = "0", decPart = ""] = trimmed.split(".");
  const negative = rawInt.startsWith("-");
  const intDigits = negative ? rawInt.slice(1) : rawInt;
  const paddedDec = (decPart + "00").slice(0, 2);
  const digits = (intDigits || "0") + paddedDec;
  const cents = BigInt(digits || "0");
  return negative ? -cents : cents;
}

function fromCents(cents: bigint): string {
  const negative = cents < 0n;
  const abs = negative ? -cents : cents;
  const text = abs.toString().padStart(3, "0");
  const formatted = `${text.slice(0, -2)}.${text.slice(-2)}`;
  return negative ? `-${formatted}` : formatted;
}

/* ------------------------------ line model ------------------------------ */

interface FormLine {
  key: number;
  account_id: string;
  debit_amount: string;
  credit_amount: string;
  description: string;
}

let nextLineKey = 1;

function emptyLine(): FormLine {
  const key = nextLineKey++;
  return {
    key,
    account_id: "",
    debit_amount: "",
    credit_amount: "",
    description: "",
  };
}

/* --------------------------------- form --------------------------------- */

export function JournalFormPage() {
  const navigate = useUiStore((s) => s.navigate);
  const queryClient = useQueryClient();

  const [journalDate, setJournalDate] = useState(() =>
    new Date().toISOString().slice(0, 10),
  );
  const [description, setDescription] = useState("");
  const [currency, setCurrency] = useState("IDR");
  const [lines, setLines] = useState<FormLine[]>([emptyLine(), emptyLine()]);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<AccountOut[]>("/gl/accounts"),
  });

  const createJournal = useMutation({
    mutationFn: (payload: unknown) =>
      api.post<JournalCreateResponse>("/gl/journals", payload),
    onSuccess: (res) => {
      setSuccess(`Saved as DRAFT: ${res.journal_number}`);
      setError(null);
      setLines([emptyLine(), emptyLine()]);
      setDescription("");
      queryClient.invalidateQueries({ queryKey: ["journals"] });
    },
    onError: (err) => {
      setError(err instanceof ApiError ? err.uiMessage : "Failed to save journal.");
      setSuccess(null);
    },
  });

  /* Live balance computation (the core UX of this form). */
  const totals = useMemo(() => {
    let debit = 0n;
    let credit = 0n;
    for (const line of lines) {
      debit += toCents(line.debit_amount);
      credit += toCents(line.credit_amount);
    }
    return { debit, credit, balanced: debit === credit && debit > 0n };
  }, [lines]);

  const updateLine = (key: number, field: keyof FormLine, value: string) => {
    setLines((prev) =>
      prev.map((l) => (l.key === key ? { ...l, [field]: value } : l)),
    );
  };

  const removeLine = (key: number) => {
    setLines((prev) => (prev.length > 2 ? prev.filter((l) => l.key !== key) : prev));
  };

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSuccess(null);

    const payloadLines = lines
      .filter((l) => l.account_id && (l.debit_amount || l.credit_amount))
      .map((l) => ({
        account_id: l.account_id,
        debit_amount: fromCents(toCents(l.debit_amount)),
        credit_amount: fromCents(toCents(l.credit_amount)),
        description: l.description || null,
      }));

    if (payloadLines.length < 2) {
      setError("A journal entry needs at least two lines.");
      return;
    }

    createJournal.mutate({
      journal_date: journalDate,
      description: description || null,
      currency_code: currency,
      lines: payloadLines,
    });
  };

  const accountOptions = accountsQuery.data ?? [];

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">New Journal Entry</h1>
          <p className="text-sm text-muted-foreground">
            Double-entry is enforced by the database engine.
          </p>
        </div>
        <Badge variant={totals.balanced ? "success" : "warning"}>
          {totals.balanced ? (
            <CheckCircle2 className="mr-1 h-3 w-3" />
          ) : (
            <XCircle className="mr-1 h-3 w-3" />
          )}
          {totals.balanced
            ? "Balanced"
            : `Diff ${fromCents(totals.debit - totals.credit)}`}
        </Badge>
      </div>

      <Card>
        <form onSubmit={onSubmit} className="space-y-4 p-4">
          {/* Header fields */}
          <div className="grid grid-cols-3 gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="journal-date">Date</Label>
              <Input
                id="journal-date"
                type="date"
                value={journalDate}
                onChange={(e) => setJournalDate(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="journal-currency">Currency</Label>
              <Input
                id="journal-currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                maxLength={3}
                minLength={3}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="journal-description">Description</Label>
              <Input
                id="journal-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Optional memo"
              />
            </div>
          </div>

          {/* Lines */}
          <div className="space-y-2">
            <div className="grid grid-cols-[1fr_2fr_130px_130px_32px] gap-2 px-1 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              <span>Account</span>
              <span>Memo</span>
              <span className="text-right">Debit</span>
              <span className="text-right">Credit</span>
              <span />
            </div>

            {lines.map((line) => (
              <div key={line.key} className="grid grid-cols-[1fr_2fr_130px_130px_32px] gap-2">
                <select
                  className="h-9 w-full rounded-md border border-input bg-card px-2 text-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  value={line.account_id}
                  onChange={(e) => updateLine(line.key, "account_id", e.target.value)}
                >
                  <option value="">Select account…</option>
                  {accountOptions
                    .filter((a) => a.is_postable && a.is_active)
                    .map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.account_code} — {a.account_name}
                      </option>
                    ))}
                </select>
                <Input
                  value={line.description}
                  onChange={(e) => updateLine(line.key, "description", e.target.value)}
                  placeholder="Line memo"
                />
                <Input
                  className="text-right font-mono"
                  inputMode="decimal"
                  value={line.debit_amount}
                  onChange={(e) => updateLine(line.key, "debit_amount", e.target.value)}
                  placeholder="0.00"
                />
                <Input
                  className="text-right font-mono"
                  inputMode="decimal"
                  value={line.credit_amount}
                  onChange={(e) => updateLine(line.key, "credit_amount", e.target.value)}
                  placeholder="0.00"
                />
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  onClick={() => removeLine(line.key)}
                  disabled={lines.length <= 2}
                  aria-label="Remove line"
                >
                  <Trash2 className="h-4 w-4 text-muted-foreground" />
                </Button>
              </div>
            ))}

            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setLines((prev) => [...prev, emptyLine()])}
            >
              <Plus className="h-3.5 w-3.5" />
              Add line
            </Button>
          </div>

          {/* Totals strip */}
          <div className="grid grid-cols-[1fr_2fr_130px_130px_32px] gap-2 border-t border-border pt-3">
            <span className="col-span-3 text-right text-xs text-muted-foreground">
              Totals
            </span>
            <span className="text-right font-mono text-sm">
              {fromCents(totals.debit)}
            </span>
            <span className="text-right font-mono text-sm">
              {fromCents(totals.credit)}
            </span>
            <span />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
          {success && <p className="text-sm text-success">{success}</p>}

          <div className="flex justify-end gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => navigate("journals")}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={!totals.balanced || createJournal.isPending}>
              {createJournal.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              Save as Draft
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
