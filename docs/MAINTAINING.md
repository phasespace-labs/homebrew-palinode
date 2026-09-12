# Maintaining the Palinode tap

The stable formula follows published stable releases of `phasespace-labs/palinode`,
including patch releases. Drafts, prereleases, development commits, and private
release cuts do not enter this channel. A release is distributed through Homebrew
only after its formula PR has passed validation and been merged.

## Release updates

`Update stable release` runs at minutes 17 and 47 each hour on the default branch.
It selects the highest semantic version among public, published stable releases,
downloads that version's source archive, verifies its package metadata, and
computes the archive SHA-256. It updates only the formula URL and checksum, keeping
the packaging recipe. The formula test derives its expected version from the URL.

The updater creates `automation/palinode-vX.Y.Z` and a reviewable PR. It never
merges, force-pushes, or pushes to `main`. A repeated run reuses the existing PR;
a push that succeeded before PR creation failed is recovered on retry. A closed
PR is left closed and reported for a maintainer to investigate. Old manual tags
and delayed jobs are refused if a newer stable release is available.

The recipe deliberately keeps its Python/pip dependency installation and the
source build of `nh3`. Version updates must not replace this with a generic Python
formula template: that would change the previously validated packaging behavior.

## Enable automation

In this tap's **Settings → Actions → General**, enable Actions and **Allow GitHub
Actions to create and approve pull requests**. If the organization disables this
setting, an organization owner must first permit it under **Organization Settings
→ Actions → General**; a repository-level change will return HTTP 409. Keep
default workflow permissions read-only and grant writes only in the updater.
The updater uses the repository's
`GITHUB_TOKEN` with contents and pull-request write permissions; it does not approve
or merge PRs. It also requests actions write permission to dispatch Formula CI.
There is no cross-repository write token or personal token to configure.

Events made with `GITHUB_TOKEN` do not reliably launch unattended PR validation:
GitHub can require workflow approval. The updater explicitly dispatches Formula CI
on its PR branch, which GitHub supports with the repository token. It checks for an
existing dispatched run at the same commit before dispatching again. Review the
run whose head SHA matches the PR. Formula CI has read-only permissions.

Only dispatch the updater from `main`; the workflow refuses other branches.
GitHub can delay scheduled jobs and disables schedules on inactive public
repositories after 60 days. Every release should also run the manual command below
and verify distribution, rather than treating the schedule as a release receipt.

## Manual release check and retry

After publishing a stable release:

```sh
gh workflow run update-release.yml --repo phasespace-labs/homebrew-palinode \
  --ref main -f release_tag=vX.Y.Z
gh run list --repo phasespace-labs/homebrew-palinode --workflow update-release.yml
gh pr list --repo phasespace-labs/homebrew-palinode \
  --head automation/palinode-vX.Y.Z
```

Replace `vX.Y.Z` with the published tag. The updater's summary links the pending
PR; success means that preparation completed, not that the formula is published.
Formula CI checks current release selection, a clean source installation on macOS
and Linux, all installed entry points, save/search, UI availability, an
MCP initialization/status round trip, and an upgrade from the formula on `main`.
The upgrade test checks that a pre-existing memory file and its Git ancestry
survive. It uses fictional data, a real SQLite/Git store, and a local HTTP embedding
fixture with deterministic finite vectors. This checks package wiring, not semantic
retrieval quality or a real Ollama/model installation. v0.19.1's search endpoint
returns 503 without an embedder even though saves persist; the test does not mask
that limitation by claiming to validate keyword-only operation.

If the update or validation fails, inspect the failed logs and rerun the failed
jobs after correcting the cause. The same version gets the same PR. To run
validation explicitly:

```sh
gh workflow run ci.yml --repo phasespace-labs/homebrew-palinode \
  --ref automation/palinode-vX.Y.Z
```

Merge only the reviewed, passing commit. If a newer stable version appears while
an older PR awaits review, use the newer PR and close the obsolete one; Formula CI's
release check rejects old candidates when rerun. Rebase/update stale PRs and rerun
validation before merging. The updater does not make a merge decision for you.

After merge, verify from a refreshed tap checkout:

```sh
python3 scripts/update_release.py --check --release-tag vX.Y.Z
brew update
brew upgrade phasespace-labs/palinode/palinode
palinode --version
```

If Actions is unavailable, run `--prepare --release-tag vX.Y.Z` in a clean feature
branch, review the formula diff, run tests, and open a PR manually. `--prepare`
does not publish anything. Updater unit tests use only Python's standard library:

```sh
python3 -m unittest discover -s tests -v
```

`bash scripts/test_formula.sh` runs the installation/upgrade checks. Use a
disposable macOS/Linux runner: it installs, removes, and upgrades the formula in
that runner's Homebrew prefix. It never uses a personal memory store. Test reports
and logs go to `artifacts/reports/` and are uploaded by CI.
