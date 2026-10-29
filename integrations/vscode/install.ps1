param([switch]$Project)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $PSCommandPath
. (Join-Path $ScriptDir "..\_shared\instructions.ps1")

$mode = if ($Project) { "--project" } else { "--global" }
$instructionsFile = if ($Project) {
    Join-Path $ScriptDir "..\_shared\link-instructions-project.md"
} else {
    Join-Path $ScriptDir "..\_shared\link-instructions.md"
}
$wikiPath = if ($Project) { Join-Path (Get-Location).Path "wiki" } else { Join-Path $HOME "link\wiki" }

New-Item -ItemType Directory -Force -Path ".vscode" | Out-Null
$target = Link-FullPath ".vscode\settings.json"
$settings = [ordered]@{}
$readable = $true
if (Test-Path -LiteralPath $target) {
    try {
        $raw = [System.IO.File]::ReadAllText($target, (New-Object System.Text.UTF8Encoding($false, $true)))
        if (Link-HasJsonComments $raw) {
            $settings = $null
        } elseif ($raw.Trim()) {
            $settings = Link-ToHashtable ($raw | ConvertFrom-Json)
        }
    } catch {
        $settings = $null
    }
    $readable = $settings -is [System.Collections.IDictionary]
}
if ($readable) {
    $key = "github.copilot.chat.codeGeneration.instructions"
    $instructionsText = Get-Content -Raw -Encoding UTF8 $instructionsFile
    # Built, not typed: Windows PowerShell 5.1 reads this script as ANSI.
    $dash = [string][char]0x2014
    $items = @()
    if ($settings.Contains($key) -and ($settings[$key] -is [System.Array])) {
        $items = @($settings[$key] | Where-Object {
            $text = if ($_ -is [System.Collections.IDictionary]) { $_["text"] } else { $_.text }
            -not (
                $text -like "*## Link $dash Local Agent Memory*" -or
                $text -like "*## Link $dash Personal Knowledge Wiki*" -or
                $text -like "*Link, an LLM-maintained knowledge wiki*"
            )
        })
    }
    $items += @{ text = $instructionsText }
    $settings[$key] = $items
    Link-WriteTextFile -Path $target -Text (($settings | ConvertTo-Json -Depth 20) + "`n")
    Write-Host "Link instructions -> $target"
} else {
    # Usually comments: VS Code settings are JSON with comments. Rewriting
    # them as plain JSON would lose the person's settings.
    Write-Host "  · Could not parse $target; leaving it unchanged. Add Link's instructions by hand."
}

if ($Project) {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1") -Project
} else {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1")
}

$mcpPython = Link-ReadMcpPython $wikiPath
Link-UpsertMcpJson -Path ".vscode\mcp.json" -Command $mcpPython -WikiPath $wikiPath -TopKey "servers" -IncludeType

Link-PrintNextSteps $mode
