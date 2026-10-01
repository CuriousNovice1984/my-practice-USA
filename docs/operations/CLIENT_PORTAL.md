# Client forms portal

Clients get a private, expiring link where they download your blank forms
(intake packet, informed consent, release of information) and upload them
completed and signed. Uploads land on the client's **Documents** card marked
"New from client", tick the matching onboarding step, and show up as one
"client uploads to review" task in the Focus Queue.

## Day-to-day use

1. **Practice → Portal forms** (`/practice/portal-forms/`): upload each blank
   form once as PDF or DOCX and pick its document type. Completed uploads are
   filed under that type: *Intake paperwork*, *Informed consent* and *Health
   history questionnaire* complete the matching onboarding steps.
2. On a client's page, **Forms portal → New upload link** (default 14 days,
   `PORTAL_LINK_DAYS`). Copy the link or use **Email**, which pre-fills a
   message with it.
3. Review new files under **Client uploads** (`/practice/portal-uploads/`) or
   straight from the client page, then mark them reviewed.

**Revoke** kills a link immediately. Each link takes at most 25 files in
total and 10 per upload, at 20 MB per file. Only PDF, images and DOCX are
accepted, and images and PDFs are re-encoded on the way in.

## What the client sees

A standalone page with your practice name, the forms to download and an upload
box. It shows no navigation, no client name and no email address. The page is
marked `noindex`, sends no `Referer`, and is never cached. An expired or
revoked link shows a "no longer available" page.

## Making the portal reachable (Tailscale Funnel)

The app itself stays on your tailnet. Clients aren't on it, so only the portal
paths are published to the internet with
[Tailscale Funnel](https://tailscale.com/kb/1223/funnel), on a **separate HTTPS
port** so your tailnet-only `tailscale serve` setup for the main app is
untouched.

```bash
# Funnel is switched on per port; 8443 is one of the ports Funnel allows.
tailscale funnel --bg --https=8443 --set-path /portal http://127.0.0.1:8000/portal
tailscale funnel --bg --https=8443 --set-path /static http://127.0.0.1:8000/static
tailscale funnel status   # check: only /portal and /static on :8443
```

Then in `.env`, using your machine's tailnet name:

```bash
PORTAL_BASE_URL=https://practice-box.your-tailnet.ts.net:8443
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,practice-box.your-tailnet.ts.net
```

Restart with `./prod.py restart`. `PORTAL_BASE_URL` makes the copied and
emailed links use the public address, and it is added to
`CSRF_TRUSTED_ORIGINS` automatically, because Funnel terminates TLS and the
app only sees plain HTTP.

**Defense in depth:** Funnel tags the requests it proxies from the internet
with a `Tailscale-Funnel-Request` header, and `FunnelPathGuardMiddleware`
returns 404 for any such request outside `/portal/` and `/static/`. If a
mount is ever set up wrongly (for example `/` on the Funnel port), the login
page and the rest of the app still aren't exposed. The mounts above remain
the primary control. Re-check them after a Tailscale upgrade.

**Never** mount `/` or `/admin` on a Funnel port. Your `tailscale serve`
config for the main app should stay tailnet-only (no `funnel`).
