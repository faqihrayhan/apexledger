/**
 * Trial balance view — per-account net debit/credit with the
 * grand-total proof (debit == credit) highlighted at the footer.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { TrialBalanceReport } from "@/lib/types";
import { Badge, Card, Input, Label } from "@/components/ui";
import { CheckCircle2, Loader2, XCircle } from "lucide-react";

function formatAmount(value: string): string {
  const [intPart = "0", decPart = "00"] = value.split(".");
  const grouped = intPart.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  const dec = (decPart + "00").slice(0, 2);
  return `${grouped}.${dec}`;
}

export function TrialBalancePage() {
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));

  const reportQuery = useQuery({
    queryKey: ["trial-balance", asOf],
    queryFn: () =>
      api.get<TrialBalanceReport>(
        `/gl/reports/trial-balance?as_of=${encodeURIComponent(asOf)}`,
      ),
  });

  const report = reportQuery.data;

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold tracking-tight">Trial Balance</h1>
          <p className="text-sm text-muted-foreground">
            As of {asOf} — posted entries only.
          </p>
        </div>
        {report && (
          <Badge variant={report.is_balanced ? "success" : "destructive"}>
            {report.is_balanced ? (
              <CheckCircle2 className="mr-1 h-3 w-3" />
            ) : (
              <XCircle className="mr-1 h-3 w-3" />
            )}
            {report.is_balanced ? "Balanced" : "Out of balance"}
          </Badge>
        )}
      </div>

      <div className="flex items-end gap-3">
        <div className="space-y-1.5">
          <Label htmlFor="tb-as-of">As of date</Label>
          <Input
            id="tb-as-of"
            type="date"
            className="w-44"
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
          />
        </div>
      </div>

      <Card className="overflow-hidden">
        <div className="grid grid-cols-[110px_1fr_120px_120px_120px_120px] items-center gap-2 border-b border-border bg-secondary/50 px-4 py-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          <span>Code</span>
          <span>Account</span>
          <span className="text-right">Total Debit</span>
          <span className="text-right">Total Credit</span>
          <span className="text-right">Net Debit</span>
          <span className="text-right">Net Credit</span>
        </div>

        {reportQuery.isLoading ? (
          <div className="flex h-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : !report || report.rows.length === 0 ? (
          <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
            No posted journal entries for this period.
          </div>
        ) : (
          <div className="max-h-[calc(100vh-420px)] overflow-auto">
            {report.rows.map((row) => (
              <div
                key={row.account_id}
                className="grid grid-cols-[110px_1fr_120px_120px_120px_120px] items-center gap-2 border-b border-border/50 px-4 py-2 text-sm"
              >
                <span className="font-mono text-xs text-muted-foreground">
                  {row.account_code}
                </span>
                <span className="truncate">{row.account_name}</span>
                <span className="text-right font-mono text-xs">
                  {formatAmount(row.total_debit)}
                </span>
                <span className="text-right font-mono text-xs">
                  {formatAmount(row.total_credit)}
                </span>
                <span className="text-right font-mono text-xs">
                  {row.net_debit === "0" ? "" : formatAmount(row.net_debit)}
                </span>
                <span className="text-right font-mono text-xs">
                  {row.net_credit === "0" ? "" : formatAmount(row.net_credit)}
                </span>
              </div>
            ))}
          </div>
        )}

        {/* Grand totals footer */}
        {report && (
          <div className="grid grid-cols-[110px_1fr_120px_120px_120px_120px] items-center gap-2 border-t-2 border-border bg-secondary/50 px-4 py-2.5 text-sm font-semibold">
            <span />
            <span>Grand Totals</span>
            <span className="text-right font-mono text-xs">
              {formatAmount(report.grand_total_debit)}
            </span>
            <span className="text-right font-mono text-xs">
              {formatAmount(report.grand_total_credit)}
            </span>
            <span className="text-right font-mono text-xs text-muted-foreground">
              {report.is_balanced ? "=" : "≠"}
            </span>
            <span className="text-right font-mono text-xs text-muted-foreground">
              {report.is_balanced ? "=" : "≠"}
            </span>
          </div>
        )}
      </Card>
    </div>
  );
}
