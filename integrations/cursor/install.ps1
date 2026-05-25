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
$target = if ($Project) { ".cursor\rules\link.mdc" } else { Join-Path $HOME ".cursor\rules\link.mdc" }
$wikiPath = if ($Project) { Join-Path (Get-Location).Path "wiki" } else { Join-Path $HOME "link\wiki" }

Link-NewParentDirectory $target
$instructions = Get-Content -Raw -Encoding UTF8 $instructionsFile
$rule = "---`ndescription: Link knowledge wiki context`nalwaysApply: true`n---`n`n$instructions"
Set-Content -Encoding UTF8 -Path $target -Value $rule
Write-Host "Link rule -> $target"

if ($Project) {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1") -Project
} else {
    & (Join-Path $ScriptDir "..\_shared\scaffold.ps1")
}

$mcpPython = Link-ReadMcpPython $wikiPath
if (-not $Project) {
    $mcpConfig = Join-Path $HOME ".cursor\mcp.json"
    if (Test-Path $mcpConfig) {
        Link-UpsertMcpJson -Path $mcpConfig -Command $mcpPython -WikiPath $wikiPath
    } else {
        Write-Host "  Add to $mcpConfig:"
        Write-Host "  { `"mcpServers`": { `"link`": { `"command`": `"$mcpPython`", `"args`": [`"-m`", `"link_mcp`", `"--wiki`", `"$wikiPath`"] } } }"
    }
}

Link-PrintNextSteps $mode
