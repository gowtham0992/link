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
$target = if ($Project) { ".kiro\steering\link.md" } else { Join-Path $HOME ".kiro\steering\link.md" }
$wikiPath = if ($Project) { Join-Path (Get-Location).Path "wiki" } else { Join-Path $HOME "link\wiki" }

Link-NewParentDirectory $target
Copy-Item -Force -Path $instructionsFile -Destination $target
Write-Host "Link steering -> $target"

if ($Project) {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1") -Project
} else {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1")
}

$mcpPython = Link-ReadMcpPython $wikiPath
if (-not $Project) {
    $mcpConfig = Join-Path $HOME ".kiro\settings\mcp.json"
    if (Test-Path $mcpConfig) {
        Link-UpsertMcpJson -Path $mcpConfig -Command $mcpPython -WikiPath $wikiPath -IncludeDisabled
    } else {
        Write-Host "  MCP config: add to $mcpConfig:"
        Write-Host "  { `"mcpServers`": { `"link`": { `"command`": `"$mcpPython`", `"args`": [`"-m`", `"link_mcp`", `"--wiki`", `"$wikiPath`"], `"disabled`": false } } }"
    }
}

Link-PrintNextSteps $mode
