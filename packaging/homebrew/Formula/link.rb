# Template for the live tap (gowtham0992/homebrew-link). At release time,
# copy this over Formula/link.rb in the tap with the new tarball URL and
# sha256 — the caveats below are the post-install story users actually see,
# so they must match the current product (lnk setup, not per-agent onboard).
class Link < Formula
  desc "Local Markdown memory for AI agents"
  homepage "https://github.com/gowtham0992/link"
  url "https://github.com/gowtham0992/link/archive/refs/tags/vX.Y.Z.tar.gz"
  sha256 "REPLACE_WITH_RELEASE_TARBALL_SHA256"
  license "MIT"
  head "https://github.com/gowtham0992/link.git", branch: "main"

  depends_on "python@3.14"

  def python3
    formula_opt_bin("python@3.14")/"python3.14"
  end

  def install
    libexec.install "link.py", "serve.py", "LINK.md", ".linkignore"
    libexec.install "logo.svg"
    libexec.install "logo.png" if File.exist?("logo.png")

    (libexec/"mcp_package").mkpath
    (libexec/"mcp_package").install "mcp_package/link_core"

    # Prefer Link's managed venv when it hosts the link-mcp package: the
    # Homebrew python is externally managed (PEP 668), so the optional
    # semantic/rerank tiers can only live in that venv. Same code runs
    # either way — link.py always uses its own bundled link_core first.
    (bin/"lnk").write <<~SH
      #!/bin/sh
      LINK_VENV_PY="$HOME/.link-mcp-venv/bin/python"
      if [ -x "$LINK_VENV_PY" ] && "$LINK_VENV_PY" -c "import link_core" >/dev/null 2>&1; then
        exec "$LINK_VENV_PY" "#{libexec}/link.py" "$@"
      fi
      exec "#{python3}" "#{libexec}/link.py" "$@"
    SH
  end

  def caveats
    <<~EOS
      Try Link:
        lnk proof                 # prove cross-agent memory in ~1 second
        lnk try                   # the full demo wiki, then: lnk serve link-demo

      Make it yours — one command wires every agent you have
      (workspace, MCP, session hooks; re-run after any upgrade):
        lnk setup

      Optional, macOS: put the review gate in your menu bar — notifications
      when memory is captured, a global palette (Opt-Cmd-M), and a live view
      of every Link surface:
        brew install --cask gowtham0992/link/linkbar

      Optional: meaning-based recall (one-time local model download):
        lnk semantic ~/link --setup
    EOS
  end

  test do
    system bin/"lnk", "--version"
    system bin/"lnk", "demo", testpath/"link-demo", "--force"
    system bin/"lnk", "validate", testpath/"link-demo"
    system bin/"lnk", "status", "--validate", testpath/"link-demo"
  end
end
