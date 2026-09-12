# Palinode Homebrew tap

Install [Palinode](https://github.com/phasespace-labs/palinode) with:

```sh
brew install phasespace-labs/palinode/palinode
palinode --version
```

Using the fully qualified formula name lets current Homebrew releases trust
only this formula while adding the tap automatically.

The formula installs the CLI, API, watcher, and MCP executables. Python 3.12 and
the package dependencies are managed by Homebrew. Git needs a configured user
name and email so memory writes can be committed.

For local search, [install and start Ollama](https://formulae.brew.sh/formula/ollama)
and download the embedding model (about 1.2 GB):

```sh
brew install ollama
brew services start ollama
ollama pull bge-m3
```

Skip this step if Ollama is already running with `bge-m3`, or configure another
supported embedding endpoint. Start a private local memory store:

```sh
mkdir -p ~/.palinode
git -C ~/.palinode init
PALINODE_DIR=~/.palinode palinode start
```

Keep that terminal open. In another terminal, run
`PALINODE_DIR=~/.palinode palinode doctor` and open <http://127.0.0.1:6340/ui/>.
In v0.19.1 saves persist without the embedder, but the search API
returns HTTP 503 until it is reachable. A chat model is optional for consolidation.
Your memories are separate from the
Homebrew installation and are not removed when you upgrade the package.

For Claude Code, connect the installed MCP executable:

```sh
claude mcp add --transport stdio --env PALINODE_DIR="$HOME/.palinode" \
  palinode -- "$(brew --prefix palinode)/bin/palinode-mcp"
```

Other editors can use the same absolute executable path with their stdio MCP
configuration, with `PALINODE_DIR` set to your absolute memory-directory path in
the server's environment. See the [editor recipes](https://github.com/phasespace-labs/palinode/blob/main/docs/MCP-INSTALL-RECIPES.md).
Project memory instructions and Claude Code hooks are installed by `palinode init`
from your project directory after the backend is running.

Upgrade an existing installation with:

```sh
brew update
brew upgrade phasespace-labs/palinode/palinode
palinode --version
```

Stop foreground services with Ctrl-C before upgrading, then run
`PALINODE_DIR=~/.palinode palinode start` again. For a service manager, use that manager's stop/start commands. This formula
does not register a `brew services` service. Run `palinode doctor` after restart
and follow the release's migration notes; upgrading the package does not rewrite
your existing store prompts or configuration.

This tap follows public stable releases through reviewed update PRs. The scheduled
check normally runs twice an hour; GitHub may delay or disable scheduled runs.
An available source release can therefore precede its Homebrew update. Check the
[update PRs](https://github.com/phasespace-labs/homebrew-palinode/pulls) and
[updater runs](https://github.com/phasespace-labs/homebrew-palinode/actions/workflows/update-release.yml)
if the versions differ.

Maintainer instructions, validation, and retry procedures are in
[docs/MAINTAINING.md](docs/MAINTAINING.md).
