// Pushes the opening words of pi's reply to the Baran iOS app when an
// interactive pi session finishes a turn. Sending is done by `baran push`,
// which does nothing when no phone or APNs key is set up.
//
// Install: copy to ~/.pi/agent/extensions/baran-push.ts
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { basename } from "node:path";

// Homebrew puts it here; pi does not always inherit the login PATH.
const baran = ["/opt/homebrew/bin/baran", "/usr/local/bin/baran"].find((path) => existsSync(path));

function lastReply(ctx): string {
  try {
    const entries = ctx?.sessionManager?.getBranch?.() ?? [];
    for (let i = entries.length - 1; i >= 0; i--) {
      const message = entries[i]?.type === "message" ? entries[i].message : undefined;
      if (message?.role !== "assistant") continue;
      const content = typeof message.content === "string" ? [{ type: "text", text: message.content }] : message.content ?? [];
      const text = content.filter((part) => part?.type === "text").map((part) => part.text ?? "").join("\n").trim();
      if (text) return text.slice(0, 2000);
    }
  } catch {}
  return "";
}

export default function (pi) {
  // TUI only: print/RPC/JSON runs are scripts and subagents nobody waits on.
  let interactive = false;

  pi.on("session_start", (_event, ctx) => {
    interactive = ctx?.mode === "tui";
  });

  pi.on("agent_settled", (_event, ctx) => {
    if (!interactive || ctx?.isIdle?.() !== true || !baran) {
      return;
    }
    const folder = basename(ctx?.cwd ?? process.cwd()) || "pi";
    try {
      const child = spawn(baran, ["push", "notify", `pi · ${folder}`, lastReply(ctx) || "Закінчив і чекає на вас."], {
        detached: true,
        stdio: "ignore",
      });
      child.on("error", () => {});
      child.unref();
    } catch {}
  });
}
