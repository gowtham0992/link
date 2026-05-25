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
$target = ".vscode\settings.json"
$settings = @{}
if (Test-Path $target) {
    try {
        $raw = Get-Content -Raw -Encoding UTF8 $target
        if ($raw.Trim()) {
            $settings = Link-ToHashtable ($raw | ConvertFrom-Json)
        }
    } catch {
        $settings = @{}
    }
}
$key = "github.copilot.chat.codeGeneration.instructions"
$instructionsText = Get-Content -Raw -Encoding UTF8 $instructionsFile
$items = @()
if ($settings.ContainsKey($key) -and ($settings[$key] -is [System.Array])) {
    $items = @($settings[$key] | Where-Object {
        $text = if ($_ -is [System.Collections.IDictionary]) { $_["text"] } else { $_.text }
        -not (
            $text -like "*## Link — Local Agent Memory*" -or
            $text -like "*## Link — Personal Knowledge Wiki*" -or
            $text -like "*Link, an LLM-maintained knowledge wiki*"
        )
    })
}
$items += @{ text = $instructionsText }
$settings[$key] = $items
Set-Content -Encoding UTF8 -Path $target -Value (($settings | ConvertTo-Json -Depth 20) + "`n")
Write-Host "Link instructions -> $target"

if ($Project) {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1") -Project
} else {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1")
}

$mcpPython = Link-ReadMcpPython $wikiPath
Link-UpsertMcpJson -Path ".vscode\mcp.json" -Command $mcpPython -WikiPath $wikiPath -TopKey "servers" -IncludeType

Link-PrintNextSteps $mode
