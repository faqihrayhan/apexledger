/**
 * Journal entry list — virtualized table able to render thousands of
 * rows at 60fps, with status filters and post/reverse actions.
 */

import { useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { api, ApiError } from "@/lib/api";
import type { JournalPostResponse, JournalReverseResponse, JournalSummary } from "@/lib/types";
import { Badge, Button, Card } from "@/components/ui";
import { useUiStore } from "@/stores/ui";
import { cn } from "@/lib/utils";
import { FilePlus2, Loader2, Send, Undo2 } from "lucide-react";

/* --------------------------------- filters ------------------------------- */

type StatusFilter = "ALL" | "DRAFT" | "POSTED" | "REVERSED";

const STATUS_FILTERS: StatusFilter[] = ["ALL", "DRAFT", "POSTED", "REVERSED"];

function statusBadgeVariant(status: string): "warning" | "success" | "destructive" | "default" {
  switch (status) {
    case "DRAFT":
      return "warning";
    case "POSTED":
      return "success";
    case "REVERSED":
      return "destructive";
    default:
      return "default";
  }
}

function formatAmount(value: string): string {
  // Group thousands with commas for display; keep 2 decimals.
  const [intPart = "0", decPart = "00"] = value.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const dec = (decPart + "00").slice(0, 2);
  return `${grouped}.${dec}`;
}

/* --------------------------------- page ---------------------------------- */

export function JournalsPage() {
  const navigate = useUiStore((s) => s.navigate);
  const queryClient = useQueryClient();
  const [filter, setFilter] = useState<StatusFilter>("ALL");
  const [actionError, setActionError] = useState<string | null>(null);

  const journalsQuery = useQuery({
    queryKey: ["journals"],
    queryFn: () => api.get<JournalSummary[]>("/gl/journals"),
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["journals"] });
  };

  const postJournal = useMutation({
    mutationFn: (id: string) =>
      api.post<JournalPostResponse>(`/gl/journals/${id}/post`),
    onSuccess: invalidate,
    onError: (err) =>
      setActionError(err instanceof ApiError ? err.uiMessage : "Failed to post."),
  });

  const reverseJournal = useMutation({
    mutationFn: (id: string) =>
      api.post<JournalReverseResponse>(`/gl/journals/${id}/reverse`, {
        reversal_date: new Date().toISOString().slice(0, 10),
        reason: "Reversed from UI",
      }),
    onSuccess: invalidate,
    onError: (err) =>
      setActionError(err instanceof ApiError ? err.uiMessage : "Failed to reverse."),
  });

  const rows = useMemo(() => {
    const data = journalsQuery.data ?? [];
    return filter === "ALL" ? data : data.filter((j) => j.status === filter);
  }, [journalsQuery.data, filter]);

  /* Virtualization setup — parent scrolls, rows are absolutely positioned. */
  const parentRef = useRef<HTMLDivElement>(null);
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 44,
    overscan: 10,
  });

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Journal Entries</h1>
          <p className="text-sm text-muted-foreground">
            {rows.length} entr{rows.length === 1 ? "y" : "ies"}
          </p>
        </div>
        <Button onClick={() => navigate("journal-new")}>
          <FilePlus2 className="h-4 w-4" />
          New Journal
        </Button>
      </div>

      {/* Status filter pills */}
      <div className="flex items-center gap-1.5">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
              filter === s
                ? "border-border bg-accent text-accent-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {s}
          </button>
        ))}
      </div>

      {actionError && (
        <p className="text-sm text-destructive">{actionError}</p>
      )}

      <Card className="overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[140px_110px_1fr_90px_130px_170px] items-center gap-2 border-b border-border bg-secondary/50 px-4 py-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          <span>Number</span>
          <span>Date</span>
          <span>Description</span>
          <span className="text-center">Status</span>
          <span className="text-right">Amount</span>
          <span className="text-right">Actions</span>
        </div>

        {/* Virtualized body */}
        <div ref={parentRef} className="h-[calc(100vh-380px)] min-h-80 overflow-auto">
          {journalsQuery.isLoading ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : rows.length === 0 ? (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              No journal entries yet.
            </div>
          ) : (
            <div
              style={{
                height: virtualizer.getTotalSize(),
                position: "relative",
                width: "100%",
              }}
            >
              {virtualizer.getVirtualItems().map((virtualRow) => {
                const journal = rows[virtualRow.index];
                if (!journal) return null;
                return (
                  <div
                    key={journal.id}
                    className="absolute left-0 top-0 w-full border-b border-border/50 px-4"
                    style={{ height: virtualRow.size, transform: `translateY(${virtualRow.start}px)` }}
                  >
                    <div className="grid h-full grid-cols-[140px_110px_1fr_90px_130px_170px] items-center gap-2 text-sm">
                      <span className="truncate font-mono text-xs text-muted-foreground">
                        {journal.journal_number}
                      </span>
                      <span className="text-xs">{journal.journal_date}</span>
                      <span className="truncate">
                        {journal.description ?? "—"}
                        {journal.is_reversal && (
                          <Badge variant="destructive" className="ml-2">REV</Badge>
                        )}
                      </span>
                      <span className="flex justify-center">
                        <Badge variant={statusBadgeVariant(journal.status)}>
                          {journal.status}
                        </Badge>
                      </span>
                      <span className="text-right font-mono text-xs">
                        {formatAmount(journal.total_amount)}
                      </span>
                      <span className="flex justify-end gap-1">
                        {journal.status === "DRAFT" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={postJournal.isPending}
                            onClick={() => {
                              setActionError(null);
                              postJournal.mutate(journal.id);
                            }}
                          >
                            <Send className="h-3 w-3" />
                            Post
                          </Button>
                        )}
                        {journal.status === "POSTED" && (
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={reverseJournal.isPending}
                            onClick={() => {
                              setActionError(null);
                              reverseJournal.mutate(journal.id);
                            }}
                          >
                            <Undo2 className="h-3 w-3" />
                            Reverse
                          </Button>
                        )}
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </Card>
    </div>
  );
}
