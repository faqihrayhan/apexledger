/**
 * Main application layout — Left Navigation, Main Content, Right AI Sidebar.
 *
 * The AI sidebar pushes (not overlays) the main content, matching the
 * Cursor/Linear-style shell from the frontend PRD.
 */

import { useEffect } from "react";
import { useAuthStore } from "@/stores/auth";
import { useUiStore, type Page } from "@/stores/ui";
import { AiChat } from "@/components/AiChat";
import { Button } from "@/components/ui";
import { cn } from "@/lib/utils";
import {
  BookOpen,
  FilePlus2,
  LayoutDashboard,
  LogOut,
  Scale,
  Sparkles,
  Users,
} from "lucide-react";

/* ------------------------------ nav config ------------------------------ */

const NAV_ITEMS: Array<{
  page: Page;
  label: string;
  icon: typeof LayoutDashboard;
}> = [
  { page: "dashboard", label: "Dashboard", icon: LayoutDashboard },
  { page: "journals", label: "Journals", icon: BookOpen },
  { page: "journal-new", label: "New Journal", icon: FilePlus2 },
  { page: "trial-balance", label: "Trial Balance", icon: Scale },
  { page: "accounts", label: "Accounts", icon: Users },
];

/* ----------------------------- AI sidebar ------------------------------- */

function AiSidebar() {
  return <AiChat />;
}

/* ------------------------------- header --------------------------------- */

function Header() {
  const toggleAiSidebar = useUiStore((s) => s.toggleAiSidebar);
  const aiSidebarOpen = useUiStore((s) => s.aiSidebarOpen);
  const role = useAuthStore((s) => s.role);

  return (
    <header className="flex h-12 shrink-0 items-center justify-between border-b border-border bg-background px-4">
      <div className="flex items-center gap-2">
        <div className="inline-flex h-6 w-6 items-center justify-center rounded-md border border-border bg-secondary">
          <BookOpen className="h-3.5 w-3.5 text-primary" />
        </div>
        <span className="text-sm font-semibold tracking-tight">ApexLedger</span>
      </div>

      <div className="flex items-center gap-3">
        <span className="text-xs text-muted-foreground">{role ?? ""}</span>
        <Button
          variant="outline"
          size="sm"
          onClick={toggleAiSidebar}
          aria-pressed={aiSidebarOpen}
        >
          <Sparkles className="h-3.5 w-3.5" />
          AI
          <kbd className="ml-1 rounded border border-border px-1 text-[10px] text-muted-foreground">
            ⌘J
          </kbd>
        </Button>
      </div>
    </header>
  );
}

/* ------------------------------ left nav -------------------------------- */

function LeftNav() {
  const page = useUiStore((s) => s.page);
  const navigate = useUiStore((s) => s.navigate);
  const logout = useAuthStore((s) => s.logout);

  return (
    <nav className="flex h-full w-52 shrink-0 flex-col border-r border-border bg-card">
      <div className="flex h-12 items-center px-4">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          General Ledger
        </span>
      </div>

      <div className="flex-1 space-y-0.5 p-2">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = page === item.page;
          return (
            <button
              key={item.page}
              onClick={() => navigate(item.page)}
              className={cn(
                "flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm transition-colors",
                active
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:bg-accent/50 hover:text-foreground",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </button>
          );
        })}
      </div>

      <div className="border-t border-border p-2">
        <button
          onClick={logout}
          className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent/50 hover:text-foreground"
        >
          <LogOut className="h-4 w-4" />
          Sign out
        </button>
      </div>
    </nav>
  );
}

/* ------------------------------ the layout ------------------------------ */

export function AppLayout({ children }: { children: React.ReactNode }) {
  const aiSidebarOpen = useUiStore((s) => s.aiSidebarOpen);
  const toggleAiSidebar = useUiStore((s) => s.toggleAiSidebar);

  // Global Cmd/Ctrl+J shortcut to toggle the AI sidebar.
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "j") {
        e.preventDefault();
        toggleAiSidebar();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [toggleAiSidebar]);

  return (
    <div className="flex h-screen flex-col">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <LeftNav />
        <main className="flex-1 overflow-y-auto">{children}</main>
        {aiSidebarOpen && <AiSidebar />}
      </div>
    </div>
  );
}
