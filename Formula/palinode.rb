class Palinode < Formula
  include Language::Python::Virtualenv

  desc "Git-native persistent memory for AI agents"
  homepage "https://github.com/phasespace-labs/palinode"
  url "https://github.com/phasespace-labs/palinode/archive/refs/tags/v0.10.0.tar.gz"
  sha256 "fefad5a3fda02c046385c98b2b21c49d1246125c0e7d17503381313595ecc24b"
  license "MIT"

  depends_on "python@3.12"

  def install
    venv = virtualenv_create(libexec, "python3.12")
    venv.pip_install buildpath
    bin.install_symlink libexec/"bin/palinode"
  end

  test do
    assert_match "0.10.0", shell_output("#{bin}/palinode --version")
  end
end
