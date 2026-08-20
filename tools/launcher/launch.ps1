[CmdletBinding()]
param(
	[Parameter(Mandatory = $true)]
	[string] $RepositoryRoot
)

$ErrorActionPreference = "Stop"
$resolvedRepositoryRoot = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$localRoot = Join-Path $env:LOCALAPPDATA "AphelionLoreTools"
$runtimeRoot = Join-Path $localRoot "runtime"
$settingsPath = Join-Path $localRoot "settings.json"
$requirementsPath = Join-Path $resolvedRepositoryRoot "tools\lore_editor\requirements.txt"
$runtimeManifestPath = Join-Path $resolvedRepositoryRoot "tools\launcher\runtime_manifest.json"
$runtimeManifest = Get-Content -LiteralPath $runtimeManifestPath -Raw | ConvertFrom-Json

function Test-PythonRuntime {
	param([string] $PythonPath)
	if (-not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
		return $false
	}
	try {
		$versionCheck = & $PythonPath -c "import sys; print('ok' if sys.version_info >= (3, 11) else 'old')" 2>$null
		if (($versionCheck | Select-Object -Last 1) -ne "ok") {
			return $false
		}
		& $PythonPath -c "import PIL" 2>$null
		return $LASTEXITCODE -eq 0
	}
	catch {
		return $false
	}
}

function Find-CompatiblePython {
	$candidates = @()
	$pythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
	if ($pythonCommand) { $candidates += $pythonCommand.Source }
	$pyCommand = Get-Command py.exe -ErrorAction SilentlyContinue
	if ($pyCommand) {
		try {
			$pyPath = & $pyCommand.Source -3 -c "import sys; print(sys.executable)" 2>$null
			if ($pyPath) { $candidates += ($pyPath | Select-Object -Last 1).Trim() }
		}
		catch { }
	}
	$candidates += (Join-Path $runtimeRoot "python\python.exe")
	foreach ($candidate in ($candidates | Select-Object -Unique)) {
		if (Test-PythonRuntime $candidate) { return $candidate }
	}
	return $null
}

function Show-RequirementsGuidance {
	Write-Host ""
	Write-Host "Lore Tools needs 64-bit Python 3.11 or newer with Pillow installed." -ForegroundColor Yellow
	Write-Host "Install Python from https://www.python.org/downloads/windows/ and then run:" -ForegroundColor Yellow
	Write-Host "  python -m pip install -r tools\lore_editor\requirements.txt" -ForegroundColor Yellow
	Write-Host "Then double-click Launch Lore Tools.cmd again." -ForegroundColor Yellow
}

function Install-PrivatePython {
	New-Item -ItemType Directory -Force -Path $runtimeRoot | Out-Null
	$installerFileName = "python-$($runtimeManifest.version)-$($runtimeManifest.architecture).exe"
	$installerPath = Join-Path $runtimeRoot $installerFileName
	$temporaryInstallerPath = "$installerPath.download"
	$installerUrl = [string]$runtimeManifest.installer_url
	Write-Host "Downloading the official Python $($runtimeManifest.version) installer..."
	Remove-Item -LiteralPath $temporaryInstallerPath -Force -ErrorAction SilentlyContinue
	Invoke-WebRequest -Uri $installerUrl -OutFile $temporaryInstallerPath
	$signature = Get-AuthenticodeSignature -LiteralPath $temporaryInstallerPath
	if ($signature.Status -ne "Valid" -or $signature.SignerCertificate.Subject -notlike "*$($runtimeManifest.signature_subject_contains)*") {
		Remove-Item -LiteralPath $temporaryInstallerPath -Force -ErrorAction SilentlyContinue
		throw "The downloaded Python installer did not have the expected valid Python Software Foundation signature."
	}
	Move-Item -LiteralPath $temporaryInstallerPath -Destination $installerPath -Force
	$installPath = Join-Path $runtimeRoot "python"
	$arguments = @(
		"/quiet",
		"InstallAllUsers=0",
		"PrependPath=0",
		"Include_launcher=0",
		"Include_test=0",
		("TargetDir=" + $installPath)
	)
	$installer = Start-Process -FilePath $installerPath -ArgumentList $arguments -Wait -PassThru
	if ($installer.ExitCode -ne 0) { throw "Python installation failed with exit code $($installer.ExitCode)." }
	$pythonPath = Join-Path $installPath "python.exe"
	if (-not (Test-Path -LiteralPath $pythonPath -PathType Leaf)) { throw "Python installation completed without creating python.exe." }
	& $pythonPath -m pip install --disable-pip-version-check --no-input -r $requirementsPath
	if ($LASTEXITCODE -ne 0) { throw "Installing the Lore Tools Python dependency failed." }
	return $pythonPath
}

