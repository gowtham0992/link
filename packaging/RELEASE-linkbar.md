# LinkBar release checklist (rides the Link 2.0.0 release)

1. `python3 scripts/prepare_release.py 2.0.0` on develop -> commit -> push
2. PR develop -> main, wait for all 10 CI checks, merge (merge commit)
3. `git switch main && git pull --ff-only && git tag -a v2.0.0 -m v2.0.0 && git push origin v2.0.0`
4. PyPI + mcp-publisher (same as 1.7 runbook)
5. Formula bump in the tap (url/sha for v2.0.0 tarball)
6. **LinkBar zip**: `cd apps/LinkBar && bash Scripts/bundle.sh --release-zip`
   - attach `.build/LinkBar-1.0.0.zip` to the v2.0.0 GitHub release
7. **Cask**: copy `packaging/linkbar.rb` to the tap as `Casks/linkbar.rb`,
   paste the sha256 from step 6, `git push` the tap
8. Verify as user #1: `brew install --cask gowtham0992/link/linkbar`
   -> app opens with no Gatekeeper dialog; menu icon appears
9. Back-merge main -> develop
10. QA before step 1, on the installed app:
    - press ⌥⌘M anywhere -> palette appears, recall works, `+text` remembers
    - end an agent session with a memorable line -> notification banner with
      Accept appears; Accept works from the banner
    - Status tab all green
