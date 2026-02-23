#Requires -Version 5.1
<#
.SYNOPSIS
    OpenReach Installer Wizard -- full GUI setup for non-technical users.
.DESCRIPTION
    Downloads/installs Python, Ollama, the OpenReach project, LLM model,
    Playwright browser, and creates a desktop shortcut.
    Uses Windows Forms for a native wizard experience with progress bars.
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------------------
# Load Windows Forms
# ---------------------------------------------------------------------------
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
$script:InstallDir     = Join-Path $env:USERPROFILE 'OpenReach'
$script:CreateShortcut = $true
$script:SelectedModel  = 'qwen3:4b'
$script:PythonPath     = ''
$script:OllamaPath     = ''
$script:HasPython      = $false
$script:HasOllama      = $false
$script:HasGit         = $false
$script:LogFile        = Join-Path $env:TEMP 'openreach_install.log'
$script:Cancelled      = $false

# Model options: name, display, size, description
$script:Models = @(
    @{ Name='qwen3:4b';  Display='Qwen 3 4B (Recommended)'; Size='~2.5 GB'; Desc='Best balance of quality and speed. Runs on most computers with 4 GB RAM.' },
    @{ Name='qwen3:1.7b'; Display='Qwen 3 1.7B (Lightweight)'; Size='~1.0 GB'; Desc='Faster, lower RAM usage. Good for older hardware. Slightly less capable.' },
    @{ Name='qwen3:8b';  Display='Qwen 3 8B (Advanced)'; Size='~5.0 GB'; Desc='Highest quality messages. Requires 8+ GB RAM and a modern GPU.' }
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
function Write-Log {
    param([string]$Message)
    $ts = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    "$ts  $Message" | Out-File -Append -FilePath $script:LogFile -Encoding utf8
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
function Test-CommandAvailable {
    param([string]$Cmd)
    try { $null = Get-Command $Cmd -ErrorAction Stop; return $true }
    catch { return $false }
}

function Get-PythonVersion {
    param([string]$Exe)
    try {
        $out = & $Exe --version 2>&1 | Out-String
        if ($out -match '(\d+)\.(\d+)\.(\d+)') {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) { return $out.Trim() }
        }
    } catch {}
    return $null
}

function Find-Python {
    foreach ($cmd in @('python','python3','py')) {
        if (Test-CommandAvailable $cmd) {
            $ver = Get-PythonVersion $cmd
            if ($ver) {
                $script:PythonPath = (Get-Command $cmd).Source
                $script:HasPython = $true
                Write-Log "Found Python: $ver at $($script:PythonPath)"
                return $ver
            }
        }
    }
    # Check common install locations
    $locations = @(
        "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Python313\python.exe","C:\Python312\python.exe","C:\Python311\python.exe"
    )
    foreach ($loc in $locations) {
        if (Test-Path $loc) {
            $ver = Get-PythonVersion $loc
            if ($ver) {
                $script:PythonPath = $loc
                $script:HasPython = $true
                Write-Log "Found Python at known path: $loc ($ver)"
                return $ver
            }
        }
    }
    $script:HasPython = $false
    Write-Log 'Python 3.11+ not found'
    return $null
}

function Find-Ollama {
    if (Test-CommandAvailable 'ollama') {
        $script:OllamaPath = (Get-Command 'ollama').Source
        $script:HasOllama = $true
        Write-Log "Found Ollama at $($script:OllamaPath)"
        return $true
    }
    $defaultPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
    if (Test-Path $defaultPath) {
        $script:OllamaPath = $defaultPath
        $script:HasOllama = $true
        Write-Log "Found Ollama at default path: $defaultPath"
        return $true
    }
    $script:HasOllama = $false
    Write-Log 'Ollama not found'
    return $false
}

function Find-Git {
    $script:HasGit = Test-CommandAvailable 'git'
    Write-Log "Git available: $($script:HasGit)"
    return $script:HasGit
}

function Download-File {
    param([string]$Url, [string]$OutFile, [System.Windows.Forms.ProgressBar]$Bar, [System.Windows.Forms.Label]$Status)
    Write-Log "Downloading $Url -> $OutFile"
    try {
        if ($Status) { $Status.Text = "Downloading $(Split-Path $OutFile -Leaf)..." }
        if ($Bar) { $Bar.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee }

        # Use BITS for large downloads (shows real progress), WebClient as fallback
        try {
            $job = Start-BitsTransfer -Source $Url -Destination $OutFile -Asynchronous
            while ($job.JobState -eq 'Transferring' -or $job.JobState -eq 'Connecting') {
                if ($job.BytesTotal -gt 0 -and $Bar) {
                    $pct = [int](($job.BytesTransferred / $job.BytesTotal) * 100)
                    $Bar.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
                    $Bar.Value = [Math]::Min($pct, 100)
                    $mbDone = [Math]::Round($job.BytesTransferred / 1MB, 1)
                    $mbTotal = [Math]::Round($job.BytesTotal / 1MB, 1)
                    if ($Status) { $Status.Text = "Downloading... $mbDone MB / $mbTotal MB" }
                }
                [System.Windows.Forms.Application]::DoEvents()
                Start-Sleep -Milliseconds 500
            }
            if ($job.JobState -eq 'Transferred') {
                Complete-BitsTransfer $job
                Write-Log "Download complete (BITS): $OutFile"
                return $true
            } else {
                Write-Log "BITS transfer failed: $($job.JobState). Falling back to WebClient."
                Remove-BitsTransfer $job -ErrorAction SilentlyContinue
            }
        } catch {
            Write-Log "BITS not available, using WebClient: $_"
        }

        # Fallback: WebClient (no per-byte progress but reliable)
        if ($Bar) { $Bar.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee }
        if ($Status) { $Status.Text = "Downloading $(Split-Path $OutFile -Leaf)... (please wait)" }
        [System.Windows.Forms.Application]::DoEvents()

        $wc = New-Object System.Net.WebClient
        $wc.Headers.Add('User-Agent', 'OpenReach-Installer/1.0')
        $wc.DownloadFile($Url, $OutFile)
        Write-Log "Download complete (WebClient): $OutFile"
        return $true
    } catch {
        Write-Log "Download failed: $_"
        return $false
    }
}

function Run-Process {
    param(
        [string]$Exe,
        [string[]]$Arguments,
        [int]$TimeoutSec = 600,
        [switch]$Silent
    )
    Write-Log "Running: $Exe $($Arguments -join ' ')"
    try {
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $Exe
        $psi.Arguments = $Arguments -join ' '
        $psi.UseShellExecute = $false
        $psi.RedirectStandardOutput = $true
        $psi.RedirectStandardError = $true
        $psi.CreateNoWindow = $Silent.IsPresent
        $psi.WindowStyle = if ($Silent) { 'Hidden' } else { 'Normal' }

        $proc = [System.Diagnostics.Process]::Start($psi)
        $stdout = $proc.StandardOutput.ReadToEnd()
        $stderr = $proc.StandardError.ReadToEnd()
        $proc.WaitForExit($TimeoutSec * 1000) | Out-Null

        Write-Log "Exit code: $($proc.ExitCode)"
        if ($stdout) { Write-Log "STDOUT: $($stdout.Substring(0, [Math]::Min($stdout.Length, 500)))" }
        if ($stderr -and $proc.ExitCode -ne 0) { Write-Log "STDERR: $($stderr.Substring(0, [Math]::Min($stderr.Length, 500)))" }

        return @{ ExitCode=$proc.ExitCode; Stdout=$stdout; Stderr=$stderr }
    } catch {
        Write-Log "Process failed: $_"
        return @{ ExitCode=-1; Stdout=''; Stderr=$_.ToString() }
    }
}

# ---------------------------------------------------------------------------
# Create the main wizard form
# ---------------------------------------------------------------------------
$form = New-Object System.Windows.Forms.Form
$form.Text = 'OpenReach Setup'
$form.Size = New-Object System.Drawing.Size(640, 520)
$form.StartPosition = 'CenterScreen'
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $true
$form.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)
$form.BackColor = [System.Drawing.Color]::White

