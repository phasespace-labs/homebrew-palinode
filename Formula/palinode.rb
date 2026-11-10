class Palinode < Formula
  include Language::Python::Virtualenv

  desc "Git-native persistent memory for AI agents"
  homepage "https://github.com/phasespace-labs/palinode"
  url "https://github.com/phasespace-labs/palinode/archive/refs/tags/v0.24.0.tar.gz"
  sha256 "5dcf26457c16e9947920d1ee89de275a0baff20fb9a0cf6cf8fdec2b90e83403"
  license "MIT"

  depends_on "rust" => :build
  depends_on "python@3.12"

  def install
    virtualenv_create(libexec, "python3.12")
    system "python3.12", "-m", "pip", "--python=#{libexec}/bin/python", "install", "--no-binary=nh3", buildpath
    %w[palinode palinode-api palinode-watcher palinode-mcp palinode-mcp-http palinode-mcp-sse].each do |command|
      bin.install_symlink libexec/"bin"/command
    end
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/palinode --version")
    %w[palinode-api palinode-watcher palinode-mcp palinode-mcp-http palinode-mcp-sse].each do |command|
      assert_predicate bin/command, :executable?
    end
    system libexec/"bin/python", "-c", "import palinode.api.server, palinode.indexer.watcher, palinode.mcp"
  end
end
