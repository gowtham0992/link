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
    # Link's section ends at the next heading of any level; everything else in
    # the file keeps its bytes and line endings, and is written without a BOM.
    $source = (Get-Content -Raw -Encoding UTF8 $SourceFile).TrimEnd("`r", "`n")
    $existing = ""
    if (Test-Path $Target) {
        $existing = [System.IO.File]::ReadAllText((Resolve-Path $Target).Path, (New-Object System.Text.UTF8Encoding($false, $true)))
    }

    $headers = @("## Link — Local Agent Memory", "## Link — Personal Knowledge Wiki")
    $headerPattern = ($headers | ForEach-Object { [regex]::Escape($_) }) -join "|"
    $pattern = "(?s)(^|`n)(?:$headerPattern)`r?`n.*?(?=`r?`n#{1,6}[ `t]|\z)"
    $newline = if ($existing.Contains("`r`n")) { "`r`n" } else { "`n" }
    $block = ($source -replace "`r?`n", "`n") -replace "`n", $newline

    if (-not $existing.Trim()) {
        $updated = $block + $newline
    } elseif ([regex]::IsMatch($existing, $pattern)) {
        $match = [regex]::Match($existing, $pattern)
        $updated = $existing.Substring(0, $match.Index) + $match.Groups[1].Value + $block + $existing.Substring($match.Index + $match.Length)
    } else {
        $separator = if ($existing.EndsWith($newline + $newline)) { "" } elseif ($existing.EndsWith($newline)) { $newline } else { $newline + $newline }
        $updated = $existing + $separator + $block + $newline
    }

    if ($updated -ne $existing) {
        $full = [System.IO.Path]::GetFullPath($Target)
        $temp = "$full.link-tmp"
        [System.IO.File]::WriteAllText($temp, $updated, (New-Object System.Text.UTF8Encoding($false)))
        Move-Item -Force -Path $temp -Destination $full
    }
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