# Header panel (dark bar at top)
$header = New-Object System.Windows.Forms.Panel
$header.Dock = 'Top'
$header.Height = 70
$header.BackColor = [System.Drawing.Color]::FromArgb(15, 15, 15)
$form.Controls.Add($header)

$headerTitle = New-Object System.Windows.Forms.Label
$headerTitle.Text = 'OpenReach Setup'
$headerTitle.ForeColor = [System.Drawing.Color]::White
$headerTitle.Font = New-Object System.Drawing.Font('Segoe UI', 16, [System.Drawing.FontStyle]::Bold)
$headerTitle.Location = New-Object System.Drawing.Point(24, 12)
$headerTitle.AutoSize = $true
$header.Controls.Add($headerTitle)

$headerSub = New-Object System.Windows.Forms.Label
$headerSub.Text = 'Social Media Outreach Agent'
$headerSub.ForeColor = [System.Drawing.Color]::FromArgb(160, 160, 160)
$headerSub.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$headerSub.Location = New-Object System.Drawing.Point(26, 44)
$headerSub.AutoSize = $true
$header.Controls.Add($headerSub)

# Bottom button panel
$btnPanel = New-Object System.Windows.Forms.Panel
$btnPanel.Dock = 'Bottom'
$btnPanel.Height = 55
$btnPanel.BackColor = [System.Drawing.Color]::FromArgb(240, 240, 240)
$form.Controls.Add($btnPanel)

$btnBack = New-Object System.Windows.Forms.Button
$btnBack.Text = '< Back'
$btnBack.Size = New-Object System.Drawing.Size(90, 32)
$btnBack.Location = New-Object System.Drawing.Point(330, 12)
$btnBack.Enabled = $false
$btnBack.FlatStyle = 'Flat'
$btnPanel.Controls.Add($btnBack)

$btnNext = New-Object System.Windows.Forms.Button
$btnNext.Text = 'Next >'
$btnNext.Size = New-Object System.Drawing.Size(90, 32)
$btnNext.Location = New-Object System.Drawing.Point(425, 12)
$btnNext.BackColor = [System.Drawing.Color]::FromArgb(124, 58, 237)
$btnNext.ForeColor = [System.Drawing.Color]::White
$btnNext.FlatStyle = 'Flat'
$btnNext.FlatAppearance.BorderSize = 0
$btnPanel.Controls.Add($btnNext)

$btnCancel = New-Object System.Windows.Forms.Button
$btnCancel.Text = 'Cancel'
$btnCancel.Size = New-Object System.Drawing.Size(90, 32)
$btnCancel.Location = New-Object System.Drawing.Point(525, 12)
$btnCancel.FlatStyle = 'Flat'
$btnPanel.Controls.Add($btnCancel)

# Content area (between header and buttons)
$content = New-Object System.Windows.Forms.Panel
$content.Location = New-Object System.Drawing.Point(0, 70)
$content.Size = New-Object System.Drawing.Size(640, 340)
$content.BackColor = [System.Drawing.Color]::White
$form.Controls.Add($content)

# ---------------------------------------------------------------------------
# Page system
# ---------------------------------------------------------------------------
$script:CurrentPage = 0
$script:Pages = @()

function New-Page {
    $p = New-Object System.Windows.Forms.Panel
    $p.Location = New-Object System.Drawing.Point(0, 0)
    $p.Size = New-Object System.Drawing.Size(640, 340)
    $p.BackColor = [System.Drawing.Color]::White
    $p.Visible = $false
    $content.Controls.Add($p)
    $script:Pages += $p
    return $p
}

function Show-Page {
    param([int]$Index)
    for ($i = 0; $i -lt $script:Pages.Count; $i++) {
        $script:Pages[$i].Visible = ($i -eq $Index)
    }
    $script:CurrentPage = $Index
    $btnBack.Enabled = ($Index -gt 0 -and $Index -lt 4)
    $headerSub.Text = @('Welcome','License Agreement','Setup Options','Component Check','Installing...','Complete')[$Index]
    [System.Windows.Forms.Application]::DoEvents()
}

# ========================== PAGE 0: Welcome ==========================
$p0 = New-Page

$w0 = New-Object System.Windows.Forms.Label
$w0.Text = "Welcome to the OpenReach installer.`r`n`r`nThis wizard will download and set up everything you need to run OpenReach on your computer.`r`n`r`nOpenReach uses a local AI model to generate personalized outreach messages and a browser engine to deliver them -- everything runs on your machine."
$w0.Location = New-Object System.Drawing.Point(30, 20)
$w0.Size = New-Object System.Drawing.Size(570, 110)
$p0.Controls.Add($w0)