function Read-GameRepository {
	if (Test-Path -LiteralPath $settingsPath -PathType Leaf) {
		try {
			$settings = Get-Content -LiteralPath $settingsPath -Raw | ConvertFrom-Json
			if ($settings.gameRepository -and (Test-Path -LiteralPath $settings.gameRepository -PathType Container)) {
				return (Resolve-Path -LiteralPath $settings.gameRepository).Path
			}
		}
		catch { }
	}
	$defaultGameRoot = Join-Path (Split-Path -Parent $resolvedRepositoryRoot) "Meridian-Rift"
	if (Test-Path -LiteralPath $defaultGameRoot -PathType Container) {
		$answer = Read-Host "Use the nearby Meridian-Rift checkout at '$defaultGameRoot'? (Y/n)"
		if ([string]::IsNullOrWhiteSpace($answer) -or $answer -match '^(y|yes)$') { return (Resolve-Path -LiteralPath $defaultGameRoot).Path }
	}
	$gameRoot = Read-Host "Enter the full path to your local Meridian-Rift checkout (blank to continue without it)"
	if ([string]::IsNullOrWhiteSpace($gameRoot)) { return $null }
	if (-not (Test-Path -LiteralPath $gameRoot -PathType Container)) { throw "The selected game checkout does not exist: $gameRoot" }
	$resolvedGameRoot = (Resolve-Path -LiteralPath $gameRoot).Path
	return $resolvedGameRoot
}

function ConvertTo-EscapedArgument {
	param([string] $Argument)
	if ($Argument.Length -gt 0 -and $Argument -notmatch '[\s"]') {
		return $Argument
	}
	$escaped = New-Object System.Text.StringBuilder
	[void]$escaped.Append('"')
	$backslashCount = 0
	foreach ($character in $Argument.ToCharArray()) {
		if ($character -eq '\') {
			$backslashCount++
			continue
		}
		if ($character -eq '"') {
			[void]$escaped.Append('\' * (($backslashCount * 2) + 1))
			[void]$escaped.Append('"')
			$backslashCount = 0
			continue
		}
		if ($backslashCount -gt 0) {
			[void]$escaped.Append('\' * $backslashCount)
			$backslashCount = 0
		}
		[void]$escaped.Append($character)
	}
	if ($backslashCount -gt 0) {
		[void]$escaped.Append('\' * ($backslashCount * 2))
	}
	[void]$escaped.Append('"')
	return $escaped.ToString()
}

$python = Find-CompatiblePython
if (-not $python) {
	Write-Host "No compatible Python runtime was found." -ForegroundColor Yellow
	$downloadAnswer = Read-Host "Download and install a private Python runtime for this tool? (y/N)"
	if ($downloadAnswer -notmatch '^(y|yes)$') {
		Show-RequirementsGuidance
		exit 1
	}
	try { $python = Install-PrivatePython }
	catch {
		Write-Host $_.Exception.Message -ForegroundColor Red
		Show-RequirementsGuidance
		exit 1
	}
}

$gameRoot = Read-GameRepository
if ($gameRoot) {
	New-Item -ItemType Directory -Force -Path $localRoot | Out-Null
	@{ gameRepository = $gameRoot } | ConvertTo-Json | Set-Content -LiteralPath $settingsPath -Encoding UTF8
}
$arguments = @(
	(Join-Path $resolvedRepositoryRoot "tools\lore_editor\serve.py"),
	"--repo-root", $resolvedRepositoryRoot,
	"--port", "0"
)
if ($gameRoot) { $arguments += @("--game-repo", $gameRoot) }

$startInfo = New-Object System.Diagnostics.ProcessStartInfo
$startInfo.FileName = $python
$startInfo.Arguments = ($arguments | ForEach-Object { ConvertTo-EscapedArgument $_ }) -join ' '
$startInfo.WorkingDirectory = $resolvedRepositoryRoot
$startInfo.UseShellExecute = $false
$startInfo.RedirectStandardOutput = $true
$startInfo.RedirectStandardError = $true
$server = New-Object System.Diagnostics.Process
$server.StartInfo = $startInfo
$null = $server.Start()
$url = $null
while (-not $server.HasExited -and -not $url) {
	if (-not $server.StandardOutput.EndOfStream) {
		$line = $server.StandardOutput.ReadLine()
		if ($line -like "LORE_EDITOR_URL=*") { $url = $line.Substring("LORE_EDITOR_URL=".Length) }
		else { Write-Host $line }
	}
	else { Start-Sleep -Milliseconds 100 }
}
if (-not $url) {
	$errorOutput = $server.StandardError.ReadToEnd()
	throw "Lore Tools could not start its local server. $errorOutput"
}
Start-Process $url
Write-Host "Lore Tools is running at $url. Close this window to stop it."
while (-not $server.HasExited) {
	if (-not $server.StandardOutput.EndOfStream) { Write-Host $server.StandardOutput.ReadLine() }
	else { Start-Sleep -Milliseconds 250 }
}
