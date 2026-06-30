param()

$ErrorActionPreference = "Stop"

function Link-NewParentDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Link-UpsertInstructions {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$SourceFile,
        [Parameter(Mandatory = $true)][string]$Label
    )

    Link-NewParentDirectory $Target
    $source = (Get-Content -Raw -Encoding UTF8 $SourceFile).TrimEnd()
    $existing = ""
    if (Test-Path $Target) {
        $existing = Get-Content -Raw -Encoding UTF8 $Target
    }

    $headers = @("## Link — Local Agent Memory", "## Link — Personal Knowledge Wiki")
    $headerPattern = ($headers | ForEach-Object { [regex]::Escape($_) }) -join "|"
    $pattern = "(?s)(^|`n)(?:$headerPattern)`n.*?(?=`n## |\z)"

    if ([regex]::IsMatch($existing, $pattern)) {
        $updated = [regex]::Replace($existing, $pattern, {
            param($match)
            $prefix = if ($match.Groups[1].Value) { "`n" } else { "" }
            return $prefix + $source
        }).TrimEnd() + "`n"
    } else {
        $separator = if ($existing.Trim()) { "`n`n" } else { "" }
        $updated = $existing.TrimEnd() + $separator + $source + "`n"
    }

    Set-Content -Encoding UTF8 -NoNewline -Path $Target -Value $updated
    Write-Host "$Label -> $Target"
}

function Link-ToHashtable {
    param($InputObject)

    if ($null -eq $InputObject) {
        return @{}
    }
    if ($InputObject -is [System.Collections.IDictionary]) {
        $out = @{}
        foreach ($key in $InputObject.Keys) {
            $out[$key] = Link-ToHashtable $InputObject[$key]
        }
        return $out
    }
    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $out = @{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $out[$property.Name] = Link-ToHashtable $property.Value
        }
        return $out
    }
    if ($InputObject -is [System.Array]) {
        return @($InputObject | ForEach-Object { Link-ToHashtable $_ })
    }
    return $InputObject
}

function Link-UpsertMcpJson {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string]$WikiPath,
        [string]$TopKey = "mcpServers",
        [switch]$IncludeType,
        [switch]$IncludeDisabled
    )

    Link-NewParentDirectory $Path
    $config = @{}
    if (Test-Path $Path) {
        try {
            $raw = Get-Content -Raw -Encoding UTF8 $Path
            if ($raw.Trim()) {
                $config = Link-ToHashtable ($raw | ConvertFrom-Json)
            }
        } catch {
            Write-Host "  · Could not parse $Path; leaving it unchanged."
            Write-Host "    Add manually: $Command -m link_mcp --wiki $WikiPath --surface slim"
            return
        }
    }

    if (-not $config.ContainsKey($TopKey) -or -not ($config[$TopKey] -is [System.Collections.IDictionary])) {
        $config[$TopKey] = @{}
    }

    $server = @{
        command = $Command
        args = @("-m", "link_mcp", "--wiki", $WikiPath, "--surface", "slim")
    }
    if ($IncludeType) {
        $server["type"] = "stdio"
    }
    if ($IncludeDisabled) {
        $server["disabled"] = $false
    }

    $config[$TopKey]["link"] = $server
    $json = $config | ConvertTo-Json -Depth 20
    Set-Content -Encoding UTF8 -Path $Path -Value ($json + "`n")
    Write-Host "  ✓ Link MCP registered in $Path"
}

function Link-ReadMcpPython {
    param([Parameter(Mandatory = $true)][string]$WikiPath)

    $root = Split-Path -Parent $WikiPath
    $marker = Join-Path $root ".link-mcp-python"
    if (Test-Path $marker) {
        $value = (Get-Content -Raw -Encoding UTF8 $marker).Trim()
        if ($value) {
            return $value
        }
    }
    return "py"
}

function Link-PrintNextSteps {
    param([string]$Mode = "--global")

    Write-Host ""
    Write-Host "Done."
    if ($Mode -eq "--project") {
        Write-Host "  Drop sources into raw/."
        Write-Host "  View wiki: py link.py serve"
        Write-Host "  Print starter prompts: py link.py next"
        Write-Host "  Try in your agent:"
        Write-Host "    is Link ready?"
        Write-Host "    start with Link before we continue"
        Write-Host "    remember that this project uses Link for local agent memory"
        Write-Host "    what does Link remember about this project?"
        Write-Host "    ingest raw/<file> into Link"
    } else {
        Write-Host "  Drop sources into ~/link/raw/."
        Write-Host "  View wiki: lnk serve"
        Write-Host "  Print starter prompts: lnk next"
        Write-Host "  Try in your agent:"
        Write-Host "    is Link ready?"
        Write-Host "    start with Link before we continue"
        Write-Host "    remember that I prefer local-first agent memory"
        Write-Host "    what does Link know about me?"
        Write-Host "    ingest raw/<file> into Link"
    }
}
