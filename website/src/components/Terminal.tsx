/**
 * Terminal-styled code block with fake window chrome.
 * Server-rendered (no client JS) — static-export friendly.
 */
export function Terminal({ lines }: { lines: string[] }) {
  return (
    <div className="terminal">
      <div className="term-bar">
        <span />
        <span />
        <span />
      </div>
      <pre>
        <code>{lines.join("\n")}</code>
      </pre>
    </div>
  );
}
