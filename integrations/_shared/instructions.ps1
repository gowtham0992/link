param()

$ErrorActionPreference = "Stop"

function Link-NewParentDirectory {
    param([Parameter(Mandatory = $true)][string]$Path)

    $parent = Split-Path -Parent $Path
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
}

function Link-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    # Relative to PowerShell's location, which Set-Location moves; .NET's
    # GetFullPath uses the process directory, which it does not (Windows
    # PowerShell 5.1 then wrote a project's CLAUDE.md into $HOME).
    return $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Path)
}

function Link-WriteTextFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][AllowEmptyString()][string]$Text
    )

    # UTF-8 without a BOM. A symlinked file is written through to its target
    # so the link stays a link; a read-only file is refused, never replaced.
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    if (Test-Path -LiteralPath $Path) {
        $item = Get-Item -LiteralPath $Path -Force
        if ($item.IsReadOnly) {
            throw "$Path is read-only; Link left it as it was. Make it writable and run this again."
        }
        if (([int]($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) -ne 0) {
            [System.IO.File]::WriteAllText($Path, $Text, $utf8)
            return
        }
    }
    $temp = "$Path.link-tmp"
    [System.IO.File]::WriteAllText($temp, $Text, $utf8)
    Move-Item -Force -LiteralPath $temp -Destination $Path
}

function Link-UpsertInstructions {
    param(
        [Parameter(Mandatory = $true)][string]$Target,
        [Parameter(Mandatory = $true)][string]$SourceFile,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $full = Link-FullPath $Target
    Link-NewParentDirectory $full
    # Link's section ends at the earliest of: its last line (the one starting
    # "Otherwise, "), the line before `lnk compile`'s block, the next heading,
    # the end of the file - the pattern in link_core/agent_instructions.py.
    # Everything else in the file keeps its bytes and line endings.
    $source = (Get-Content -Raw -Encoding UTF8 (Link-FullPath $SourceFile)).TrimEnd("`r", "`n")
    $existing = ""
    if (Test-Path -LiteralPath $full) {
        $existing = [System.IO.File]::ReadAllText($full, (New-Object System.Text.UTF8Encoding($false, $true)))
    }

    # The em dash is built, not typed: Windows PowerShell 5.1 reads a script
    # without a BOM as ANSI, and a typed one would never match the file.
    $dash = [string][char]0x2014
    $headers = @("## Link $dash Local Agent Memory", "## Link $dash Personal Knowledge Wiki")
    $headerPattern = ($headers | ForEach-Object { [regex]::Escape($_) }) -join "|"
    $pattern = "(?s)(^|`n)(?:$headerPattern)`r?`n.*?" +
        "(?:(?<=`n)Otherwise, [^`r`n]*" +
        "|(?=(?:`r?`n)+(?:<!-- BEGIN LINK MEMORY|#{1,6}[ `t]|[^`r`n]+`r?`n(?:=+|-+)[ `t]*(?:`r?`n|\z)))" +
        "|(?=(?:`r?`n)*\z))"
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
        Link-WriteTextFile -Path $full -Text $updated
    }
    Write-Host "$Label -> $Target"
}

function Link-ToHashtable {
    param($InputObject)

    # Objects become ordered dictionaries, so the person's keys keep their
    # order. Arrays are returned with the unary comma: a bare `return @(...)`
    # unrolls them, turning "args": ["server.js"] into "server.js" and an
    # empty array into null. A null stays null.
    if ($null -eq $InputObject) {
        return $null
    }
    if ($InputObject -is [System.Collections.IDictionary]) {
        $out = [ordered]@{}
        foreach ($key in $InputObject.Keys) {
            $out[$key] = Link-ToHashtable $InputObject[$key]
        }
        return $out
    }
    if ($InputObject -is [System.Management.Automation.PSCustomObject]) {
        $out = [ordered]@{}
        foreach ($property in $InputObject.PSObject.Properties) {
            $out[$property.Name] = Link-ToHashtable $property.Value
        }
        return $out
    }
    if ($InputObject -is [System.Array]) {
        $items = New-Object System.Collections.ArrayList
        foreach ($element in $InputObject) {
            [void]$items.Add((Link-ToHashtable $element))
        }
        return ,($items.ToArray())
    }
    return $InputObject
}

function Link-HasJsonComments {
    param([AllowEmptyString()][string]$Text)

    # PowerShell 7's ConvertFrom-Json skips // and /* */ comments, and writing
    # the object back would drop them: a file with comments is left alone.
    $masked = [regex]::Replace($Text, '"(?:[^"\\]|\\.)*"', '""')
    return ($masked.Contains("//") -or $masked.Contains("/*"))
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

    $full = Link-FullPath $Path
    Link-NewParentDirectory $full
    $config = [ordered]@{}
    if (Test-Path -LiteralPath $full) {
        try {
            $raw = [System.IO.File]::ReadAllText($full, (New-Object System.Text.UTF8Encoding($false, $true)))
            if (Link-HasJsonComments $raw) {
                $config = $null
            } elseif ($raw.Trim()) {
                $config = Link-ToHashtable ($raw | ConvertFrom-Json)
            }
        } catch {
            $config = $null
        }
        if (-not ($config -is [System.Collections.IDictionary])) {
            Write-Host "  · Could not parse $Path; leaving it unchanged."
            Write-Host "    Add manually: $Command -m link_mcp --wiki $WikiPath --surface slim"
            return
        }
    }

    if (-not $config.Contains($TopKey) -or -not ($config[$TopKey] -is [System.Collections.IDictionary])) {
        $config[$TopKey] = [ordered]@{}
    }

    $server = [ordered]@{
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
    # Set-Content -Encoding UTF8 writes a BOM on Windows PowerShell 5.1.
    Link-WriteTextFile -Path $full -Text ($json + "`n")
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
