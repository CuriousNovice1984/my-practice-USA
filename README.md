# my-practice (USA)

**Self-hosted practice management for a solo, self-pay counseling practice in the US.**
Sessions, invoices, notes, banking and client paperwork, on your own hardware behind a
Tailscale tailnet.

This is a fork of [dholbach/my-practice](https://github.com/dholbach/my-practice), a
Django app built for a German practice. It has been converted for a Texas-based LPC
licensed in TX, UT, VA and NM. The fork does **not** pull updates from upstream.
Changes made here are local to this repository.

---

## What changed from upstream

| Area | This fork |
|---|---|
| Locale | English only, `America/Chicago`, USD (`$1,234.56`), dates shown as `DD MMM YY` (`05 Mar 26`) |
| Holidays | US federal holidays with observed dates, used for capacity and working-day math |
| Taxes | IRS Form 1040-ES quarterly periods and due dates, a self-employment tax estimate, and the simplified home-office deduction. No VAT. |
| Billing | Self-pay invoices only. No insurance claims and no vendor integrations. |
| Licensure | A state-license tracker (Practice → Licenses) with renewal alerts in the Focus Queue. Each client has a state, and you get a warning when a client's state isn't one you're licensed in. |
| Banking | A Plaid landing page (**Bank connection**). It imports transactions into the existing review and matching pipeline. US-format CSV import still works. |
| Client forms | A private, expiring upload link per client, so clients download your blank forms and upload completed ones. See [CLIENT_PORTAL.md](docs/operations/CLIENT_PORTAL.md). |
| Records | Records retention (default 7 years, configurable) replaces the GDPR deletion flow |
| Removed | German fee schedule (GebüH), German contract and intake PDFs, the language switcher, update-check pings and GHCR image pulls |
| Interface | A photographic, assistant-style redesign: every section opens on its own real photograph, and the dashboard greets you by time of day with a briefing of what needs you. See [CREDITS.md](app/static/scenes/CREDITS.md) for the photography. |
| Kept | Google Calendar sync and email sending |

---

## Running it

**Requirements**: Docker with the Compose plugin, Git, Python 3.

```bash
git clone <this repo> my-practice
cd my-practice
./prod.py setup     # generates secrets, builds the image locally, starts the stack
```

`./prod.py update` runs `git pull --ff-only` on **this** repository, rebuilds and
restarts. Nothing is downloaded from upstream or from a container registry.

Expose the main app only on your tailnet (`tailscale serve`). The client upload portal
is the one exception: it is published on a separate Funnel port. See
[CLIENT_PORTAL.md](docs/operations/CLIENT_PORTAL.md).

Settings that matter for this setup (see `.env.example`):

```bash
TZ=America/Chicago
PLAID_CLIENT_ID=...          # optional; Bank connection page stays inert without it
PLAID_SECRET=...
PLAID_ENV=production         # or sandbox
PORTAL_BASE_URL=https://practice-box.your-tailnet.ts.net:8443
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,practice-box.your-tailnet.ts.net
```

After first login:

1. **Practice settings**: name, EIN, state, payment instructions, invoice email text and
   home-office square footage.
2. **Practice → Licenses**: enter your real license numbers and expiration dates.
3. **Practice → Portal forms**: upload your blank intake, consent and release forms.
4. **Bank connection (Plaid)**: link your business account with Plaid.

### Development

```bash
./dev.py start --build
./dev.py manage createsuperuser
./dev.py manage seed_sample_data   # fictional Austin, TX demo data
./dev.py test
```

Reference: `./dev.py --help` or [docs/operations/SCRIPTS.md](docs/operations/SCRIPTS.md).

---

## Things to verify for your own practice

These are compliance questions the software can't answer for you:

- **Records retention**: Texas LPC rules require at least 5 years after termination (or
  after a minor client turns 18). Other states differ. Set the years in Practice
  settings to the strictest state you practice in.
- **Telehealth across state lines**: you are responsible for confirming licensure
  in the client's state at the time of each session. The app only warns.
- **HIPAA**: the self-hosted, encrypted-at-rest design helps, but a risk analysis and
  policies are still yours to write. The GDPR documents inherited from upstream
  (`docs/operations/DPIA-template.md`, `DATA_REGISTER.md`) can serve as a starting
  outline.
- **Plaid**: the integration is covered by tests against a mocked API. Try it in
  `PLAID_ENV=sandbox` before linking a real account.

---

## Architecture

A Django 6 monolith on PostgreSQL. Clinical notes are Fernet-encrypted with a key kept
separate from disk encryption. Views delegate to builder and helper classes in
`app/my_practice/utils/`. [CLAUDE.md](CLAUDE.md) is the pattern reference.

| | |
|---|---|
| [CLIENT_PORTAL.md](docs/operations/CLIENT_PORTAL.md) | Upload portal and Tailscale Funnel setup |
| [FEATURES.md](docs/FEATURES.md) | Full feature list |
| [BACKUP_SETUP.md](docs/guides/BACKUP_SETUP.md) | Backup and restore |
| [CLINICAL_DATA_SECURITY.md](docs/guides/CLINICAL_DATA_SECURITY.md) | How sensitive data is encrypted at rest |
| [docs/operations/SECURITY.md](docs/operations/SECURITY.md) | Security model and deployment notes |
| [CODE_STRUCTURE.md](docs/architecture/CODE_STRUCTURE.md) | Codebase patterns |

---

## License

[GNU Affero General Public License v3.0](LICENSE) (AGPL-3.0)

Copyright (C) 2026 Daniel Holbach (original work); modifications in this fork are
likewise licensed under AGPL-3.0.
