/**
 * ApexLedger — Root application component.
 *
 * Sets up React Query, Zustand, and the router.
 * The dark theme is applied at the document level via Tailwind's
 * `darkMode: "class"` strategy.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="dark min-h-screen bg-background text-foreground">
        <main className="flex items-center justify-center min-h-screen">
          <div className="text-center space-y-4">
            <h1 className="text-4xl font-bold tracking-tight">ApexLedger</h1>
            <p className="text-muted-foreground text-lg">
              Open-Core AI-Native Accounting Platform
            </p>
            <p className="text-sm text-muted-foreground">
              Frontend scaffold ready — Phase 3 (UI) coming soon.
            </p>
          </div>
        </main>
      </div>
    </QueryClientProvider>
  );
}
