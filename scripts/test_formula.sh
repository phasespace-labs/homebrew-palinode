#!/usr/bin/env bash
set -euo pipefail

# This modifies the test runner's Homebrew installation; use a disposable runner.
repo_dir="$(pwd)"
report_dir="$repo_dir/artifacts/reports"
formula=phasespace-labs/palinode/palinode
mkdir -p "$report_dir"
exec > >(tee "$report_dir/formula.log") 2>&1

brew --version
brew config
cp Formula/palinode.rb "$report_dir/candidate.rb"
git show origin/main:Formula/palinode.rb > "$report_dir/baseline.rb"

brew tap phasespace-labs/palinode "$repo_dir"
if brew help trust >/dev/null 2>&1; then
  brew trust --formula "$formula"
fi
tap_dir="$(brew --repository phasespace-labs/palinode)"
cp "$report_dir/candidate.rb" "$tap_dir/Formula/palinode.rb"
brew style "$formula"
brew install --build-from-source "$formula"
brew test "$formula"
prefix="$(brew --prefix palinode)"
"$prefix/libexec/bin/python" scripts/smoke_runtime.py --seed --store "$report_dir/clean-memory"
"$prefix/libexec/bin/python" scripts/smoke_runtime.py --bin "$prefix/bin" --store "$report_dir/clean-memory"

# Install the previous formula, then replace it with the candidate without touching its store.
brew uninstall "$formula"
cp "$report_dir/baseline.rb" "$tap_dir/Formula/palinode.rb"
brew install --build-from-source "$formula"
prefix="$(brew --prefix palinode)"
"$prefix/libexec/bin/python" scripts/smoke_runtime.py --seed --store "$report_dir/upgrade-memory"
before_version="$(palinode --version)"
cp "$report_dir/candidate.rb" "$tap_dir/Formula/palinode.rb"
base_tag="$(sed -nE 's|.*tags/(v[0-9.]+)\.tar\.gz.*|\1|p' "$report_dir/baseline.rb")"
candidate_tag="$(sed -nE 's|.*tags/(v[0-9.]+)\.tar\.gz.*|\1|p' "$report_dir/candidate.rb")"
if [[ "$base_tag" == "$candidate_tag" ]]; then
  brew reinstall --build-from-source "$formula"
else
  brew upgrade --build-from-source "$formula"
fi
prefix="$(brew --prefix palinode)"
palinode --version
brew test "$formula"
"$prefix/libexec/bin/python" scripts/smoke_runtime.py --bin "$prefix/bin" --store "$report_dir/upgrade-memory"
printf 'Upgrade baseline: %s\n' "$before_version"
