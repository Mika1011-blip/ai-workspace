# Crew roles

One file per role: `<role>.md`. Each brief states:

- **Owns** — the specific files/folders this role is responsible for.
- **Must not touch** — anything outside that scope.
- **Reports back** — how and when it signals it's done (e.g. opens a PR,
  messages the lead).
- Ends with: `Follow COMMS.md.`

No roles exist yet. `/spawn-worker <role> "<task>"` creates `<role>.md` on
demand if it's missing — it will ask the lead for the brief and save it here
before spawning.
