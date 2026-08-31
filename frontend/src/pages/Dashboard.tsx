/**
 * Dashboard — financial summary cards scoped to the current entity.
 */

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { JournalSummary, TrialBalanceReport } from "@/lib/types";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { Badge, Card } from "@/components/ui";
import { BookOpen, FilePlus2, Scale } from "lucide-react";

function formatAmount(value: string): string {
  const [intPart = "0", decPart = "00"] = value.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const dec = (decPart + "00").slice(0, 2);
  return `${grouped}.${dec}`;
}

export function DashboardPage() {
  const navigate = useUiStore((s) => s.navigate);
  const role = useAuthStore((s) => s.role);

  const journalsQuery = useQuery({
    queryKey: ["journals"],
    queryFn: () => api.get<JournalSummary[]>("/gl/journals"),
  });

  const tbQuery = useQuery({
    queryKey: ["trial-balance", "today"],
    queryFn: () =>
      api.get<TrialBalanceReport>(
        `/gl/reports/trial-balance?as_of=${encodeURIComponent(
          new Date().toISOString().slice(0, 10),
        )}`,
      ),
  });

  const journals = journalsQuery.data ?? [];
  const drafts = journals.filter((j) => j.status === "DRAFT").length;
  const tb = tbQuery.data;

  return (
    <div className="mx-auto max-w-6xl space-y-4 p-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">Signed in as {role}</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-3 gap-4">
        <Card
          className="cursor-pointer p-4 transition-colors hover:border-primary/50"
          onClick={() => navigate("journals")}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Total journals</span>
            <BookOpen className="h-4 w-4 text-muted-foreground" />
          </div>
          <p className="mt-2 text-2xl font-semibold tracking-tight">
            {journals.length}
          </p>
        </Card>

        <Card
          className="cursor-pointer p-4 transition-colors hover:border-primary/50"
          onClick={() => navigate("journals")}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Awaiting posting</span>
            <FilePlus2 className="h-4 w-4 text-amber-500" />
          </div>
          <p className="mt-2 text-2xl font-semibold tracking-tight text-amber-500">
            {drafts}
          </p>
        </Card>

        <Card
          className="cursor-pointer p-4 transition-colors hover:border-primary/50"
          onClick={() => navigate("trial-balance")}
        >
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">Trial balance</span>
            <Scale className="h-4 w-4 text-muted-foreground" />
          </div>
          <p className="mt-2 text-2xl font-semibold tracking-tight">
            {tb ? formatAmount(tb.grand_total_debit) : "—"}
          </p>
          {tb && (
            <Badge
              variant={tb.is_balanced ? "success" : "destructive"}
              className="mt-2"
            >
              {tb.is_balanced ? "Balanced" : "Out of balance"}
            </Badge>
          )}
        </Card>
      </div>

      {/* Recent journals list */}
      <div>
        <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Recent journals
        </h2>
        <Card className="divide-y divide-border/50">
          {journalsQuery.isLoading ? (
            <div className="flex h-24 items-center justify-center text-sm text-muted-foreground">
              Loading…
            </div>
          ) : journals.length === 0 ? (
            <div className="flex h-24 items-center justify-center">
              <p className="text-sm text-muted-foreground">
                No journals yet — create your first entry.
              </p>
            </div>
          ) : (
            journals.slice(0, 5).map((j) => (
              <div
                key={j.id}
                className="flex items-center justify-between px-4 py-2.5 text-sm"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs text-muted-foreground">
                    {j.journal_number}
                  </span>
                  <span className="truncate">{j.description ?? "—"}</span>
                </div>
                <div className="flex items-center gap-3">
                  <Badge
                    variant={
                      j.status === "POSTED"
                        ? "success"
                        : j.status === "DRAFT"
                          ? "warning"
                          : "destructive"
                    }
                  >
                    {j.status}
                  </Badge>
                  <span className="font-mono text-xs">
                    {formatAmount(j.total_amount)}
                  </span>
                </div>
              </div>
            ))
          )}
        </Card>
      </div>
    </div>
  );
}
