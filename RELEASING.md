# Releases (HACS)

HACS 2 compares `custom_components/.../manifest.json` **version** to the Git ref. On **main**, the ref is a **commit SHA**, so it will never equal `1.2.0` and HACS shows *“The version … can not be used with HACS”*.

**Fix:** publish a **semver GitHub Release** whose tag matches the manifest (use a `v` prefix on the tag only).

Example (manifest says `1.2.0`):

```bash
git tag -a v1.2.0 -m "Release 1.2.0"
git push origin v1.2.0
```

Then on GitHub: **Releases → Draft a new release → choose tag v1.2.0 → Publish**.

After that, in HACS users should install **version 1.2.0** (from releases), not the default branch.

When you bump the integration, update `manifest.json` `version` and repeat with `v1.2.1`, etc.
