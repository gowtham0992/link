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
$target = if ($Project) { "CLAUDE.md" } else { Join-Path $HOME ".claude\CLAUDE.md" }
$wikiPath = if ($Project) { Join-Path (Get-Location).Path "wiki" } else { Join-Path $HOME "link\wiki" }

Link-UpsertInstructions $target $instructionsFile "Link steering"

if ($Project) {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1") -Project
} else {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1")
}

$mcpPython = Link-ReadMcpPython $wikiPath
$mcpConfig = Join-Path $HOME ".claude.json"
if (Test-Path $mcpConfig) {
    Link-UpsertMcpJson -Path $mcpConfig -Command $mcpPython -WikiPath $wikiPath
} else {
    Write-Host ""
    Write-Host "  MCP config: add to $mcpConfig or .mcp.json at project root:"
    Write-Host "  { `"mcpServers`": { `"link`": { `"command`": `"$mcpPython`", `"args`": [`"-m`", `"link_mcp`", `"--wiki`", `"$wikiPath`", `"--surface`", `"slim`"] } } }"
}

Link-PrintNextSteps $mode
