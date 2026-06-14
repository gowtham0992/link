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
$target = if ($Project) { "GEMINI.md" } else { Join-Path $HOME ".gemini\GEMINI.md" }
$wikiPath = if ($Project) { Join-Path (Get-Location).Path "wiki" } else { Join-Path $HOME "link\wiki" }

Link-UpsertInstructions $target $instructionsFile "Link instructions"

if ($Project) {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1") -Project
} else {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1")
}

$mcpPython = Link-ReadMcpPython $wikiPath
$settings = Join-Path $HOME ".gemini\settings.json"
if (-not $Project -and (Test-Path $settings)) {
    Link-UpsertMcpJson -Path $settings -Command $mcpPython -WikiPath $wikiPath
} else {
    Write-Host ""
    Write-Host "  MCP: add to ${settings}:"
    Write-Host "  { `"mcpServers`": { `"link`": { `"command`": `"$mcpPython`", `"args`": [`"-m`", `"link_mcp`", `"--wiki`", `"$wikiPath`"] } } }"
}

Link-PrintNextSteps $mode
