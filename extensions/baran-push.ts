// Pushes the opening words of pi's reply to the Baran iOS app when an
// interactive pi session finishes a turn, and a question at once when pi
// stops to ask one (the ask_user dialog announces itself as `herdr:blocked`).
// Sending is done by `baran push`, which does nothing when no phone is set up.
//
// Install: copy to ~/.pi/agent/extensions/baran-push.ts
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { basename, join } from "node:path";

// Homebrew puts it here; pi does not always inherit the login PATH.
const baran = ["/opt/homebrew/bin/baran", "/usr/local/bin/baran", join(homedir(), ".local/bin/baran")].find((path) =>
  existsSync(path),
);

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

function push(args: string[]) {
  if (!baran) return;
  try {
    const child = spawn(baran, ["push", ...args], { detached: true, stdio: "ignore" });
    child.on("error", () => {});
    child.unref();
  } catch {}
}

export default function (pi) {
  // TUI only: print/RPC/JSON runs are scripts and subagents nobody waits on.
  let interactive = false;
  let folder = "pi";

  // A question waits for an answer, so it goes out even while the Mac is in use.
  pi.events?.on?.("herdr:blocked", (data) => {
    if (!interactive || !data?.active) return;
    const header = typeof data.label === "string" && data.label.trim() ? data.label.trim() : "";
    push(["send", "--kind", "ask", `pi · ${folder}`, header ? `Питає: ${header}` : "Має до вас питання."]);
  });

  pi.on("session_start", (_event, ctx) => {
    interactive = ctx?.mode === "tui";
    folder = basename(ctx?.cwd ?? process.cwd()) || "pi";
  });

  pi.on("agent_settled", (_event, ctx) => {
    // A subagent's finished turn (pi-collaborating-agents sets
    // PI_COLLAB_SUBAGENT_DEPTH) is held back by `baran push` itself while the
    // host's quiet_subagents setting is on; its questions still go out.
    if (!interactive || ctx?.isIdle?.() !== true || !baran) {
      return;
    }
    push(["notify", `pi · ${folder}`, lastReply(ctx) || "Закінчив і чекає на вас."]);
  });
}