$warnBox = New-Object System.Windows.Forms.Panel
$warnBox.Location = New-Object System.Drawing.Point(30, 145)
$warnBox.Size = New-Object System.Drawing.Size(570, 120)
$warnBox.BackColor = [System.Drawing.Color]::FromArgb(255, 248, 230)
$warnBox.BorderStyle = 'FixedSingle'
$p0.Controls.Add($warnBox)

$warnIcon = New-Object System.Windows.Forms.Label
$warnIcon.Text = 'LARGE DOWNLOADS'
$warnIcon.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$warnIcon.ForeColor = [System.Drawing.Color]::FromArgb(180, 120, 0)
$warnIcon.Location = New-Object System.Drawing.Point(12, 10)
$warnIcon.AutoSize = $true
$warnBox.Controls.Add($warnIcon)

$warnText = New-Object System.Windows.Forms.Label
$warnText.Text = "This installer will download up to 3-5 GB of data:`r`n`r`n  - Python (if needed): ~30 MB`r`n  - Ollama (if needed): ~100 MB`r`n  - AI Model: 1 - 5 GB (depending on your choice)`r`n  - Browser Engine: ~150 MB`r`n  - Python Packages: ~50 MB`r`n`r`nPlease use a stable internet connection. Installation may take 10-20 minutes."
$warnText.Location = New-Object System.Drawing.Point(12, 35)
$warnText.Size = New-Object System.Drawing.Size(545, 80)
$warnText.ForeColor = [System.Drawing.Color]::FromArgb(120, 80, 0)
$warnBox.Controls.Add($warnText)

$reqLabel = New-Object System.Windows.Forms.Label
$reqLabel.Text = 'System Requirements: Windows 10/11  |  4 GB RAM minimum  |  6 GB free disk space'
$reqLabel.Location = New-Object System.Drawing.Point(30, 285)
$reqLabel.Size = New-Object System.Drawing.Size(570, 20)
$reqLabel.ForeColor = [System.Drawing.Color]::Gray
$p0.Controls.Add($reqLabel)

# ========================== PAGE 1: License ==========================
$p1 = New-Page

$licLabel = New-Object System.Windows.Forms.Label
$licLabel.Text = 'Please read the following important information before continuing:'
$licLabel.Location = New-Object System.Drawing.Point(30, 10)
$licLabel.Size = New-Object System.Drawing.Size(570, 20)
$p1.Controls.Add($licLabel)

$licBox = New-Object System.Windows.Forms.TextBox
$licBox.Multiline = $true
$licBox.ReadOnly = $true
$licBox.ScrollBars = 'Vertical'
$licBox.Location = New-Object System.Drawing.Point(30, 35)
$licBox.Size = New-Object System.Drawing.Size(570, 240)
$licBox.BackColor = [System.Drawing.Color]::White
$licBox.Font = New-Object System.Drawing.Font('Consolas', 8.5)
$licBox.Text = @"
MIT License -- Copyright (c) 2026 Cormass Group

Permission is hereby granted, free of charge, to any person obtaining
a copy of this software to deal in the Software without restriction.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.

IMPORTANT DISCLAIMER:

1. YOU are solely responsible for complying with all applicable laws
   (CAN-SPAM, GDPR, CASL, etc.) and platform Terms of Service.

2. Automated outreach may result in account suspension or bans on
   social media platforms. The authors accept NO liability.

3. You will NOT use this tool for spam, harassment, or any form of
   illegal or unwanted communication.

4. This software is a tool -- how you use it is your responsibility.

Full license: LICENSE file  |  Full disclaimer: DISCLAIMER.md
"@
$p1.Controls.Add($licBox)

$licCheck = New-Object System.Windows.Forms.CheckBox
$licCheck.Text = 'I have read and accept the license terms and disclaimer'
$licCheck.Location = New-Object System.Drawing.Point(30, 285)
$licCheck.Size = New-Object System.Drawing.Size(400, 22)
$licCheck.Add_CheckedChanged({ $btnNext.Enabled = $licCheck.Checked })
$p1.Controls.Add($licCheck)

# ========================== PAGE 2: Options ==========================
$p2 = New-Page

# Install location
$locLabel = New-Object System.Windows.Forms.Label
$locLabel.Text = 'Installation Folder:'
$locLabel.Location = New-Object System.Drawing.Point(30, 15)
$locLabel.AutoSize = $true
$locLabel.Font = New-Object System.Drawing.Font('Segoe UI', 9.5, [System.Drawing.FontStyle]::Bold)
$p2.Controls.Add($locLabel)

$locBox = New-Object System.Windows.Forms.TextBox
$locBox.Text = $script:InstallDir
$locBox.Location = New-Object System.Drawing.Point(30, 40)
$locBox.Size = New-Object System.Drawing.Size(480, 26)
$p2.Controls.Add($locBox)

$locBrowse = New-Object System.Windows.Forms.Button
$locBrowse.Text = 'Browse...'
$locBrowse.Location = New-Object System.Drawing.Point(520, 38)
$locBrowse.Size = New-Object System.Drawing.Size(80, 28)
$locBrowse.FlatStyle = 'Flat'
$locBrowse.Add_Click({
    $fbd = New-Object System.Windows.Forms.FolderBrowserDialog
    $fbd.Description = 'Choose installation folder'
    $fbd.SelectedPath = $locBox.Text
    if ($fbd.ShowDialog() -eq 'OK') { $locBox.Text = $fbd.SelectedPath }
})
$p2.Controls.Add($locBrowse)

# Model selection
$mdlLabel = New-Object System.Windows.Forms.Label
$mdlLabel.Text = 'AI Model:'
$mdlLabel.Location = New-Object System.Drawing.Point(30, 85)
$mdlLabel.AutoSize = $true
$mdlLabel.Font = New-Object System.Drawing.Font('Segoe UI', 9.5, [System.Drawing.FontStyle]::Bold)
$p2.Controls.Add($mdlLabel)

