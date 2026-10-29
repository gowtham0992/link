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

Remove-Item -Recurse -Force $dir
Write-Host "instructions.ps1 round trip: ok"
