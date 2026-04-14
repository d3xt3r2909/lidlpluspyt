# Releases (HACS)

HACS 2 compares `manifest.json` **version** to the Git ref. On **main**, the ref is a **commit SHA**, so HACS rejects it. Users must install a **tagged release**.

## Automatic releases (no GitHub UI)

Pushing a tag `v*` triggers `.github/workflows/release.yml`, which creates the GitHub Release for you.

1. Bump `custom_components/lidl_plus/manifest.json` → `version` (e.g. `1.2.1`).
2. Commit and push `main`.
3. Tag and push (same number as manifest, with `v` prefix):

```bash
git tag -a v1.2.1 -m "Release 1.2.1"
git push origin main
git push origin v1.2.1
```

Wait for the **Publish GitHub Release** workflow to finish; then HACS can install **1.2.1**.