$mdlGroup = New-Object System.Windows.Forms.GroupBox
$mdlGroup.Location = New-Object System.Drawing.Point(30, 105)
$mdlGroup.Size = New-Object System.Drawing.Size(570, 145)
$mdlGroup.Text = ''
$p2.Controls.Add($mdlGroup)

$yOff = 15
$script:ModelRadios = @()
foreach ($m in $script:Models) {
    $rb = New-Object System.Windows.Forms.RadioButton
    $rb.Text = "$($m.Display)  --  $($m.Size)"
    $rb.Location = New-Object System.Drawing.Point(15, $yOff)
    $rb.Size = New-Object System.Drawing.Size(540, 20)
    $rb.Tag = $m.Name
    $rb.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)
    if ($m.Name -eq 'qwen3:4b') { $rb.Checked = $true }
    $mdlGroup.Controls.Add($rb)
    $script:ModelRadios += $rb

    $descLbl = New-Object System.Windows.Forms.Label
    $descLbl.Text = $m.Desc
    $descLbl.Location = New-Object System.Drawing.Point(35, ($yOff + 20))
    $descLbl.Size = New-Object System.Drawing.Size(520, 18)
    $descLbl.ForeColor = [System.Drawing.Color]::Gray
    $descLbl.Font = New-Object System.Drawing.Font('Segoe UI', 8.5)
    $mdlGroup.Controls.Add($descLbl)

    $yOff += 42
}

# Desktop shortcut
$scCheck = New-Object System.Windows.Forms.CheckBox
$scCheck.Text = 'Create Desktop shortcut'
$scCheck.Checked = $true
$scCheck.Location = New-Object System.Drawing.Point(30, 270)
$scCheck.Size = New-Object System.Drawing.Size(300, 22)
$p2.Controls.Add($scCheck)

# ========================== PAGE 3: Component Check ==========================
$p3 = New-Page

$chkTitle = New-Object System.Windows.Forms.Label
$chkTitle.Text = 'The installer detected the following on your system:'
$chkTitle.Location = New-Object System.Drawing.Point(30, 15)
$chkTitle.Size = New-Object System.Drawing.Size(570, 20)
$p3.Controls.Add($chkTitle)

$chkList = New-Object System.Windows.Forms.ListView
$chkList.View = 'Details'
$chkList.Location = New-Object System.Drawing.Point(30, 45)
$chkList.Size = New-Object System.Drawing.Size(570, 180)
$chkList.FullRowSelect = $true
$chkList.GridLines = $true
$chkList.HeaderStyle = 'Nonclickable'
$chkList.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)
$null = $chkList.Columns.Add('Component', 200)
$null = $chkList.Columns.Add('Status', 150)
$null = $chkList.Columns.Add('Action', 200)
$p3.Controls.Add($chkList)

$chkSummary = New-Object System.Windows.Forms.Label
$chkSummary.Text = ''
$chkSummary.Location = New-Object System.Drawing.Point(30, 240)
$chkSummary.Size = New-Object System.Drawing.Size(570, 60)
$chkSummary.ForeColor = [System.Drawing.Color]::FromArgb(80, 80, 80)
$p3.Controls.Add($chkSummary)

function Update-ComponentCheck {
    $chkList.Items.Clear()

    # Python
    $pyVer = Find-Python
    $pyItem = New-Object System.Windows.Forms.ListViewItem('Python 3.11+')
    if ($script:HasPython) {
        $pyItem.SubItems.Add($pyVer)
        $pyItem.SubItems.Add('Already installed')
        $pyItem.ForeColor = [System.Drawing.Color]::FromArgb(0, 128, 0)
    } else {
        $pyItem.SubItems.Add('Not found')
        $pyItem.SubItems.Add('Will download and install (~30 MB)')
        $pyItem.ForeColor = [System.Drawing.Color]::FromArgb(200, 120, 0)
    }
    $chkList.Items.Add($pyItem)

    # Ollama
    Find-Ollama | Out-Null
    $olItem = New-Object System.Windows.Forms.ListViewItem('Ollama')
    if ($script:HasOllama) {
        $olItem.SubItems.Add('Installed')
        $olItem.SubItems.Add('Already installed')
        $olItem.ForeColor = [System.Drawing.Color]::FromArgb(0, 128, 0)
    } else {
        $olItem.SubItems.Add('Not found')
        $olItem.SubItems.Add('Will download and install (~100 MB)')
        $olItem.ForeColor = [System.Drawing.Color]::FromArgb(200, 120, 0)
    }
    $chkList.Items.Add($olItem)

    # Git
    Find-Git | Out-Null
    $gitItem = New-Object System.Windows.Forms.ListViewItem('Git')
    if ($script:HasGit) {
        $gitItem.SubItems.Add('Installed')
        $gitItem.SubItems.Add('Will clone from GitHub')
        $gitItem.ForeColor = [System.Drawing.Color]::FromArgb(0, 128, 0)
    } else {
        $gitItem.SubItems.Add('Not found')
        $gitItem.SubItems.Add('Will download ZIP from GitHub')
        $gitItem.ForeColor = [System.Drawing.Color]::FromArgb(100, 100, 100)
    }
    $chkList.Items.Add($gitItem)

    # AI Model
    $mdlItem = New-Object System.Windows.Forms.ListViewItem("AI Model ($($script:SelectedModel))")
    $mdlSize = ($script:Models | Where-Object { $_.Name -eq $script:SelectedModel }).Size
    $mdlItem.SubItems.Add('Required')
    $mdlItem.SubItems.Add("Will download ($mdlSize)")
    $mdlItem.ForeColor = [System.Drawing.Color]::FromArgb(200, 120, 0)
    $chkList.Items.Add($mdlItem)

    # Browser
    $brItem = New-Object System.Windows.Forms.ListViewItem('Playwright Chromium')
    $brItem.SubItems.Add('Required')
    $brItem.SubItems.Add('Will download (~150 MB)')
    $brItem.ForeColor = [System.Drawing.Color]::FromArgb(200, 120, 0)
    $chkList.Items.Add($brItem)

    # Summary
    $downloads = @()
    if (-not $script:HasPython) { $downloads += 'Python' }
    if (-not $script:HasOllama) { $downloads += 'Ollama' }
    $downloads += 'OpenReach'
    $downloads += "AI Model ($mdlSize)"
    $downloads += 'Browser Engine'

    $chkSummary.Text = "Click 'Install' to begin. The following will be downloaded:`r`n$($downloads -join ', ')`r`n`r`nThis may take 10-20 minutes depending on your internet speed."
}

