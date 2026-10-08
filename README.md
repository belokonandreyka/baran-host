# baran-host

Host-side companion of **Baran**, an iOS SSH terminal for people who run coding
agents (pi, Claude Code, Codex) on their own machines. It runs on the machine
you connect to and does three things:

- `baran pair` shows a QR code in the terminal; the app scans it and gets the
  address, user, port and a freshly authorized SSH key.
- `baran push` sends a push notification to your phone straight through Apple's
  push service (no server in between) when an agent is waiting for you.
- `baran statusline` is a Claude Code status line that also records your plan
  limits, so the app can show them. Every five minutes it also asks Anthropic
  for the per-model weekly limits (Fable), using Claude Code's own login.

Needs Python 3 and nothing else. macOS and Linux.

## Install

```sh
brew install belokonandreyka/baran/baran
```

Without Homebrew (Linux, a NAS):

```sh
curl -fsSL https://baran.party/install.sh | sh
```

That unpacks the tools into `~/.local/share/baran` and links `~/.local/bin/baran`;
run it again to update. It needs curl, tar and python3.

## Pair a machine

```sh
baran pair                    # new key for the phone + QR with everything
baran pair --no-key           # address only; choose the key in the app
baran pair --host 10.0.0.5 --port 2222 --name NAS
```

By default this creates an ed25519 key, appends its public half to
`~/.ssh/authorized_keys` (comment `baran <date>`) and puts the private half
into the QR code only. Whoever photographs the code can log in as you: show it
to your own phone, then press Enter to wipe it from the screen.

## Notifications

`baran push` needs an APNs key from your Apple developer account:

```
~/.config/baran/apns.json     {"team_id": "...", "key_id": "...", "key_path": "~/.config/baran/AuthKey_XXXX.p8"}
~/.config/baran/devices.json  written by the app over SSH when you enable notifications
```

Without either file it does nothing and exits 0, so a hook never breaks an agent.

```sh
baran push send "Title" "Body"      # always
baran push notify "Title" "Body"    # silent while this Mac's keyboard or mouse is in use,
                                    # except for phones set to "even when I'm at the Mac"
```

### Claude Code

In `~/.claude/settings.json`:

```json
{
  "statusLine": {"type": "command", "command": "baran statusline"},
  "hooks": {
    "Stop": [{"hooks": [{"type": "command", "command": "baran push claude-hook"}]}],
    "PermissionRequest": [{"hooks": [{"type": "command", "command": "baran push claude-hook"}]}],
    "PreToolUse": [{"matcher": "AskUserQuestion|ExitPlanMode", "hooks": [{"type": "command", "command": "baran push claude-hook"}]}]
  }
}
```

The notification body is the opening of Claude's last reply, so that text passes
through Apple's push service.

### Codex

`baran integrate codex` adds `baran push codex-hook` for Stop and
PermissionRequest to `~/.codex/hooks.json`, after any hooks already there.
Codex runs hooks only with `hooks = true` under `[features]` in
`~/.codex/config.toml`, and may ask to trust new ones.

### Hermes

`baran integrate hermes` installs the `baran-push` plugin into
`~/.hermes/plugins` and enables it. It pushes only from interactive (cli)
sessions: the reply, an approval request, a clarifying question. Restart
hermes sessions and the gateway to load it.

### pi

Copy `extensions/baran-push.ts` to `~/.pi/agent/extensions/`.

## Host status

`baran doctor` lists what works on this host (APNs key, registered phone, push
tools, herdr, SFTP), its version against the newest one, and the agent hooks.
`baran integrate claude|codex|hermes|pi` sets the hooks up and `--remove` takes them out;
`~/.claude/settings.json` is backed up to `settings.json.bak-baran` first, and
another status line is left alone. The app runs both over SSH (long-press a
connection → Host status).

## Files the app and the host share

| File | Written by | Read by |
|---|---|---|
| QR payload: `{"herdr":1,"n":name,"h":host,"p":port,"u":user,"c":command,"k":key}` | `baran pair` | app |
| `~/.config/baran/devices.json` | app | `baran push` |
| `~/.claude/usage-limits.json` | `baran statusline` | app |
| `~/.claude/usage-scoped.json` | `baran statusline` | app |

## License

MIT
