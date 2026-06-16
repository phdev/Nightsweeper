# Releasing `nightsweeper` to npm

Nightsweeper publishes via **OIDC Trusted Publishing** — GitHub Actions authenticates
to npm with a short-lived OIDC id-token, so there is **no long-lived `NPM_TOKEN`** stored
anywhere. The workflow lives at [`.github/workflows/release.yml`](.github/workflows/release.yml).

## ⚠️ Bootstrap: the FIRST publish cannot use OIDC

npm has **no PyPI-style "pending publisher"** — the Trusted Publisher settings page only
exists once a package is already on the registry. Since `nightsweeper` has never been
published, the first version must be published once with a credential. Do this **once**:

1. **Create a short-lived token.** On npmjs.com → **Access Tokens** → **Generate New Token**
   → **Granular Access Token**, scoped to **Read and write** for packages, shortest expiry
   (1–7 days). (Or skip the token and use `npm login` with 2FA in the next step.)
2. **Publish `0.1.0` from your laptop** on a clean checkout of `phdev/Nightsweeper`:
   ```bash
   npm ci
   npm publish          # prepublishOnly runs the 46 tests first; --access public is implied (unscoped name)
   ```
   With a token, write it to `~/.npmrc` first:
   `//registry.npmjs.org/:_authToken=<token>`. With `npm login`, just `npm publish`.
3. **Register the Trusted Publisher** (next section) — now that the package exists.
4. **Revoke the bootstrap token** immediately (npmjs.com → Access Tokens → Delete). That
   is the only time a credential ever touches publishing.

## One-time setup: register the Trusted Publisher

Do this **once**, after the package exists on npm (bootstrap above).

1. **Commit the workflow.** `.github/workflows/release.yml` must be on the default branch
   of `phdev/Nightsweeper`. The Trusted Publisher references it by **bare filename**
   (`release.yml`), so it must live in `.github/workflows/`.
2. **Make the repo public.** Automatic provenance requires **both** a public package and a
   public source repo. If `phdev/Nightsweeper` is private, publishing still works but
   provenance is silently skipped.
3. **Sign in to npmjs.com** as an owner/maintainer of `nightsweeper`.
4. Open `https://www.npmjs.com/package/nightsweeper/access` (or **Packages → nightsweeper →
   Settings**) and find the **Trusted Publisher** section.
5. **Select your publisher → GitHub Actions.**
6. **Fill the fields — ALL CASE-SENSITIVE, type them exactly:**
   - **Organization or user:** `phdev` *(no leading `@`, no scope syntax)*
   - **Repository:** `Nightsweeper` *(capital **N** — `nightsweeper` will NOT match and will break OIDC at publish time)*
   - **Workflow filename:** `release.yml` *(bare filename, no path, include `.yml`)*
   - **Environment name:** *leave blank*
   - **Allowed actions:** **npm publish**
7. **Save.** npm does **not** validate on save — a typo only surfaces as a publish-time
   `404 / ENEEDAUTH`, so double-check the casing now.
8. *(Optional hardening, AFTER the workflow has succeeded once on OIDC)* enable **Require
   two-factor authentication and disallow tokens** to force all future publishes through
   OIDC. Doing this before the first successful OIDC run can lock you out.

## Cutting a release (tokenless, from then on)

1. Bump the version and push the tag:
   ```bash
   npm version patch        # or minor / major
   git push --follow-tags
   ```
2. On GitHub → **Releases → Draft a new release**, pick the `vX.Y.Z` tag, write notes,
   **Publish release**.
3. The `release: published` event fires `release.yml`: checkout → Node 24 → ensure
   npm ≥ 11.5.1 → `npm ci` → `npm test` → `npm publish --provenance` over OIDC (no token),
   with provenance attestation.
4. *(Retry)* Re-run from the **Actions** tab via **Run workflow** (`workflow_dispatch`).

## Why the workflow looks the way it does (hard-won, do not "simplify")

These were each confirmed against current (2025–2026) npm/GitHub docs **and** field reports:

- **Node 24, not 20.** Trusted publishing requires npm ≥ 11.5.1 **and** Node ≥ 22.14.0.
  This is the *runner* version, unrelated to the package's `engines.node>=20` floor.
- **No `registry-url` on setup-node.** That input writes an `.npmrc` with
  `//registry.npmjs.org/:_authToken=${NODE_AUTH_TOKEN}` + `always-auth=true`, which forces
  the legacy token path and breaks OIDC. npm defaults to the public registry anyway.
- **`NODE_AUTH_TOKEN` is never set — and is `unset` before publish.** An *empty* token is
  still a value npm tries to use; it must be entirely absent for the OIDC fallback.
- **`--provenance` is explicit.** Docs say it's automatic, but field reports vary; the flag
  is a harmless no-op when provenance already fires and rescues the cases where it doesn't.
- **Keep `repository.url` as `git+https://github.com/phdev/Nightsweeper.git`.** Do not
  rewrite it to plain https — npm re-normalizes to the `git+https://…#.git` form and a
  mismatch breaks provenance.