# ========================== PAGE 4: Installing ==========================
$p4 = New-Page

$instStatus = New-Object System.Windows.Forms.Label
$instStatus.Text = 'Preparing installation...'
$instStatus.Location = New-Object System.Drawing.Point(30, 20)
$instStatus.Size = New-Object System.Drawing.Size(570, 22)
$instStatus.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$p4.Controls.Add($instStatus)

$instDetail = New-Object System.Windows.Forms.Label
$instDetail.Text = ''
$instDetail.Location = New-Object System.Drawing.Point(30, 48)
$instDetail.Size = New-Object System.Drawing.Size(570, 20)
$instDetail.ForeColor = [System.Drawing.Color]::Gray
$p4.Controls.Add($instDetail)

$instBar = New-Object System.Windows.Forms.ProgressBar
$instBar.Location = New-Object System.Drawing.Point(30, 80)
$instBar.Size = New-Object System.Drawing.Size(570, 28)
$instBar.Style = 'Continuous'
$instBar.Minimum = 0
$instBar.Maximum = 100
$p4.Controls.Add($instBar)

$instPctLabel = New-Object System.Windows.Forms.Label
$instPctLabel.Text = '0%'
$instPctLabel.Location = New-Object System.Drawing.Point(30, 112)
$instPctLabel.Size = New-Object System.Drawing.Size(570, 18)
$instPctLabel.TextAlign = 'MiddleRight'
$instPctLabel.ForeColor = [System.Drawing.Color]::Gray
$p4.Controls.Add($instPctLabel)

# Step-by-step log
$instLog = New-Object System.Windows.Forms.TextBox
$instLog.Multiline = $true
$instLog.ReadOnly = $true
$instLog.ScrollBars = 'Vertical'
$instLog.Location = New-Object System.Drawing.Point(30, 140)
$instLog.Size = New-Object System.Drawing.Size(570, 180)
$instLog.BackColor = [System.Drawing.Color]::FromArgb(20, 20, 20)
$instLog.ForeColor = [System.Drawing.Color]::FromArgb(180, 220, 180)
$instLog.Font = New-Object System.Drawing.Font('Consolas', 8.5)
$p4.Controls.Add($instLog)

function Set-InstallProgress {
    param([int]$Pct, [string]$Step, [string]$Detail = '')
    $instBar.Value = [Math]::Min($Pct, 100)
    $instPctLabel.Text = "$Pct%"
    $instStatus.Text = $Step
    if ($Detail) { $instDetail.Text = $Detail }
    [System.Windows.Forms.Application]::DoEvents()
}

function Add-InstallLog {
    param([string]$Msg)
    $ts = Get-Date -Format 'HH:mm:ss'
    $instLog.AppendText("[$ts] $Msg`r`n")
    Write-Log $Msg
    [System.Windows.Forms.Application]::DoEvents()
}

# ========================== PAGE 5: Complete ==========================
$p5 = New-Page

$doneTitle = New-Object System.Windows.Forms.Label
$doneTitle.Text = 'Installation Complete!'
$doneTitle.Location = New-Object System.Drawing.Point(30, 30)
$doneTitle.AutoSize = $true
$doneTitle.Font = New-Object System.Drawing.Font('Segoe UI', 16, [System.Drawing.FontStyle]::Bold)
$doneTitle.ForeColor = [System.Drawing.Color]::FromArgb(0, 150, 0)
$p5.Controls.Add($doneTitle)

$doneSummary = New-Object System.Windows.Forms.Label
$doneSummary.Text = ''
$doneSummary.Location = New-Object System.Drawing.Point(30, 75)
$doneSummary.Size = New-Object System.Drawing.Size(570, 120)
$p5.Controls.Add($doneSummary)

$launchCheck = New-Object System.Windows.Forms.CheckBox
$launchCheck.Text = 'Launch OpenReach now'
$launchCheck.Checked = $true
$launchCheck.Location = New-Object System.Drawing.Point(30, 210)
$launchCheck.Size = New-Object System.Drawing.Size(300, 22)
$p5.Controls.Add($launchCheck)

$doneNote = New-Object System.Windows.Forms.Label
$doneNote.Text = "You can always start OpenReach from the Desktop shortcut`r`nor by running 'Start OpenReach.bat' in the installation folder."
$doneNote.Location = New-Object System.Drawing.Point(30, 260)
$doneNote.Size = New-Object System.Drawing.Size(570, 40)
$doneNote.ForeColor = [System.Drawing.Color]::Gray
$p5.Controls.Add($doneNote)

