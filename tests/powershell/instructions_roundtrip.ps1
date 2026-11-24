# Link-UpsertInstructions keeps the person's file intact: run on CI's Windows runner.
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "..\..\integrations\_shared\instructions.ps1")

$dir = Join-Path ([System.IO.Path]::GetTempPath()) ("link-ps-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $dir | Out-Null
$utf8 = New-Object System.Text.UTF8Encoding($false)
$source = Join-Path $dir "source.md"
[System.IO.File]::WriteAllText($source, "## Link — Local Agent Memory`n`nnew body`n", $utf8)

function Assert($condition, $message) {
    if (-not $condition) { throw "FAILED: $message" }
}

# 1. A CRLF file of the person's own: kept byte for byte, Link's section appended in CRLF, no BOM.
$target = Join-Path $dir "AGENTS.md"
$mine = "# Mine`r`n`r`nkeep`r`n"
[System.IO.File]::WriteAllText($target, $mine, $utf8)
Link-UpsertInstructions $target $source "test"
$bytes = [System.IO.File]::ReadAllBytes($target)
Assert ($bytes[0] -ne 0xEF) "no byte-order mark"
$text = [System.IO.File]::ReadAllText($target)
Assert ($text.StartsWith($mine)) "the person's text is kept exactly"
Assert ($text.Contains("## Link — Local Agent Memory`r`n`r`nnew body`r`n")) "Link's section uses the file's CRLF"
Assert (-not ($text -match "[^`r]`n")) "no bare LF introduced"

# 2. Upserting again changes nothing.
Link-UpsertInstructions $target $source "test"
Assert ([System.IO.File]::ReadAllText($target) -eq $text) "idempotent"

# 3. A heading of any level after Link's section belongs to the person.
$after = Join-Path $dir "after.md"
[System.IO.File]::WriteAllText($after, "## Link — Local Agent Memory`nold`n### Mine after`nstay`n", $utf8)
Link-UpsertInstructions $after $source "test"
$text = [System.IO.File]::ReadAllText($after)
Assert ($text -eq "## Link — Local Agent Memory`n`nnew body`n### Mine after`nstay`n") "section replaced, ### heading kept: [$text]"

# 4. A section at the end of an LF file keeps the final line break on every run.
$lf = Join-Path $dir "lf.md"
[System.IO.File]::WriteAllText($lf, "# Mine`n`n## Link — Local Agent Memory`nold`n", $utf8)
Link-UpsertInstructions $lf $source "test"
$once = [System.IO.File]::ReadAllText($lf)
Link-UpsertInstructions $lf $source "test"
Assert ([System.IO.File]::ReadAllText($lf) -eq $once) "idempotent at the end of the file"
Assert ($once -eq "# Mine`n`n## Link — Local Agent Memory`n`nnew body`n") "final line break kept: [$once]"

# 5. A new file gets just Link's section.
$fresh = Join-Path $dir "fresh\AGENTS.md"
Link-UpsertInstructions $fresh $source "test"
Assert ([System.IO.File]::ReadAllText($fresh) -eq "## Link — Local Agent Memory`n`nnew body`n") "new file"

# 6. A line the person wrote after Link's section (which ends with its "Otherwise, " line) is theirs.
$source2 = Join-Path $dir "source2.md"
[System.IO.File]::WriteAllText($source2, "## Link — Local Agent Memory`n`nnew body`nOtherwise, new last line.`n", $utf8)
$tail = Join-Path $dir "tail.md"
[System.IO.File]::WriteAllText($tail, "# Mine`n`n## Link — Local Agent Memory`n`nold body`nOtherwise, old last line.`n`n- Always use pnpm`n", $utf8)
Link-UpsertInstructions $tail $source2 "test"
$text = [System.IO.File]::ReadAllText($tail)
Assert ($text -eq "# Mine`n`n## Link — Local Agent Memory`n`nnew body`nOtherwise, new last line.`n`n- Always use pnpm`n") "line after the section kept: [$text]"
Link-UpsertInstructions $tail $source2 "test"
Assert ([System.IO.File]::ReadAllText($tail) -eq $text) "idempotent with a line after the section"

# 7. lnk compile's block after the section survives a second install.
$compiled = Join-Path $dir "compiled.md"
$blockText = "<!-- BEGIN LINK MEMORY: generated -->`n- Use tabs.`n<!-- END LINK MEMORY -->`n"
[System.IO.File]::WriteAllText($compiled, "# Project`n`n## Link — Local Agent Memory`n`nold body`n`n" + $blockText, $utf8)
Link-UpsertInstructions $compiled $source "test"
$text = [System.IO.File]::ReadAllText($compiled)
Assert ($text -eq "# Project`n`n## Link — Local Agent Memory`n`nnew body`n`n" + $blockText) "compile block kept: [$text]"

# 8. A relative path is relative to PowerShell's location, not the process directory.
$project = Join-Path $dir "project"
New-Item -ItemType Directory -Path $project | Out-Null
Push-Location $project
try {
    Link-UpsertInstructions "CLAUDE.md" $source "test"
    Link-UpsertInstructions "nested\CLAUDE.md" $source "test"
} finally {
    Pop-Location
}
Assert (Test-Path -LiteralPath (Join-Path $project "CLAUDE.md")) "relative target written in the current location"
Assert (Test-Path -LiteralPath (Join-Path $project "nested\CLAUDE.md")) "relative nested target written in the current location"
Assert ([System.IO.File]::ReadAllText((Join-Path $project "CLAUDE.md")) -eq "## Link — Local Agent Memory`n`nnew body`n") "relative target content"

# 9. A read-only file is refused and left as it was.
$locked = Join-Path $dir "locked.md"
[System.IO.File]::WriteAllText($locked, "# Mine`n", $utf8)
(Get-Item -LiteralPath $locked).IsReadOnly = $true
$refused = $false
try { Link-UpsertInstructions $locked $source "test" } catch { $refused = $true }
(Get-Item -LiteralPath $locked).IsReadOnly = $false
Assert $refused "read-only file refused"
Assert ([System.IO.File]::ReadAllText($locked) -eq "# Mine`n") "read-only file unchanged"

# 10. A symlinked file stays a link and its target is written (when this runner may create links).
$real = Join-Path $dir "dotfiles.md"
[System.IO.File]::WriteAllText($real, "# Mine`n", $utf8)
$link = Join-Path $dir "linked.md"
$linked = $false
try { New-Item -ItemType SymbolicLink -Path $link -Target $real -ErrorAction Stop | Out-Null; $linked = $true } catch { }
if ($linked) {
    Link-UpsertInstructions $link $source "test"
    $item = Get-Item -LiteralPath $link -Force
    Assert (([int]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) -ne 0) "still a symlink"
    Assert ([System.IO.File]::ReadAllText($real).Contains("new body")) "the link's target was written"
}

# 11. Other servers' arrays stay arrays (a one-element array was written as a string, an empty one as null),
#     key order and nulls are kept, and the file has no BOM.
$mcp = Join-Path $dir "mcp.json"
[System.IO.File]::WriteAllText($mcp, '{"zeta": 1, "mcpServers": {"other": {"command": "node", "args": ["server.js"], "env": null, "empty": []}}}', $utf8)
Link-UpsertMcpJson -Path $mcp -Command "py" -WikiPath "C:\wiki"
$bytes = [System.IO.File]::ReadAllBytes($mcp)
Assert ($bytes[0] -ne 0xEF) "mcp.json without a BOM"
$text = [System.IO.File]::ReadAllText($mcp)
Assert ($text -match '"args":\s*\[\s*"server\.js"\s*\]') "one-element array kept: [$text]"
Assert ($text -match '"empty":\s*\[\s*\]') "empty array kept: [$text]"
Assert ($text -match '"env":\s*null') "null kept: [$text]"
Assert ($text.IndexOf('"zeta"') -lt $text.IndexOf('"mcpServers"')) "key order kept: [$text]"
$parsed = $text | ConvertFrom-Json
Assert ($parsed.mcpServers.link.command -eq "py") "Link's server written"
Assert (@($parsed.mcpServers.link.args).Count -eq 6) "Link's args written"

# 12. A file that is not JSON (a comment) is left alone.
$jsonc = Join-Path $dir "jsonc.json"
[System.IO.File]::WriteAllText($jsonc, "// mine`n{`"a`": 1}`n", $utf8)
Link-UpsertMcpJson -Path $jsonc -Command "py" -WikiPath "C:\wiki"
Assert ([System.IO.File]::ReadAllText($jsonc) -eq "// mine`n{`"a`": 1}`n") "unparseable file unchanged"

# 13. A BOM before Link's heading: the section is found and replaced (not added twice), and the BOM stays.
$bomFile = Join-Path $dir "bom.md"
[System.IO.File]::WriteAllText($bomFile, "## Link — Local Agent Memory`nold`n", (New-Object System.Text.UTF8Encoding($true)))
Link-UpsertInstructions $bomFile $source "test"
$bytes = [System.IO.File]::ReadAllBytes($bomFile)
Assert ($bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) "BOM kept"
$text = [System.IO.File]::ReadAllText($bomFile)
Assert ($text -eq "## Link — Local Agent Memory`n`nnew body`n") "one section, replaced: [$text]"

Remove-Item -Recurse -Force $dir
Write-Host "instructions.ps1 round trip: ok"
