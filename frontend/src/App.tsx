/**
 * ApexLedger — Root application component.
 *
 * Wires React Query, the auth gate (login/setup wizard vs. the app
 * shell), and the page switcher from the UI store.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useAuthStore } from "@/stores/auth";
import { useUiStore } from "@/stores/ui";
import { AppLayout } from "@/components/AppLayout";
import { LoginPage } from "@/pages/Login";
import { DashboardPage } from "@/pages/Dashboard";
import { JournalsPage } from "@/pages/Journals";
import { JournalFormPage } from "@/pages/JournalForm";
import { TrialBalancePage } from "@/pages/TrialBalance";
import { AccountsPage } from "@/pages/Accounts";
import { PayrollPage } from "@/pages/Payroll";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

function CurrentPage() {
  const page = useUiStore((s) => s.page);

  switch (page) {
    case "dashboard":
      return <DashboardPage />;
    case "journals":
      return <JournalsPage />;
    case "journal-new":
      return <JournalFormPage />;
    case "trial-balance":
      return <TrialBalancePage />;
    case "accounts":
      return <AccountsPage />;
    case "payroll":
      return <PayrollPage />;
    default:
      return <DashboardPage />;
  }
}

function Shell() {
  const isAuthenticated = useAuthStore((s) => s.token !== null);

  if (!isAuthenticated) {
    return <LoginPage />;
  }

  return (
    <AppLayout>
      <CurrentPage />
    </AppLayout>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="dark min-h-screen bg-background text-foreground">
        <Shell />
      </div>
    </QueryClientProvider>
  );
}
