param([switch]$Project)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $PSCommandPath
$LinkRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$Mode = if ($Project) { "--project" } else { "--global" }
$TargetDir = if ($Project) { (Get-Location).Path } else { Join-Path $HOME "link" }
$BasePython = if (Get-Command py -ErrorAction SilentlyContinue) {
    "py"
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    "python"
} else {
    throw "Python was not found. Install Python 3 and rerun this installer."
}

if (-not $Project) {
    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
}

function Copy-LinkFile {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination,
        [string]$Label = ""
    )

    if (Test-Path $Source) {
        $parent = Split-Path -Parent $Destination
        if ($parent) {
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
        }
        Copy-Item -Force -Path $Source -Destination $Destination
        if ($Label) {
            Write-Host "  Updated $Label"
        }
    }
}

function Install-LinkCommandWrapper {
    if ($Project -or -not (Test-Path (Join-Path $TargetDir "link.py"))) {
        return
    }

    $cliDir = if ($env:LINK_CLI_DIR) { $env:LINK_CLI_DIR } else { Join-Path $HOME ".local\bin" }
    $cmdPath = Join-Path $cliDir "lnk.cmd"
    $psPath = Join-Path $cliDir "lnk.ps1"
    $legacyCmdPath = Join-Path $cliDir "link.cmd"
    $legacyPsPath = Join-Path $cliDir "link.ps1"
    $marker = "Link command wrapper"
    $linkPy = Join-Path $TargetDir "link.py"

    New-Item -ItemType Directory -Force -Path $cliDir | Out-Null

    foreach ($legacyPath in @($legacyCmdPath, $legacyPsPath)) {
        if ((Test-Path $legacyPath) -and (Select-String -Quiet -SimpleMatch $marker $legacyPath)) {
            Remove-Item -Force $legacyPath
            Write-Host "  Removed old Link wrapper: $legacyPath"
        }
    }

    if ((Test-Path $cmdPath) -and -not (Select-String -Quiet -SimpleMatch $marker $cmdPath)) {
        Write-Host "  · $cmdPath already exists and is not a Link wrapper; not overwriting."
        Write-Host "    Fallback: $BasePython `"$linkPy`" health"
        return
    }

    $cmd = @"
@echo off
REM $marker
set LINK_CLI_COMMAND=lnk
$BasePython "$linkPy" %*
"@
    Set-Content -Encoding ASCII -Path $cmdPath -Value $cmd

    $ps = @"
# $marker
$env:LINK_CLI_COMMAND = "lnk"
& $BasePython "$linkPy" @args
exit `$LASTEXITCODE
"@
    Set-Content -Encoding UTF8 -Path $psPath -Value $ps

    Write-Host "  ✓ Link command: $cmdPath"
    $pathParts = ($env:PATH -split [IO.Path]::PathSeparator)
    if ($pathParts -notcontains $cliDir) {
        Write-Host "  · Add $cliDir to PATH to run: lnk health"
    }
}

$isUpdate = (Test-Path (Join-Path $TargetDir "wiki\index.md")) -or (Test-Path (Join-Path $TargetDir "wiki\log.md"))
if ($isUpdate) {
    Write-Host "  Existing wiki detected at $TargetDir - updating code only, wiki data untouched."
} else {
    Write-Host "  Fresh install at $TargetDir."
}

Copy-LinkFile (Join-Path $LinkRoot "serve.py") (Join-Path $TargetDir "serve.py") "serve.py"
Copy-LinkFile (Join-Path $LinkRoot "LINK.md") (Join-Path $TargetDir "LINK.md") "LINK.md"
Copy-LinkFile (Join-Path $LinkRoot "link.py") (Join-Path $TargetDir "link.py") "link.py"
Copy-LinkFile (Join-Path $LinkRoot "logo.png") (Join-Path $TargetDir "logo.png")
Copy-LinkFile (Join-Path $LinkRoot "logo.svg") (Join-Path $TargetDir "logo.svg")
Copy-LinkFile (Join-Path $LinkRoot ".linkignore") (Join-Path $TargetDir ".linkignore")

$coreDir = Join-Path $LinkRoot "mcp_package\link_core"
if (Test-Path $coreDir) {
    $targetCore = Join-Path $TargetDir "link_core"
    New-Item -ItemType Directory -Force -Path $targetCore | Out-Null
    Copy-Item -Force -Path (Join-Path $coreDir "*.py") -Destination $targetCore
    Write-Host "  Updated link_core"
}

$dirs = @(
    "raw",
    "wiki\sources",
    "wiki\concepts",
    "wiki\entities",
    "wiki\memories",
    "wiki\comparisons",
    "wiki\explorations"
)
foreach ($dir in $dirs) {
    $path = Join-Path $TargetDir $dir
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    if (-not $isUpdate) {
        New-Item -ItemType File -Force -Path (Join-Path $path ".gitkeep") | Out-Null
    }
}

if (-not $isUpdate) {
    & $BasePython (Join-Path $TargetDir "link.py") doctor --fix $TargetDir *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Link wiki initialization failed."
    }
    Write-Host "  Wiki structure created at $TargetDir"
}

