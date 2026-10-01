# Project Instructions

Solo self-pay counseling practice management (US fork: Texas LPC, licensed in TX/UT/VA/NM) built with Django, PostgreSQL, running in Docker locally behind Tailscale. Forked from a German upstream; this fork never pulls upstream updates or registry images.

## 🔒 Privacy & Data Protection (CRITICAL)

**Ground Rules - NEVER violate these:**
1. **No Real Names**: Use dummy names in all docs, code, examples, commit messages
   - ✅ Good: "Max Mustermann", "Anna Schmidt", "Maria Musterfrau"
   - ❌ Bad: Any real client or practitioner names
2. **No Contact Info**: Never include real emails, phone numbers, addresses
   - ✅ Good: "mail@example.com", "contact@practice.example", "+49 123 456789"
   - ❌ Bad: Real email addresses or phone numbers
3. **Anonymized Examples**: Use fictional data in documentation and tests
   - Client codes: XX-1, YY-2, AB-3
   - Invoice numbers: INV-001, INV-002
   - Bank names: "M. Schmidt", "Test GmbH"
4. **Review Before Commit**: Check for leaked PII in:
   - Commit messages
   - Documentation files
   - Code comments
   - Test fixtures
   - Migration defaults (use placeholders)

**Client Privacy Mode** (active by default):
- Templates use `client.client_code` instead of full names
- Admin interface respects privacy settings
- Exports use codes unless explicitly needed

