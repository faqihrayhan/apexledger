/**
 * Chart of Accounts — flat list with type badges, grouped visually
 * by account type.
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AccountOut } from "@/lib/types";
import { Badge, Card } from "@/components/ui";

const TYPE_ORDER = ["ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"] as const;

function typeBadgeVariant(t: string): "default" | "success" | "warning" | "destructive" {
  switch (t) {
    case "ASSET":
      return "success";
    case "REVENUE":
      return "default";
    case "EXPENSE":
      return "warning";
    case "LIABILITY":
    case "EQUITY":
      return "destructive";
    default:
      return "default";
  }
}

export function AccountsPage() {
  const accountsQuery = useQuery({
    queryKey: ["accounts"],
    queryFn: () => api.get<AccountOut[]>("/gl/accounts"),
  });

  const accounts = accountsQuery.data ?? [];

  const grouped = useMemo(() => {
    const map = new Map<string, AccountOut[]>();
    for (const acc of accounts) {
      const list = map.get(acc.account_type) ?? [];
      list.push(acc);
      map.set(acc.account_type, list);
    }
    return map;
  }, [accounts]);

  return (
    <div className="mx-auto max-w-5xl space-y-4 p-6">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">Chart of Accounts</h1>
        <p className="text-sm text-muted-foreground">
          {accounts.length} accounts — grouped by type.
        </p>
      </div>

      {accountsQuery.isLoading ? (
        <div className="flex h-40 items-center justify-center text-sm text-muted-foreground">
          Loading…
        </div>
      ) : accounts.length === 0 ? (
        <Card className="flex h-40 items-center justify-center">
          <p className="text-sm text-muted-foreground">
            No accounts yet. Finance roles can create them via the API.
          </p>
        </Card>
      ) : (
        TYPE_ORDER.filter((t) => grouped.has(t)).map((t) => (
          <div key={t} className="space-y-1.5">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              {t}
            </h2>
            <Card className="divide-y divide-border/50">
              {grouped.get(t)!.map((acc) => (
                <div key={acc.id} className="flex items-center justify-between px-4 py-2 text-sm">
                  <div className="flex items-center gap-3">
                    <span className="w-16 font-mono text-xs text-muted-foreground">
                      {acc.account_code}
                    </span>
                    <span className="truncate">{acc.account_name}</span>
                    {!acc.is_active && (
                      <Badge variant="outline" className="text-[10px]">
                        INACTIVE
                      </Badge>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    {!acc.is_postable && (
                      <Badge variant="outline" className="text-[10px]">
                        HEADER
                      </Badge>
                    )}
                    <Badge variant={typeBadgeVariant(acc.account_type)}>
                      {acc.normal_balance}
                    </Badge>
                  </div>
                </div>
              ))}
            </Card>
          </div>
        ))
      )}
    </div>
  );
}