Write-Host "  Wiki ready at $TargetDir"
Install-LinkCommandWrapper

Write-Host ""
Write-Host "  Setting up MCP server..."

$linkMcpPackage = if (Test-Path (Join-Path $LinkRoot "mcp_package")) {
    Join-Path $LinkRoot "mcp_package"
} else {
    "link-mcp"
}
$mcpPython = $BasePython
$venv = if ($env:LINK_MCP_VENV) { $env:LINK_MCP_VENV } else { Join-Path $HOME ".link-mcp-venv" }
$venvPython = Join-Path $venv "Scripts\python.exe"
$marker = Join-Path $TargetDir ".link-mcp-python"
$installed = $false
$reused = $false

& $BasePython -m pip install --upgrade $linkMcpPackage -q *> $null
if ($LASTEXITCODE -eq 0) {
    $installed = $true
    $mcpPython = $BasePython
} else {
    & $BasePython -m venv $venv *> $null
    if ($LASTEXITCODE -eq 0 -and (Test-Path $venvPython)) {
        & $venvPython -m pip install --upgrade pip -q *> $null
        if ($LASTEXITCODE -eq 0) {
            & $venvPython -m pip install --upgrade $linkMcpPackage -q *> $null
            if ($LASTEXITCODE -eq 0) {
                $installed = $true
                $mcpPython = $venvPython
            }
        }
    }
}

if (-not $installed -and (Test-Path $marker)) {
    $candidate = (Get-Content -Raw -Encoding UTF8 $marker).Trim()
    if ($candidate) {
        & $candidate -c "import link_mcp" *> $null
        if ($LASTEXITCODE -eq 0) {
            $installed = $true
            $reused = $true
            $mcpPython = $candidate
        }
    }
} elseif (-not $installed -and (Test-Path $venvPython)) {
    & $venvPython -c "import link_mcp" *> $null
    if ($LASTEXITCODE -eq 0) {
        $installed = $true
        $reused = $true
        $mcpPython = $venvPython
    }
}

if ($installed) {
    Set-Content -Encoding UTF8 -Path $marker -Value ($mcpPython + "`n")
    if ($reused) {
        Write-Host "  ✓ existing link-mcp available"
        Write-Host "  · Automatic upgrade did not complete; run verify-mcp to confirm the installed version."
    } else {
        Write-Host "  ✓ link-mcp installed"
    }
    if ($mcpPython -ne $BasePython) {
        Write-Host "  ✓ MCP Python: $mcpPython"
    }
    Write-Host ""
    Write-Host "  Add to your MCP client config:"
    Write-Host "  {"
    Write-Host "    `"mcpServers`": {"
    Write-Host "      `"link`": {"
    Write-Host "        `"command`": `"$mcpPython`","
    Write-Host "        `"args`": [`"-m`", `"link_mcp`", `"--wiki`", `"$TargetDir\wiki`", `"--surface`", `"slim`"]"
    Write-Host "      }"
    Write-Host "    }"
    Write-Host "  }"
} else {
    Write-Host "  · Could not install link-mcp automatically."
    Write-Host "  Manual options:"
    Write-Host "    $BasePython -m pip install --upgrade link-mcp"
    Write-Host "    $BasePython -m venv ~/.link-mcp-venv"
    Write-Host "    ~\.link-mcp-venv\Scripts\python.exe -m pip install --upgrade pip link-mcp"
}

if (Test-Path (Join-Path $TargetDir "link.py")) {
    Write-Host ""
    if ($Project) {
        Write-Host "  Check Link readiness:"
        Write-Host "    py link.py health"
        Write-Host "  Verify MCP setup:"
        Write-Host "    py link.py verify-mcp"
    } else {
        Write-Host "  Check Link readiness:"
        Write-Host "    lnk health"
        Write-Host "  Verify MCP setup:"
        Write-Host "    lnk verify-mcp"
    }
}
