# baran-host

Host-side companion of **Baran**, an iOS SSH terminal for people who run coding
agents (pi, Claude Code, Codex) on their own machines. It runs on the machine
you connect to and does three things:

- `baran pair` shows a QR code in the terminal; the app scans it and gets the
  address, user, port and a freshly authorized SSH key (`--text` prints the same
  as one line to paste, for when the code cannot be scanned, e.g. `baran pair`
  runs in Baran's own terminal on the phone).
- `baran push` sends a push notification to your phone when an agent is waiting
  for you. The text is sealed on this machine with a key only your phone has,
  and goes through the push relay at baran.party, which holds the APNs key and
  cannot read it.
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
baran pair --text             # one line to paste instead of the QR (+ → Paste code)
```

By default this creates an ed25519 key, appends its public half to
`~/.ssh/authorized_keys` (comment `baran <date>`) and puts the private half
into the QR code only. Whoever photographs the code can log in as you: show it
to your own phone, then press Enter to wipe it from the screen.

## Notifications

Turn notifications on in the app: it registers the phone with the relay
(baran.party) and writes `~/.config/baran/devices.json` on every host over SSH,
with the relay address, the phone's id and secret, and the key that seals the
text (ChaCha20-Poly1305, `libexec/seal.py`). Apple and the relay see only
"new message" and the sealed box; the phone's notification extension opens it.
No APNs key is needed on the host.

Phones registered by older app versions carry a raw APNs token instead; those
are sent to Apple directly and need the key from the Apple developer account:

```
~/.config/baran/apns.json     {"team_id": "...", "key_id": "...", "key_path": "~/.config/baran/AuthKey_XXXX.p8"}
```

Without phones it does nothing and exits 0, so a hook never breaks an agent.

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

The notification body is the opening of Claude's last reply. Through the relay
it travels sealed; only for direct (older) entries does it pass through Apple's
push service as plain text.

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
| QR payload: `{"herdr":1,"n":name,"h":host,"p":port,"u":user,"c":command,"s":ed25519 seed}`; with `--text`, `baran:` + its base64url | `baran pair` | app |
| `~/.config/baran/devices.json` (relay id, secret and seal key per phone; mode 600) | app | `baran push` |
| `~/.claude/usage-limits.json` | `baran statusline` | app |
| `~/.claude/usage-scoped.json` | `baran statusline` | app |

## License

MIT
