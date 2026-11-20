# Changelog

The Baran app shows the entries newer than the installed version next to its
update button. One version per `## ` heading, one change per `- ` line.

## 0.3.20

- The stock phrases in pushes ("Asks: …", "Needs permission", "Finished and is waiting for you.") are in English; the app shows them in the phone's language

## 0.3.19

- `baran pair` on a Mac puts its Bonjour name (`Name.local`) into the code, so the saved host survives a new address from the router

## 0.3.18

- `baran stats`: CPU, memory, network, disk and the busiest processes, for the app's server view
- `baran ports`: dev servers your processes listen on, with the page title, ready to open from the phone
- Pushes and quiet mode recognise herdr-core terminals

## 0.3.17

- Phones can ask for questions and permission requests only

## 0.3.16

- Host settings the app changes: quiet nested agents, quiet outside herdr, background git fetch
- pi subagents follow the quiet nested agents setting

## 0.3.15

- Every push names its pane
- pi subagents no longer send "finished" pushes

## 0.3.14

- A Codex permission request reaches the phone even while you use the Mac

## 0.3.13

- Questions and permission requests arrive as their own, louder kind of push and say where they were asked
- A status line script that runs `baran statusline` counts as installed

## 0.3.10

- `baran pair` uses the LAN address, not a VPN or proxy tunnel's
- The installer links into Homebrew's bin on a Mac

## 0.3.9

- `baran attach` starts a stopped herdr server in the GUI session first

## 0.3.8

- Pushes go through the baran.party relay, sealed on the host with a key only your phone has
