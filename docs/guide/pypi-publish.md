# Publishing to PyPI

## Prerequisites

1. PyPI account at [pypi.org](https://pypi.org/)
2. Owner access to the `quickcall-opentrace` package on PyPI
3. A PyPI API token with **Upload** scope

## 1. Set up the GitHub secret

Go to **GitHub → Repository Settings → Secrets and variables → Actions** and add:

| Secret name | Value |
|-------------|-------|
| `PYPI_API_TOKEN` | Your PyPI API token (starts with `pypi-`) |

Never commit this token to the repo.

## 2. Cut a release

### Option A: GitHub Web UI (recommended)

1. Go to **GitHub → Releases → Draft a new release**
2. Choose or create a tag (e.g., `v0.4.64`)
3. Write release notes
4. Click **Publish release**

The `.github/workflows/publish.yml` workflow will automatically:
- Build wheel + sdist with `uv build`
- Upload to PyPI with `uv publish`

### Option B: Command line

```bash
# 1. Update version in pyproject.toml and opentrace/__init__.py
git add -A
git commit -m "release: v0.4.64"

# 2. Tag and push
git tag v0.4.64
git push origin main --follow-tags
```

The tag push triggers the publish workflow.

## 3. Verify the upload

```bash
pip install quickcall-opentrace
quickcall-server --version
quickcall-daemon --version
```

## Manual publish (emergency only)

If CI is down:

```bash
# Build
uv build

# Publish (you'll be prompted for token)
uv publish --token $PYPI_API_TOKEN
```

## Version checklist before tagging

- [ ] `pyproject.toml` version matches `opentrace/__init__.py`
- [ ] `CHANGELOG.md` is updated
- [ ] All tests pass: `uv run pytest`
- [ ] Ruff is clean: `uv run ruff check .`
- [ ] README is current