**Guardrail test** (M-PAT-08): `my_practice/tests/test_privacy_coverage.py` ratchets both
directions of the `.sensitive-data` contract — a personal field rendered *outside* a blur
(under-blur), and a blur wrapped around something that was never personal (over-blur,
which hides a form label or the client code that is itself the privacy-safe form). Neither
is visible in review or in normal use: `body.privacy-mode` is a client-side localStorage
toggle, so nothing renders differently unless it happens to be switched on. That is why
this bug class was fixed one site at a time three times (#321, #424, #426) before being
automated. Use `<span class="sensitive-data">` for a name shown beside its client code,
`|privacy_name` (initials stay legible) where there is no code to fall back on — inquiries,
and any picker whose rows must be told apart — and nothing at all for codes, invoice
numbers, form inputs or `<option>` text (a CSS blur can't reach text painted by the OS
select widget, so selects show the code only). `KNOWN_UNPROTECTED` holds the deliberate
exceptions, each with a reason; shrink it, never grow it to make a new render pass. Full
contract: [docs/guides/CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) (M-PAT-08).

## US Locale (standing rules)
- **English only.** `LANGUAGE_CODE = "en-us"`, one entry in `LANGUAGES`, no `locale/` catalogs and no language switcher. Never reintroduce German UI text, a `_de`/`_en` field pair, or a per-client language.
- **Keep wrapping user-facing strings** in `{% trans %}`/`gettext`/`gettext_lazy` (lazy for class-body attributes, eager inside functions) so translation can be added later without a sweep. `my_practice/tests/test_i18n_coverage.py` still fails if a non-PDF template skips `{% load i18n %}` or contains German characters.
- **Time zone** `America/Chicago` (`TIME_ZONE`, overridable via `DJANGO_TIME_ZONE`; the container `TZ` should match).
- **Dates** display as `DD MMM YY` (`05 Mar 26`) via `config/formats/en/formats.py` (`DATE_FORMAT = "d M y"`). Templates spell it `|date:"d M y"`; don't introduce other day-first or numeric formats like `d.m.Y` or `m/d/Y`. HTML date inputs stay ISO.
- **Currency** USD via `utils/formatting.format_currency` / the `currency` template filters: `$1,234.56`, negatives `-$5.00`. Never build `€` or German number formats.
- **Taxes**: IRS 1040-ES quarterly periods come from `utils/practice_days.estimated_tax_periods(year)`; self-employment tax estimate and simplified home office (`HomeOfficeCalculator`) live there too. No VAT anywhere.
- **No outbound phoning home**: no update checks, no telemetry. Outbound calls are limited to Google Calendar, SMTP, and Plaid (only when `PLAID_*` is configured).
- **Client portal** (`/portal/<token>/`) is the only path exposed beyond the tailnet (Tailscale Funnel). Its views use `@login_not_required` and must never reveal client names. `FunnelPathGuardMiddleware` 404s Funnel traffic outside `/portal/` and `/static/`. See [docs/operations/CLIENT_PORTAL.md](docs/operations/CLIENT_PORTAL.md).

## Photographic Interface (standing rules)
The UI is a calm, assistant-style shell built on real photography. Every page renders inside `base.html`'s **scene**: a full-bleed photograph hero with the page title in the display serif, a frosted top bar, and the content card overlapping the photo, while a blurred wash of the same photo sits behind the whole page.
- **Titles go in the hero.** Set `{% block page_title %}`/`{% block page_subtitle %}`; never open a page's content with its own `<h1>`. Both blocks pass through `strip_emoji`.
- **No emoji in the UI.** Use words, or `{% icon "pencil" %}` (`templatetags/icons.py`) for a control whose only content is a glyph, and keep its `title`/`aria-label`. Add a path to `icons.PATHS` rather than reaching for an emoji.
- **Only real photographs and footage**: no illustrations, AI images or stock vectors. Everything is self-hosted under `static/scenes/` (no hotlinking; the app makes no outbound calls), produced with `scripts/scene_media.py`, and credited in **both** `my_practice/scenes.py` and `static/scenes/CREDITS.md`. `my_practice/tests/test_scenes.py` fails on a missing file, a missing credit, an orphaned file, or footage whose `Scene.video` flag doesn't match.
- **Which photo a page gets**: `scenes.scene_for()` maps URL-name prefixes (`SECTION_PREFIXES`) to scenes; the dashboard and sign-in follow the time of day (dawn/day/dusk/night in `TIME_ZONE`). A new section that should look different needs a prefix entry, not template code.
- **Footage**: `scripts/scene_media.py video <key> clip.mp4`, then set `video=True` on the scene. The `<video>` only gets its `src` from `base.html`'s script when ambient motion is on, so reduced-motion users never download it. The photo stays as poster and fallback.
- **Colour on photographs** uses the theme-independent `--color-on-photo*` tokens (light text on a darkened image in both themes); content surfaces use `--color-glass*`/`--color-surface`. Never put theme-dependent text tokens directly on a photo.
- **Motion** (the slow drift, card rise-in, and any footage) must stop under `prefers-reduced-motion` unless the user switched motion on with the top-bar toggle (`html[data-motion]`).
- **The dashboard briefing** (`utils/briefing.py`) speaks in the assistant's voice and shows client codes only. The hero isn't covered by privacy mode, so a name must never reach it.

See [PROJECTS.md](PROJECTS.md) for numbered projects with status tracking (TODO/WIP/DONE).

## Development Commands (use `./dev.py` for everything)
```bash
./dev.py start              # Start containers
./dev.py test               # Run Django + JS tests
./dev.py test my_practice.tests.test_calculations  # Specific test
./dev.py test --smart        # Only tests affected by recent changes (pytest + testmon)
./dev.py test --fast         # Full suite, parallel workers + failfast
./dev.py shell              # Django shell (interactive)
./dev.py manage <cmd>       # Django management commands
./dev.py run <script.py>    # Run script with Django environment
./dev.py logs -f            # Follow container logs
./dev.py restart --force    # Full restart (reloads .env)
./dev.py lint               # Run ruff format + ruff lint only (fast, no tests)
./dev.py quality            # Run lint + Tailwind CSS build + full test suite (pre-release)
./dev.py install-hooks      # Install the pre-commit hooks (once per clone)
```

### Git workflow
**`main` is branch-protected — all changes require a PR**, even trivial ones like generated files or docs. Always work on a feature branch and open a PR via `gh pr create`.

Install the hooks once per clone: `pip install pre-commit && ./dev.py install-hooks`. `.pre-commit-config.yaml` is the **only** hook mechanism — never add a second one via `core.hooksPath`, which overrides `.git/hooks/` wholesale and silently disables everything in it (that is how the gitleaks scan sat dead for months). CI runs the same config, so skipping the install only moves the feedback to the PR.

### Guardrails that run in CI but not in `./dev.py test`
- `gitleaks detect` over the full git history (the pre-commit hook only scans the index, so it is skipped in CI — see CODEBASE_STANDARDS.md for why).
- `manage.py check --deploy` against the hardened config. The suite runs with `DJANGO_DEBUG=True`, so the whole `if not DEBUG:` block in `config/settings.py` is otherwise never evaluated.
- `mypy --follow-imports=silent` over the modules `mypy.ini` declares strict. Widen that path list and the `mypy.ini` overrides together.
- `scripts/check_requirements_sync.py` — `requirements.txt` and `requirements-dev.txt` duplicate every runtime pin on purpose (Dependabot does not resolve `-r` includes) and had already drifted once.

Full contract: [docs/guides/CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) § Repository Tooling & Guardrails.

### Release process
Full checklist: [docs/operations/RELEASE.md](docs/operations/RELEASE.md). The image is built locally; nothing is published to or pulled from a registry.

1. Bump all three version strings (they must match): `app/my_practice/version.py`, `prod.py` (`VERSION`), and `docker-compose.prod.yml` (`image: my-practice-usa:vX.Y.Z`), plus the docs pass (`docs/CHANGELOG.md`, `docs/FEATURES.md`, `PROJECTS.md`).
2. Merge, tag `vX.Y.Z`, then on the practice machine run `./prod.py update` (`git pull --ff-only` + rebuild + restart).

### Testing Strategy

Match test scope to change scope — don't run the full suite for every edit:

- **During development**: run only the test file(s) for code you touched
  ```bash
  ./dev.py test my_practice.tests.test_inquiry
  ./dev.py test my_practice.tests.test_invoice my_practice.tests.test_calculations
  ```
- **Before committing**: broaden slightly to cover shared code touched (models, utils)
- **Full suite** (`./dev.py test --fast`, or plain `./dev.py test` if you want full non-parallel `-v 2` output): once per session when work is done, or before a release

If you touch a shared utility or model used across many views, run a wider set. If you touch one view/form, run its test file.

`--smart` (pytest-testmon) is a good middle ground when you're not sure what your change touched — it maps changed files/lines to the tests that cover them, so it's cheaper than a scoped guess and much cheaper than the full suite. First run on a fresh checkout builds the mapping (runs everything once); subsequent runs are fast. Rebuild the mapping (`./dev.py test --smart` again) after a rebase or pulling unrelated changes, since testmon's map can go stale.

## Architecture

### Modular Structure
- **Models** (`app/my_practice/models/`): Domain-focused modules (client, invoice, practice, financial, etc.)
- **Views** (`app/my_practice/views/`): Feature-specific view modules + CRUD mixins
- **Utils** (`app/my_practice/utils/`): Reusable business logic - **USE THESE FIRST!**
- **Templates** (`app/templates/`): Base template + `includes/` for reusable components

### Essential Patterns (Use These!)

#### Builder Classes for Complex Context
When views need complex context preparation, use builder classes:
```python
# Financial lists (expenses, withdrawals)
from my_practice.utils import FinancialListContextBuilder
builder = FinancialListContextBuilder(queryset, year_filter=year)
context, items = builder.build_context(include_categories=True, include_tax_deductible=True)

# Analytics dashboard
from my_practice.utils import AnalyticsDashboardBuilder
builder = AnalyticsDashboardBuilder(start_date, end_date)
context = builder.build_context()

```

#### Filter Helpers for QuerySets
Encapsulate complex filtering logic:
```python
from my_practice.utils import InvoiceFilterHelper
helper = InvoiceFilterHelper(Invoice.objects.all())
filtered = helper.apply_filters(
    search_query=request.GET.get('search'),
    year_filter=year,
    status_filter=status
)
```

#### Session Counting - Always use centralized function
```python
from my_practice.utils import count_sessions
sessions = count_sessions(invoice.items.all())  # Formula: (duration / 60.0) * quantity
```

#### CRUD Views - Use mixins from `views/crud_mixins.py`
```python
# Simple form-based CRUD
class ExpenseCreateView(PracticeScopedCreateView):
    model = CompanyExpense
    form_class = CompanyExpenseForm
    template_name = "my_practice/expense_form.html"
    success_url = reverse_lazy("expense_list")
    success_message = gettext_lazy("Expense from {obj.date:%d.%m.%Y} created successfully.")

# ?next= redirect support (success_url honors ?next=, exposes context["next"])
class ExpenseDeleteView(NextRedirectMixin, PracticeScopedDeleteView):
    model = CompanyExpense
    success_url = reverse_lazy("expense_list")

# Invoice formsets
class InvoiceCreateView(InvoiceFormsetMixin, PracticeScopedCreateView):
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return self.get_formset_context(context, formset_key="items")
```
Available base classes: `PracticeScopedListView`, `PracticeScopedCreateView`, `PracticeScopedUpdateView`, `PracticeScopedDeleteView`, `NextRedirectMixin`, `InvoiceFormsetMixin`.

#### Centralized Queries and Calculations
```python
# Revenue calculations
from my_practice.utils import RevenueCalculator
revenue = RevenueCalculator.get_year_revenue(2026, use_paid_date=True)["total"]
breakdown = RevenueCalculator.get_status_breakdown(year=2026)

# Date ranges
from my_practice.utils import DateRangeHelper
helper = DateRangeHelper(start_date, end_date)
months = helper.get_month_list()
```

#### Numbered patterns (M-PAT-01 … M-PAT-09)

Each exists because the bug it prevents is invisible in code review. The rule is
here; the worked example and the failure it came from are in
[CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) § Patterns Reference.

| | Rule |
| --- | --- |
| **M-PAT-01** Error handling | Form views: `messages.error()` + `form_invalid()`. API views: `JsonResponse` with a status code. Management commands: log, then raise `CommandError`. |
| **M-PAT-02** Date filters | Always go through `RevenueCalculator`; never hand-build `invoice_date__year` / `status` filters. |
| **M-PAT-03** Charts in hidden tabs | A chart drawn in a `display: none` container gets zero height. Redraw from `chartRegistry` 50–100 ms after the tab becomes visible. |
| **M-PAT-04** CSS | No inline `<style>`, no new `.css` files — everything in `tailwind.css`. Full rule in § CSS Architecture below. |
| **M-PAT-05** Working days | `DateRangeHelper.count_working_days` with US federal holidays; never `round(days * 5/7)`. See § Working-Day Calculations below. |
| **M-PAT-06** Form draft guard | Opt long-text forms in with `data-draft-guard` plus the three `data-draft-*` labels; reuse those msgids verbatim rather than minting new ones. |
| **M-PAT-07** CSS tokens | Use real `--color-*` tokens (grep the `@theme` block); never invent a name, never hardcode hex on a semantic class. |
| **M-PAT-08** Privacy mode | `.sensitive-data` for a name beside its code, `\|privacy_name` where there is no code, nothing for codes / inputs / `<option>` text. |
| **M-PAT-09** Narrow windows | Minimum supported viewport is 768px (a half-screen laptop, not a phone). Flex button groups declare `flex-wrap: wrap`; every `<table>` sits directly in `.table-container`; 6+ columns also needs `table-container--wide`. |

## Code Style & Patterns

### Import Organization
Use relative imports for app-internal code:
```python
# Good
from ..models import Client, Invoice
from ..utils import count_sessions, RevenueCalculator
from .crud_mixins import PracticeScopedCreateView

# Avoid
from my_practice.models import Client
```

### Error Handling Patterns
- **Form Views**: Use `messages.error()` + `form_invalid()` pattern
- **API Views**: Return `JsonResponse` with appropriate status codes
- **Management Commands**: Raise exceptions with logging

### Query Optimization
- Always use `.select_related()` for ForeignKey access: `Invoice.objects.select_related('client')`
- Use `.prefetch_related()` for reverse relations: `Client.objects.prefetch_related('invoices')`
- Use `.only()` when building maps: `Client.objects.only('id', 'client_code', 'full_name')`

## Language Policy (P-038)

| Layer | Language | Notes |
|-------|----------|-------|
| Code — variable/function/class names | **EN** | Always |
| Code — comments and docstrings | **EN** | Always; migrate German ones as you touch them |
| Filenames (templates, CSS, JS, scripts) | **EN** | Always; rename German ones as you touch them |
| URL slugs | **EN** | Always; 4 German slugs remain (tracked in P-038) |
| Docs (.md files, guides, architecture) | **EN** | Always; migrate German docs as you touch them |
| UI/app text (labels, buttons, messages, verbose_names) | **EN** | Wrapped in `{% trans %}`/`gettext`, see US Locale above |
| model `verbose_name` / `help_text` | **EN** | Wrapped in `gettext_lazy` |

**Practical rule for day-to-day work:** new code is always English. When editing a file that still has German comments or identifiers, translate them in the same commit.

## Conventions
- **UI Language**: English only (`LANGUAGE_CODE = "en-us"`), see US Locale above
- **Currency Format**: USD, `$1,234.56` (`format_currency`)
- **Date Format**: `DD MMM YY` (`05 Mar 26`)
- **Typography**: Newsreader (display serif: titles, greeting, figures) and Hanken Grotesk (UI), self-hosted in `static/fonts/`
- **Code Style**: Black formatting, isort for imports
- **Tests**: Place in `tests/test_<module>.py`, use Django TestCase
- **Client Privacy**: Always use client codes in templates, respect privacy mode
- **Type Hints**: Use Python 3.13 union syntax: `str | None`, `dict[str, int]`, `list[str]` (not `Optional`, `Dict`, `List`)
- **No dead code**: Never leave commented-out code blocks; delete unused code

## CSS Architecture (M-PAT-04)

**Rule: No inline `<style>` blocks in templates and no new `.css` files — all CSS belongs in `tailwind.css`.**

### Structure
- `app/static/css/tailwind.css` — single source file; compiled to `tailwind.out.css` by `@tailwindcss/cli`
- `app/static/css/tailwind.out.css` — compiled output, loaded by `base.html` (gitignored; rebuilt by `npm run build:css`)
- PDF templates (`invoice_pdf_*.html`) are exempt — they require inline styles for PDF rendering

### Adding new styles
Put new component classes in `tailwind.css` under `@layer components`:
```css
/* in tailwind.css */
@layer components {
  .my-component { background: var(--color-surface); color: var(--color-text-primary); }
}
```

Use `--color-*` tokens for all colours — they automatically adapt to dark mode via `[data-theme="dark"]` overrides. Never use hardcoded hex values.

**Guardrail test**: `my_practice/tests/test_css_tokens.py` is a ratchet over two failure modes that are invisible in review and in light mode:
- `var(--x)` where `--x` is never defined. With no fallback the whole declaration is *dropped* (invalid at computed-value time) and the property reverts to inherited/initial — a background or hover highlight just never renders. With a hardcoded fallback the fallback wins permanently.
- New hardcoded hex on a semantic component class. A literal hex doesn't flip with the theme while a tokenised text colour does, so a light background ends up carrying the dark theme's near-white text — contrast ≈1.0, invisible rather than merely low. `.cn-triage-attention`, `.onboarding-step.step-done` and the login page's `.alert-error` all shipped that way.

`KNOWN_HARDCODED_HEX_PREFIXES` allowlists what is deliberately theme-independent (brand gradients, fixed swatch palettes, coloured buttons with white text) — shrink it, never grow it to make a new colour pass. Use the real token names; grep the `@theme` block at the bottom of `tailwind.css` rather than inventing one (`--card-bg`, `--text-primary`, `--color-text` and `--color-surface-alt` have all been invented and silently did nothing). Full contract: [docs/guides/CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) (M-PAT-07).

Do **not** create a new `.css` file. Do **not** add a block for page-specific CSS `<link>`/`<style>` tags — there deliberately isn't one; all CSS goes in `tailwind.css`.

Never add bare `<style>` blocks:
```html
{# BAD — do not do this #}
<style>
    .my-class { ... }
</style>
```

`base.html` has two blocks for page-specific `<script>` tags, neither for CSS: `extra_head_scripts` (in `<head>`, for scripts an inline script further down the page calls synchronously — e.g. chart libs) and `extra_js` (near the end of `<body>`, for everything else). Pick whichever matches your load-order need; don't repurpose either for CSS.

### Forms
- Use `StyledFormMixin` for all ModelForms — no manual `attrs={"class": "form-control"}` on field widgets
- Use `DateFormField` for all date inputs — handles `date` input type automatically

### Delete Views
- Use `PracticeScopedDeleteView` for all delete views — no wrapper functions or custom `get_object()`

### Models
- Use `TimestampedModel` as base class for all new models needing `created_at`/`updated_at`

## Key Models
- `Client` - Therapy clients with individual hourly rates
- `Invoice` / `InvoiceItem` - Invoices with line items (duration, quantity, rate) - **primary data source**
- `Practice` - Practice settings (logo, signature, bank details, email templates)
- `CompanyWithdrawal` / `CompanyExpense` - Financial tracking

## Database
PostgreSQL with performance indexes — defined inline via each model's `Meta.indexes` (e.g. `Invoice`, `Session`, `PracticeTodo`, `SupervisionItem`, `ClientInquiry`) rather than concentrated in specific migration files. Use `select_related`/`prefetch_related` for related data.

## File Organization
When adding new features:
1. **Check `utils/` first** - Many helpers already exist!
2. Model → `models/<domain>.py` + update `models/__init__.py`
3. View → `views/<feature>_views.py` + update `views/__init__.py`
4. Utility functions → `utils/<purpose>.py` + update `utils/__init__.py`
5. Tests → `tests/test_<module>.py`

## Documentation Guidelines

Where each kind of document belongs, plus the docstring and inline-comment
rules: [CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) § Documentation.
Decisions that would otherwise only survive as a code comment go in
[docs/decisions/](docs/decisions/) as an ADR — its README says when one is warranted.

### Documentation Principles
1. **One source of truth per topic** - PROJECTS.md is the index, P-XXX docs have details
2. **Status-based organization** - Use todo/wip/done directories for lifecycle tracking
3. **Numbered projects** - P-XXX format for easy cross-referencing; a new project takes the **lowest unused number** (there are gaps — see [PROJECTS.md § Project Numbering](PROJECTS.md#-project-numbering)), never the number of the GitHub issue it came from
4. **Docstrings are mandatory** for public functions/classes
5. **Code is the primary documentation** - write self-documenting code
6. **Comments explain WHY, not WHAT** - code shows what, comments explain reasoning
7. **Update docs with code changes** - outdated docs are worse than no docs
8. **Link between docs** - use relative links to connect related documentation
9. **Archive with dates** - Historical docs get YYYY-MM-DD_ prefixes

## Narrow-Window Layout (M-PAT-09)

The UI must work down to a **768px viewport** — a small laptop, or a window dragged to
half the desktop while the news plays beside it. Phones are explicitly out of scope.
Nothing here renders differently until the window is narrow, so every instance ships
unseen; four were live at once when this was automated.

- **Flex button groups declare `flex-wrap: wrap`.** A group with `display: flex` and no
  wrap sizes to max-content and paints its buttons outside the parent. Wrapping is never
  worse than overflowing and changes nothing at full width.
- **Every `<table>` sits directly inside `<div class="table-container">`**, and a table
  of **6+ columns** also needs `table-container--wide`. The wrapper alone is a no-op:
  `.table-container table` is `width: 100%`, so without the modifier's `min-width` the
  table just crushes its columns while the markup looks correct.

**Guardrail test**: `my_practice/tests/test_responsive_layout.py` ratchets all three,
plus any fixed px floor wider than the 736px content box. Its allowlists are empty —
keep them that way. Full contract:
[docs/guides/CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) (M-PAT-09);
rationale: [ADR-0006](docs/decisions/ADR-0006-minimum-supported-window-width.md).

## Working-Day Calculations (M-PAT-05)

**Always use `DateRangeHelper.count_working_days` with US federal holidays. Never the `round(days * 5/7)` approximation**: it diverges around holiday weeks (Thanksgiving, Christmas), producing materially wrong utilization figures.

- `count_working_days(start, end)` is inclusive at both ends, Mon–Fri, no holidays.
- Pass a holiday set to exclude them; build it **once per function call**, not inside a loop.
- For "days elapsed before a milestone" (half-open `[start, end)`), pass `end - timedelta(days=1)` so a same-day event counts as 0.
- `us_federal_holidays(year)` (observed dates: Saturday → Friday, Sunday → Monday) lives in `utils/practice_days.py` and is **not** re-exported from `utils/__init__.py`; import it directly.

Worked example: [CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) § Patterns Reference.

## Available Utility Classes (Use Before Creating New Code!)
- `AnalyticsDashboardBuilder` - Dashboard context preparation
- `FinancialListContextBuilder` - Financial list views
- `InvoiceFilterHelper` - Invoice queryset filtering
- `RevenueCalculator` - All revenue calculations
- `DateRangeHelper` - Date range utilities

See [docs/architecture/CODE_STRUCTURE.md](docs/architecture/CODE_STRUCTURE.md) for complete reference.

## Documentation Gardening

At the end of each coding session, do a quick gardening pass before committing.

### Done-Item Graduation Workflow
1. **User-facing features** → add a one-line entry to `docs/FEATURES.md` under the relevant section
2. **Technical changes** → already captured by CHANGELOG.md commit entries; no extra action needed
3. **Project completion** → create `docs/projects/done/P-XXX_NAME.md` (if it doesn't exist), move the project doc from `wip/` or `todo/` to `done/`, add a brief "Recent Activity" entry to PROJECTS.md, and mark the row in the PROJECTS.md "Abgeschlossen" table

### Keeping PROJECTS.md Clean
- Keep at most **2 "Recent Activity" entries** (the last two sessions only)
- Older entries belong in CHANGELOG.md — delete them from PROJECTS.md after adding a new one
- The Backlog section should contain only open/upcoming work; remove items once done

### Gardening Checklist (end of each session)
- [ ] PROJECTS.md: add new "Recent Activity" entry, drop oldest if >2 exist
- [ ] docs/FEATURES.md: add user-facing highlights
- [ ] docs/projects/done/: create/update P-XXX doc for completed projects

## Periodic Review

`./dev.py review` monthly, `./dev.py review --full` quarterly. It runs the
automated checks (dead code, CVEs, outdated packages, coverage; plus complexity
and long files in `--full`) and prints the manual checklist to work through, so
there is nothing to remember here.

Cadence, what each mode covers and the full scan checklist:
[CODEBASE_STANDARDS.md](docs/guides/CODEBASE_STANDARDS.md) § Periodic Review Cadence.
