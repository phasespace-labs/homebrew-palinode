class Palinode < Formula
  include Language::Python::Virtualenv

  desc "Git-native persistent memory for AI agents"
  homepage "https://github.com/phasespace-labs/palinode"
  url "https://github.com/phasespace-labs/palinode/archive/refs/tags/v0.19.1.tar.gz"
  sha256 "2320746fa3c85fb6247f4eebdf77ec2431f3a62bcd86c8926e69365d8cc2494a"
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
