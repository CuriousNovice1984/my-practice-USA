# Release Checklist

This fork builds its image locally and never pulls from a registry or from upstream.
A "release" is a version bump on `main` that `./prod.py update` picks up with
`git pull --ff-only` before it rebuilds.

## 1. Version-bump PR

**Version strings: update all three, they must match** (`test_release_guardrails.py`
enforces it):

| File | What to change |
|------|---------------|
| `app/my_practice/version.py` | `VERSION = "vX.Y.Z"` |
| `prod.py` | `VERSION = "vX.Y.Z"` |
| `docker-compose.prod.yml` | `image: my-practice-usa:vX.Y.Z` |

**Docs pass** (same PR):

- [ ] `docs/CHANGELOG.md`: add a release section with highlights
- [ ] `docs/FEATURES.md`: add user-facing additions under the right section
- [ ] `PROJECTS.md`: update Recent Activity, cap at 2 entries

## 2. Merge, then tag

```bash
git checkout main && git pull --ff-only
git tag vX.Y.Z && git push origin vX.Y.Z
```

The tag is a bookmark only. No workflow builds or publishes images.

## 3. Deploy

On the practice machine:

```bash
# take a backup first (docs/guides/BACKUP_SETUP.md)
./prod.py update     # git pull --ff-only, docker compose build, up -d (migrations run on start)
```

- [ ] The footer shows the new version
- [ ] Log in, open a client, the invoice list and the tax overview
- [ ] If the portal is published, open a test client's upload link from outside the tailnet