# ---------------------------------------------------------------------------
# Installation logic
# ---------------------------------------------------------------------------
function Start-Installation {
    $btnBack.Enabled = $false
    $btnNext.Enabled = $false
    $btnCancel.Text = 'Cancel'

    $tempDir = Join-Path $env:TEMP 'openreach_setup'
    New-Item -ItemType Directory -Path $tempDir -Force -ErrorAction SilentlyContinue | Out-Null

    try {

        # --- Step 1: Install Python if needed (0-20%) ---
        if (-not $script:HasPython) {
            Set-InstallProgress 2 'Installing Python...' 'Downloading Python 3.13 installer'
            Add-InstallLog 'Python 3.11+ not found. Downloading Python 3.13...'

            $pyInstaller = Join-Path $tempDir 'python-3.13.2-amd64.exe'
            $pyUrl = 'https://www.python.org/ftp/python/3.13.2/python-3.13.2-amd64.exe'

            $dlOk = Download-File -Url $pyUrl -OutFile $pyInstaller -Bar $instBar -Status $instDetail
            if (-not $dlOk -or -not (Test-Path $pyInstaller)) {
                Add-InstallLog 'ERROR: Python download failed.'
                throw 'Failed to download Python. Please check your internet connection.'
            }
            Add-InstallLog 'Python downloaded. Running installer (silent)...'
            Set-InstallProgress 10 'Installing Python...' 'Running Python installer (this may take a minute)'

            # Silent install with PATH option
            $pyResult = Run-Process $pyInstaller @('/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_test=0', 'Include_launcher=1') -TimeoutSec 300 -Silent
            if ($pyResult.ExitCode -ne 0) {
                Add-InstallLog "WARNING: Python installer returned code $($pyResult.ExitCode). Trying alternate approach..."
                # Try without quiet for user interaction
                $pyResult2 = Run-Process $pyInstaller @('PrependPath=1', 'Include_test=0') -TimeoutSec 600
                if ($pyResult2.ExitCode -ne 0) {
                    throw 'Python installation failed. Please install Python 3.11+ manually from python.org'
                }
            }

            # Refresh PATH
            $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('PATH', 'User')

            Start-Sleep -Seconds 2
            $pyVer = Find-Python
            if (-not $script:HasPython) {
                # One more attempt: check known locations
                $script:PythonPath = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"
                if (Test-Path $script:PythonPath) {
                    $script:HasPython = $true
                    Add-InstallLog "Found Python at $($script:PythonPath)"
                } else {
                    throw 'Python installed but not found in PATH. Please restart your computer and run the installer again.'
                }
            }
            Add-InstallLog "Python installed: $pyVer"
        } else {
            Add-InstallLog "Python already installed: $($script:PythonPath)"
        }
        Set-InstallProgress 20 'Python ready' ''

        # --- Step 2: Install Ollama if needed (20-35%) ---
        if (-not $script:HasOllama) {
            Set-InstallProgress 22 'Installing Ollama...' 'Downloading Ollama installer'
            Add-InstallLog 'Ollama not found. Downloading...'

            $olInstaller = Join-Path $tempDir 'OllamaSetup.exe'
            $olUrl = 'https://ollama.com/download/OllamaSetup.exe'

            $dlOk = Download-File -Url $olUrl -OutFile $olInstaller -Bar $instBar -Status $instDetail
            if (-not $dlOk -or -not (Test-Path $olInstaller)) {
                throw 'Failed to download Ollama. Please check your internet connection.'
            }

            Add-InstallLog 'Ollama downloaded. Running installer...'
            Set-InstallProgress 28 'Installing Ollama...' 'Running Ollama installer'

            $olResult = Run-Process $olInstaller @('/VERYSILENT', '/NORESTART', '/SUPPRESSMSGBOXES') -TimeoutSec 300 -Silent
            Start-Sleep -Seconds 3

            # Refresh PATH
            $env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' + [System.Environment]::GetEnvironmentVariable('PATH', 'User')

            Find-Ollama | Out-Null
            if (-not $script:HasOllama) {
                $script:OllamaPath = "$env:LOCALAPPDATA\Programs\Ollama\ollama.exe"
                if (Test-Path $script:OllamaPath) {
                    $script:HasOllama = $true
                } else {
                    Add-InstallLog 'WARNING: Ollama installed but not found. Will try to continue.'
                }
            }
            Add-InstallLog 'Ollama installed.'
        } else {
            Add-InstallLog "Ollama already installed: $($script:OllamaPath)"
        }
        Set-InstallProgress 35 'Ollama ready' ''

        # --- Step 3: Download OpenReach (35-50%) ---
        Set-InstallProgress 37 'Downloading OpenReach...' 'Getting project files from GitHub'
        Add-InstallLog 'Downloading OpenReach from GitHub...'

        $installTarget = $script:InstallDir

        if ($script:HasGit) {
            # Clone via git
            if (Test-Path (Join-Path $installTarget '.git')) {
                Add-InstallLog 'OpenReach already cloned. Pulling latest...'
                $pullResult = Run-Process 'git' @('-C', "`"$installTarget`"", 'pull', '--ff-only') -TimeoutSec 120 -Silent
                if ($pullResult.ExitCode -ne 0) {
                    Add-InstallLog 'Git pull failed. Continuing with existing files.'
                }
            } elseif (Test-Path (Join-Path $installTarget 'openreach\__init__.py')) {
                Add-InstallLog 'OpenReach already exists (no git). Skipping download.'
            } else {
                $gitResult = Run-Process 'git' @('clone', 'https://github.com/cormass/openreach.git', "`"$installTarget`"") -TimeoutSec 300 -Silent
                if ($gitResult.ExitCode -ne 0) {
                    Add-InstallLog 'Git clone failed. Falling back to ZIP download...'
                    $script:HasGit = $false
                } else {
                    Add-InstallLog 'Cloned from GitHub.'
                }
            }
        }

        if (-not $script:HasGit) {
            # Download ZIP
            if (Test-Path (Join-Path $installTarget 'openreach\__init__.py')) {
                Add-InstallLog 'OpenReach already exists. Skipping download.'
            } else {
                $zipPath = Join-Path $tempDir 'openreach.zip'
                $zipUrl = 'https://github.com/cormass/openreach/archive/refs/heads/main.zip'

                $dlOk = Download-File -Url $zipUrl -OutFile $zipPath -Bar $instBar -Status $instDetail
                if (-not $dlOk) {
                    throw 'Failed to download OpenReach from GitHub. Check your internet connection.'
                }

                Add-InstallLog 'Extracting...'
                $extractDir = Join-Path $tempDir 'openreach_extract'
                if (Test-Path $extractDir) { Remove-Item $extractDir -Recurse -Force }
                Expand-Archive -Path $zipPath -DestinationPath $extractDir -Force

                # GitHub zips contain a folder like 'openreach-main/', move contents
                $innerDir = Get-ChildItem $extractDir -Directory | Select-Object -First 1
                if ($innerDir) {
                    New-Item -ItemType Directory -Path $installTarget -Force | Out-Null
                    Copy-Item -Path (Join-Path $innerDir.FullName '*') -Destination $installTarget -Recurse -Force
                }
                Add-InstallLog 'OpenReach extracted.'
            }
        }
        Set-InstallProgress 50 'OpenReach downloaded' ''

        # --- Step 4: Create venv and install packages (50-70%) ---
        Set-InstallProgress 52 'Setting up Python environment...' 'Creating virtual environment'
        Add-InstallLog 'Creating Python virtual environment...'

        $venvDir = Join-Path $installTarget '.venv'
        $venvPy = Join-Path $venvDir 'Scripts\python.exe'
        $venvPip = Join-Path $venvDir 'Scripts\pip.exe'

        if (-not (Test-Path $venvPy)) {
            $venvResult = Run-Process $script:PythonPath @('-m', 'venv', "`"$venvDir`"") -TimeoutSec 120 -Silent
            if ($venvResult.ExitCode -ne 0) {
                throw "Failed to create virtual environment. Error: $($venvResult.Stderr)"
            }
        }
        Add-InstallLog 'Virtual environment ready.'

        Set-InstallProgress 55 'Installing Python packages...' 'This may take 2-3 minutes'
        Add-InstallLog 'Installing Python packages...'

        $reqFile = Join-Path $installTarget 'requirements.txt'
        if (Test-Path $reqFile) {
            # Upgrade pip first
            $pipUpResult = Run-Process $venvPy @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip') -TimeoutSec 120 -Silent
            # Install requirements
            $pipResult = Run-Process $venvPip @('install', '--quiet', '-r', "`"$reqFile`"") -TimeoutSec 600 -Silent
            if ($pipResult.ExitCode -ne 0) {
                Add-InstallLog "WARNING: Some packages may have failed to install: $($pipResult.Stderr)"
                Add-InstallLog 'Retrying with verbose output...'
                $pipResult2 = Run-Process $venvPip @('install', '-r', "`"$reqFile`"") -TimeoutSec 600 -Silent
                if ($pipResult2.ExitCode -ne 0) {
                    throw "Failed to install Python packages. Error: $($pipResult2.Stderr)"
                }
            }
            Add-InstallLog 'Python packages installed.'
        } else {
            Add-InstallLog 'WARNING: requirements.txt not found. Skipping package install.'
        }
        Set-InstallProgress 70 'Packages installed' ''

        # --- Step 5: Install Playwright browser (70-80%) ---
        Set-InstallProgress 72 'Installing browser engine...' 'Downloading Chromium (~150 MB)'
        Add-InstallLog 'Installing Playwright Chromium browser...'

        $pwResult = Run-Process $venvPy @('-m', 'playwright', 'install', 'chromium') -TimeoutSec 600 -Silent
        if ($pwResult.ExitCode -ne 0) {
            Add-InstallLog "WARNING: Playwright browser install failed. You can install it later."
            Add-InstallLog "Run: .venv\Scripts\python -m playwright install chromium"
        } else {
            Add-InstallLog 'Playwright Chromium installed.'
        }
        Set-InstallProgress 80 'Browser engine ready' ''

        # --- Step 6: Start Ollama and pull model (80-95%) ---
        Set-InstallProgress 82 'Setting up AI model...' 'Starting Ollama'
        Add-InstallLog "Setting up AI model: $($script:SelectedModel)"

        # Start Ollama if not running
        $ollamaRunning = $false
        try {
            $testReq = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
            $ollamaRunning = ($testReq.StatusCode -eq 200)
        } catch { $ollamaRunning = $false }

        if (-not $ollamaRunning -and $script:HasOllama) {
            Add-InstallLog 'Starting Ollama server...'
            try {
                Start-Process -FilePath $script:OllamaPath -ArgumentList 'serve' -WindowStyle Hidden
                for ($w = 0; $w -lt 15; $w++) {
                    Start-Sleep -Seconds 1
                    try {
                        $testReq = Invoke-WebRequest -Uri 'http://localhost:11434/api/tags' -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
                        if ($testReq.StatusCode -eq 200) { $ollamaRunning = $true; break }
                    } catch {}
                    [System.Windows.Forms.Application]::DoEvents()
                }
            } catch {
                Add-InstallLog "WARNING: Could not start Ollama: $_"
            }
        }

        if ($ollamaRunning) {
            Add-InstallLog "Ollama is running. Pulling model $($script:SelectedModel)..."
            Set-InstallProgress 85 "Downloading AI model ($($script:SelectedModel))..." 'This is the largest download -- may take 5-15 minutes'

            # Pull model using ollama CLI (shows progress in our log via polling)
            $pullJob = Start-Process -FilePath $script:OllamaPath -ArgumentList "pull $($script:SelectedModel)" -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $tempDir 'ollama_pull.log') -RedirectStandardError (Join-Path $tempDir 'ollama_pull_err.log')

            $lastLog = ''
            while (-not $pullJob.HasExited) {
                Start-Sleep -Seconds 2
                [System.Windows.Forms.Application]::DoEvents()
                try {
                    $logContent = Get-Content (Join-Path $tempDir 'ollama_pull.log') -Tail 1 -ErrorAction SilentlyContinue
                    if ($logContent -and $logContent -ne $lastLog) {
                        $lastLog = $logContent
                        $instDetail.Text = $logContent
                        [System.Windows.Forms.Application]::DoEvents()
                    }
                } catch {}

                # Animate progress bar between 85-94
                if ($instBar.Value -lt 94) {
                    $instBar.Value++
                    $instPctLabel.Text = "$($instBar.Value)%"
                }
            }
            if ($pullJob.ExitCode -eq 0) {
                Add-InstallLog "Model $($script:SelectedModel) downloaded successfully."
            } else {
                Add-InstallLog "WARNING: Model pull may have failed (exit code $($pullJob.ExitCode))."
                Add-InstallLog "You can pull it manually later: ollama pull $($script:SelectedModel)"
            }
        } else {
            Add-InstallLog 'WARNING: Ollama is not running. Model download skipped.'
            Add-InstallLog "After installation, start Ollama and run: ollama pull $($script:SelectedModel)"
        }
        Set-InstallProgress 95 'AI model ready' ''

        # --- Step 7: Create desktop shortcut (95-98%) ---
        Set-InstallProgress 96 'Creating shortcut...' ''

        if ($script:CreateShortcut) {
            Add-InstallLog 'Creating desktop shortcut...'
            try {
                $desktopPath = [System.Environment]::GetFolderPath('Desktop')
                $shortcutPath = Join-Path $desktopPath 'OpenReach.lnk'
                $batPath = Join-Path $installTarget 'Start OpenReach.bat'

                $shell = New-Object -ComObject WScript.Shell
                $sc = $shell.CreateShortcut($shortcutPath)
                $sc.TargetPath = $batPath
                $sc.WorkingDirectory = $installTarget
                $sc.Description = 'Launch OpenReach - Social Media Outreach Agent'
                $sc.WindowStyle = 1
                # Try to set icon from Python or default
                $iconPath = Join-Path $installTarget 'installer\openreach.ico'
                if (Test-Path $iconPath) {
                    $sc.IconLocation = $iconPath
                }
                $sc.Save()
                [System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null
                Add-InstallLog "Desktop shortcut created: $shortcutPath"
            } catch {
                Add-InstallLog "WARNING: Could not create desktop shortcut: $_"
            }
        }

        # --- Step 8: Write config marker (98-100%) ---
        Set-InstallProgress 98 'Finalizing...' ''
        Add-InstallLog 'Writing configuration...'

        $configDir = Join-Path $env:USERPROFILE '.openreach'
        New-Item -ItemType Directory -Path $configDir -Force -ErrorAction SilentlyContinue | Out-Null

        # Mark legal acceptance
        $legalFile = Join-Path $configDir '.legal_accepted'
        "accepted=$(Get-Date -Format 'yyyy-MM-ddTHH:mm:ss')" | Out-File $legalFile -Encoding utf8

        # Write default config with selected model
        $configFile = Join-Path $configDir 'config.yaml'
        if (-not (Test-Path $configFile)) {
            @"
llm:
  model: $($script:SelectedModel)
  temperature: 0.7
  base_url: http://localhost:11434

browser:
  headless: false
  slow_mo: 50

outreach:
  delay_min: 45
  delay_max: 180
  daily_limit: 50
  session_limit: 15

ui:
  host: 127.0.0.1
  port: 5000
"@ | Out-File $configFile -Encoding utf8
            Add-InstallLog "Config written to $configFile"
        }

        # Mark deps as installed so Start OpenReach.bat skips setup
        $depsMarker = Join-Path $installTarget '.venv\.deps_installed'
        'done' | Out-File $depsMarker -Encoding utf8 -ErrorAction SilentlyContinue
        $pwMarker = Join-Path $installTarget '.venv\.pw_installed'
        'done' | Out-File $pwMarker -Encoding utf8 -ErrorAction SilentlyContinue

        Set-InstallProgress 100 'Installation complete!' ''
        Add-InstallLog '--- Installation complete! ---'

        # Transition to completion page
        $doneSummary.Text = "OpenReach has been installed successfully.`r`n`r`nInstalled to: $installTarget`r`nAI Model: $($script:SelectedModel)`r`nDesktop Shortcut: $(if ($script:CreateShortcut) { 'Created' } else { 'Skipped' })`r`n`r`nYou can start using OpenReach right away.`r`nJust double-click the desktop shortcut or 'Start OpenReach.bat'."

        $btnNext.Enabled = $true
        $btnNext.Text = 'Finish'
        $btnCancel.Enabled = $false
        Show-Page 5

    } catch {
        $errMsg = $_.Exception.Message
        Add-InstallLog "FATAL ERROR: $errMsg"
        Set-InstallProgress $instBar.Value "Installation failed" $errMsg
        $instStatus.ForeColor = [System.Drawing.Color]::Red

        [System.Windows.Forms.MessageBox]::Show(
            "Installation encountered an error:`n`n$errMsg`n`nCheck the log at:`n$($script:LogFile)`n`nYou can try running the installer again.",
            'OpenReach Setup - Error',
            'OK',
            'Error'
        )
        $btnCancel.Text = 'Close'
        $btnCancel.Enabled = $true
    } finally {
        # Cleanup temp files (keep log)
        try {
            $tempSetup = Join-Path $env:TEMP 'openreach_setup'
            if (Test-Path $tempSetup) {
                Remove-Item $tempSetup -Recurse -Force -ErrorAction SilentlyContinue
            }
        } catch {}
    }
}

# ---------------------------------------------------------------------------
# Navigation logic
# ---------------------------------------------------------------------------
$btnCancel.Add_Click({
    if ($script:CurrentPage -eq 5) {
        $form.Close()
        return
    }
    $result = [System.Windows.Forms.MessageBox]::Show(
        'Are you sure you want to cancel the installation?',
        'OpenReach Setup',
        'YesNo',
        'Question'
    )
    if ($result -eq 'Yes') {
        $script:Cancelled = $true
        $form.Close()
    }
})

$btnBack.Add_Click({
    if ($script:CurrentPage -gt 0 -and $script:CurrentPage -lt 4) {
        Show-Page ($script:CurrentPage - 1)
        # Re-enable Next when going back from license page
        if ($script:CurrentPage -eq 1) {
            $btnNext.Enabled = $licCheck.Checked
        } else {
            $btnNext.Enabled = $true
        }
    }
})

$btnNext.Add_Click({
    switch ($script:CurrentPage) {
        0 {
            # Welcome -> License
            Show-Page 1
            $btnNext.Enabled = $licCheck.Checked
        }
        1 {
            # License -> Options
            Show-Page 2
            $btnNext.Enabled = $true
        }
        2 {
            # Options -> Component Check
            $script:InstallDir = $locBox.Text.Trim()
            $script:CreateShortcut = $scCheck.Checked
            foreach ($rb in $script:ModelRadios) {
                if ($rb.Checked) { $script:SelectedModel = $rb.Tag; break }
            }
            Update-ComponentCheck
            Show-Page 3
            $btnNext.Text = 'Install'
        }
        3 {
            # Component Check -> Installing
            Show-Page 4
            $btnNext.Text = 'Next >'
            Start-Installation
        }
        5 {
            # Complete -> finish
            if ($launchCheck.Checked) {
                $batPath = Join-Path $script:InstallDir 'Start OpenReach.bat'
                if (Test-Path $batPath) {
                    Start-Process -FilePath 'cmd.exe' -ArgumentList "/c `"$batPath`"" -WorkingDirectory $script:InstallDir
                }
            }
            $form.Close()
        }
    }
})

# ---------------------------------------------------------------------------
# Launch
# ---------------------------------------------------------------------------
Write-Log '========== OpenReach Installer Started =========='
Write-Log "OS: $([System.Environment]::OSVersion.VersionString)"
Write-Log "User: $env:USERNAME"

Show-Page 0
$form.Add_Shown({ $form.Activate() })
[void]$form.ShowDialog()
$form.Dispose()

Write-Log '========== Installer Closed =========='
