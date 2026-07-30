# HARVEX TRADING SUITE - DEAD WINDOW DETECTOR + AUTO-RELAUNCH + DUPLICATE CLEANER (FIXED)
# Save as: HARVCORE.ps1

# Load scripts from JSON file
$jsonPath = "C:\xampp\htdocs\harvcore\scripts.json"
$jsonContent = Get-Content -Path $jsonPath -Raw | ConvertFrom-Json
$scripts = $jsonContent.scripts

$pythonExe = "python"
$scriptDir = "C:\xampp\htdocs\harvcore"
$launcherTitle = "HARVCORE TRADING SUITE - CONTROL CENTER"
$switchInterval = 5
$maxRetries = 5
$retryCount = @{}
$processMap = @{}
$deadWindows = @{}  # Track dead windows
$scriptWindowTitles = @{}  # Store actual window titles for each script
$windowDetails = @{}  # Store detailed window info

foreach ($script in $scripts) {
    $retryCount[$script.name] = 0
    $processMap[$script.name] = $null
    $deadWindows[$script.name] = $false
    $scriptWindowTitles[$script.name] = $null
    $windowDetails[$script.name] = $null
}

function Write-Log {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] " + $Message)
}

function Write-Log-Error {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] ERROR " + $Message) -ForegroundColor Red
}

function Write-Log-Success {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] OK " + $Message) -ForegroundColor Green
}

function Write-Log-Warning {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] WARN " + $Message) -ForegroundColor Yellow
}

function Write-Log-Dead {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] DEAD " + $Message) -ForegroundColor Red -BackgroundColor DarkRed
}

function Write-Log-Detail {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] INFO " + $Message) -ForegroundColor Cyan
}

function Write-Log-Duplicate {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] DUPLICATE " + $Message) -ForegroundColor Yellow -BackgroundColor DarkRed
}

function Get-All-Windows {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;

public class WindowEnumerator {
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    
    [DllImport("user32.dll")]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    
    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hWnd);
    
    [DllImport("user32.dll")]
    public static extern int GetWindowTextLength(IntPtr hWnd);
    
    [DllImport("user32.dll")]
    public static extern bool IsWindowEnabled(IntPtr hWnd);
    
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    
    public static System.Collections.Generic.List<WindowInfo> GetAllWindows() {
        var windows = new System.Collections.Generic.List<WindowInfo>();
        
        EnumWindows((hwnd, lParam) => {
            if (!IsWindowVisible(hwnd) || !IsWindow(hwnd)) {
                return true;
            }
            
            int length = GetWindowTextLength(hwnd);
            if (length == 0) {
                return true;
            }
            
            StringBuilder sb = new StringBuilder(length + 1);
            GetWindowText(hwnd, sb, sb.Capacity);
            string windowTitle = sb.ToString();
            
            if (!string.IsNullOrEmpty(windowTitle)) {
                uint pid;
                GetWindowThreadProcessId(hwnd, out pid);
                
                windows.Add(new WindowInfo {
                    HWND = hwnd,
                    Title = windowTitle,
                    PID = pid,
                    IsEnabled = IsWindowEnabled(hwnd)
                });
            }
            return true;
        }, IntPtr.Zero);
        
        return windows;
    }
}

public class WindowInfo {
    public IntPtr HWND { get; set; }
    public string Title { get; set; }
    public uint PID { get; set; }
    public bool IsEnabled { get; set; }
    
    public override string ToString() {
        return string.Format("PID: {0}, Title: {1}, Enabled: {2}", PID, Title, IsEnabled);
    }
}
"@ -Language CSharp -ErrorAction SilentlyContinue
    
    try {
        $windows = [WindowEnumerator]::GetAllWindows()
        return $windows
    } catch {
        Write-Log-Error "Failed to get windows: $_"
        return @()
    }
}

function Is-Window-Match {
    param([string]$WindowTitle, [string]$ScriptName)
    
    # Exact match for dead window
    if ($WindowTitle -match "^$ScriptName\s*$") {
        return "dead"
    }
    
    # Active window - starts with script name and contains python/path
    if ($WindowTitle -match "^$ScriptName\s+-") {
        return "active"
    }
    
    return "none"
}

function Get-Window-Details {
    param([string]$ScriptName)
    
    $windows = Get-All-Windows
    $details = @{
        Found = $false
        WindowTitle = ""
        PID = 0
        ProcessName = ""
        ProcessResponding = $false
        ProcessCPU = 0
        ProcessMemory = 0
        WindowEnabled = $false
        DetectionMethod = ""
        DeadWindowPID = 0
        DeadWindowTitle = ""
        DeadWindowHWND = 0
        DuplicateWindows = @()
    }
    
    $foundActive = $false
    $foundDead = $false
    $activeWindows = @()
    
    foreach ($win in $windows) {
        $title = $win.Title
        $match = Is-Window-Match -WindowTitle $title -ScriptName $ScriptName
        
        if ($match -eq "active") {
            $foundActive = $true
            $activeWindows += $win
            $details.Found = $true
            $details.WindowTitle = $title
            $details.PID = $win.PID
            $details.WindowEnabled = $win.IsEnabled
            $details.DetectionMethod = "Active window with Python/command"
            
            try {
                $proc = Get-Process -Id $win.PID -ErrorAction Stop
                $details.ProcessName = $proc.ProcessName
                $details.ProcessResponding = $proc.Responding
                $details.ProcessCPU = [math]::Round($proc.CPU, 2)
                $details.ProcessMemory = [math]::Round($proc.WorkingSet64 / 1MB, 2)
            } catch {
                $details.ProcessResponding = $false
            }
        }
        
        if ($match -eq "dead") {
            $foundDead = $true
            $details.DeadWindowPID = $win.PID
            $details.DeadWindowTitle = $title
            $details.DeadWindowHWND = $win.HWND
        }
    }
    
    # Store duplicate windows (more than 1 active window)
    if ($activeWindows.Count -gt 1) {
        $details.DuplicateWindows = $activeWindows
        $details.DetectionMethod = "DUPLICATE WINDOWS DETECTED - $($activeWindows.Count) instances"
    }
    
    # If we found a dead window but no active window, it's truly dead
    if ($foundDead -and -not $foundActive) {
        $details.Found = $false
        $details.DetectionMethod = "DEAD WINDOW - No command/process"
        $details.PID = $details.DeadWindowPID
        $details.WindowTitle = $details.DeadWindowTitle
        return $details
    }
    
    # If we found both active and dead, the dead one needs to be cleaned up
    if ($foundDead -and $foundActive) {
        $details.DetectionMethod = "DEAD WINDOW DETECTED - Will be cleaned up"
        return $details
    }
    
    return $details
}

function Close-Window-By-Handle {
    param([IntPtr]$WindowHandle, [string]$WindowTitle)
    
    if ($WindowHandle -eq [IntPtr]::Zero) {
        return $false
    }
    
    try {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public class WindowCloser {
    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern bool CloseWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool DestroyWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool IsWindow(IntPtr hWnd);
    
    public const uint WM_CLOSE = 0x0010;
    public const uint WM_QUIT = 0x0012;
    public const uint WM_DESTROY = 0x0002;
    
    public static bool CloseWindowByHandle(IntPtr hWnd) {
        if (!IsWindow(hWnd)) {
            return false;
        }
        PostMessage(hWnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
        System.Threading.Thread.Sleep(200);
        SendMessage(hWnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
        System.Threading.Thread.Sleep(200);
        CloseWindow(hWnd);
        System.Threading.Thread.Sleep(200);
        if (IsWindow(hWnd)) {
            DestroyWindow(hWnd);
        }
        return true;
    }
}
"@ -Language CSharp -ErrorAction SilentlyContinue
        
        return [WindowCloser]::CloseWindowByHandle($WindowHandle)
    } catch {
        Write-Log-Warning "Failed to close window by handle: $_"
        return $false
    }
}

function Close-Dead-Window {
    param([string]$ScriptName, [int]$ProcessId, [IntPtr]$WindowHandle)
    
    Write-Log-Warning "Closing dead window for $ScriptName (PID: $ProcessId)"
    
    # METHOD 1: Try to close by sending WM_CLOSE to the specific window handle
    if ($WindowHandle -ne [IntPtr]::Zero) {
        $result = Close-Window-By-Handle -WindowHandle $WindowHandle -WindowTitle $ScriptName
        if ($result) {
            Write-Log-Success "Closed dead window via window handle"
            Start-Sleep -Seconds 1
            return $true
        }
    }
    
    # METHOD 2: Try to close by window title using taskkill
    try {
        $result = taskkill /F /FI "WINDOWTITLE eq $ScriptName" 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Log-Success "Closed dead window via taskkill by title"
            Start-Sleep -Seconds 1
            return $true
        }
    } catch {
        Write-Log-Warning "taskkill by title failed: $_"
    }
    
    # METHOD 3: Try to close by PID only if it's NOT the main process
    if ($ProcessId -gt 0) {
        try {
            $proc = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
            if ($proc -and $proc.ProcessName -ne "powershell" -and $proc.ProcessName -ne "cmd") {
                $proc.CloseMainWindow() | Out-Null
                Start-Sleep -Milliseconds 500
                if (-not $proc.HasExited) {
                    $proc.Kill() | Out-Null
                }
                Write-Log-Success "Killed dead window process (PID: $ProcessId)"
                Start-Sleep -Seconds 1
                return $true
            }
        } catch {
            Write-Log-Warning "Could not kill process by PID: $_"
        }
    }
    
    Write-Log-Error "Could not close dead window: $ScriptName"
    return $false
}

function Detect-And-Fix-Duplicate-Windows {
    Write-Log "Scanning for duplicate windows..."
    
    $windows = Get-All-Windows
    $duplicatesFound = @()
    $fixedCount = 0
    
    foreach ($script in $scripts) {
        $scriptName = $script.name
        $activeWindows = @()
        $deadWindowsList = @()
        
        # Find all windows for this script using exact matching
        foreach ($win in $windows) {
            $title = $win.Title
            $match = Is-Window-Match -WindowTitle $title -ScriptName $scriptName
            
            if ($match -eq "active") {
                $activeWindows += $win
            }
            
            if ($match -eq "dead") {
                $deadWindowsList += $win
            }
        }
        
        # Check for duplicates (more than 1 active window)
        if ($activeWindows.Count -gt 1) {
            Write-Log-Duplicate "DUPLICATE WINDOWS: Found $($activeWindows.Count) instances of $scriptName"
            
            # Keep the first one, close the rest
            $keepWindow = $activeWindows[0]
            $closeWindows = $activeWindows | Select-Object -Skip 1
            
            foreach ($closeWin in $closeWindows) {
                Write-Log-Warning "Closing duplicate window: '$($closeWin.Title)' (PID: $($closeWin.PID))"
                $result = Close-Window-By-Handle -WindowHandle $closeWin.HWND -WindowTitle $scriptName
                if ($result) {
                    Write-Log-Success "Closed duplicate window"
                    $fixedCount++
                } else {
                    # Try taskkill by title and PID
                    try {
                        taskkill /F /PID $closeWin.PID 2>&1 | Out-Null
                        Write-Log-Success "Killed duplicate window (PID: $($closeWin.PID))"
                        $fixedCount++
                    } catch {
                        Write-Log-Warning "Could not close duplicate window"
                    }
                }
            }
            
            $duplicatesFound += @{
                Name = $scriptName
                Count = $activeWindows.Count
                KeptPID = $keepWindow.PID
                ClosedPIDs = ($closeWindows | ForEach-Object { $_.PID })
            }
            
            # Reset dead window status since we cleaned up
            $deadWindows[$scriptName] = $false
        }
        
        # Also clean up dead windows if they exist alongside active windows
        if ($deadWindowsList.Count -gt 0 -and $activeWindows.Count -gt 0) {
            foreach ($deadWin in $deadWindowsList) {
                Write-Log-Warning "Cleaning up dead window: '$($deadWin.Title)' (PID: $($deadWin.PID))"
                Close-Dead-Window -ScriptName $scriptName -ProcessId $deadWin.PID -WindowHandle $deadWin.HWND
                $fixedCount++
            }
        }
    }
    
    if ($duplicatesFound.Count -gt 0) {
        Write-Log ""
        Write-Log "============================================" -ForegroundColor Yellow
        Write-Log "  DUPLICATE WINDOWS CLEANED UP" -ForegroundColor Yellow -BackgroundColor DarkRed
        Write-Log "============================================" -ForegroundColor Yellow
        foreach ($dup in $duplicatesFound) {
            Write-Log-Duplicate "  $($dup.Name) - $($dup.Count) instances found, kept PID: $($dup.KeptPID)"
        }
        Write-Log "============================================" -ForegroundColor Yellow
        Write-Log ""
        Write-Log-Success "Fixed $fixedCount duplicate/dead windows"
        Write-Log ""
    } else {
        Write-Log-Success "No duplicate windows detected"
    }
    
    return $duplicatesFound
}

function Detect-And-Fix-Dead-Windows {
    Write-Log "Scanning for dead windows..."
    
    $windows = Get-All-Windows
    $deadFound = @()
    $fixedCount = 0
    
    foreach ($script in $scripts) {
        $scriptName = $script.name
        $foundActive = $false
        $foundDead = $false
        $deadPID = 0
        $deadTitle = ""
        $deadHWND = [IntPtr]::Zero
        
        # First pass - find active and dead windows using exact matching
        foreach ($win in $windows) {
            $title = $win.Title
            $match = Is-Window-Match -WindowTitle $title -ScriptName $scriptName
            
            if ($match -eq "active") {
                $foundActive = $true
                $scriptWindowTitles[$scriptName] = $title
                Write-Log-Success "Found active window: '$title' (PID: $($win.PID))"
            }
            
            if ($match -eq "dead") {
                $foundDead = $true
                $deadPID = $win.PID
                $deadTitle = $title
                $deadHWND = $win.HWND
                Write-Log-Dead "Found dead window: '$title' (PID: $($win.PID))"
            }
        }
        
        # Handle dead windows
        if ($foundDead -and -not $foundActive) {
            # Truly dead - need to clean up and relaunch
            Write-Log-Dead "DEAD WINDOW: $scriptName - No active window found, cleaning up..."
            $closed = Close-Dead-Window -ScriptName $scriptName -ProcessId $deadPID -WindowHandle $deadHWND
            if ($closed) {
                Write-Log-Success "Successfully cleaned up dead window"
            } else {
                Write-Log-Warning "Could not clean up dead window, may need manual intervention"
            }
            
            $deadFound += @{
                Name = $scriptName
                PID = $deadPID
                Title = $deadTitle
                Reason = "Dead window - no command line"
            }
            $deadWindows[$scriptName] = $true
            $fixedCount++
            
            # Launch new instance
            Write-Log "Launching new instance of $scriptName..."
            Launch-Script -ScriptName $scriptName -ScriptPath $script.path
            Start-Sleep -Seconds 2
            $deadWindows[$scriptName] = $false
            Write-Log-Success "New instance of $scriptName launched"
            
        } elseif ($foundDead -and $foundActive) {
            # Dead window exists but active window also exists - just clean up the dead one
            Write-Log-Warning "Dead window detected for $scriptName but active window exists - cleaning up dead window"
            $closed = Close-Dead-Window -ScriptName $scriptName -ProcessId $deadPID -WindowHandle $deadHWND
            if ($closed) {
                Write-Log-Success "Successfully cleaned up dead window"
            } else {
                Write-Log-Warning "Could not clean up dead window, may need manual intervention"
            }
            
            $deadFound += @{
                Name = $scriptName
                PID = $deadPID
                Title = $deadTitle
                Reason = "Dead window - active window also exists"
            }
            $fixedCount++
            $deadWindows[$scriptName] = $false
            
        } elseif (-not $foundActive -and -not $foundDead) {
            # No window at all - launch new
            Write-Log-Warning "No window found for $scriptName - launching new instance"
            Launch-Script -ScriptName $scriptName -ScriptPath $script.path
            Start-Sleep -Seconds 2
            $deadWindows[$scriptName] = $false
        } else {
            # All good - window is active
            $deadWindows[$scriptName] = $false
        }
    }
    
    if ($deadFound.Count -gt 0) {
        Write-Log ""
        Write-Log "============================================" -ForegroundColor Red
        Write-Log "  DEAD WINDOWS CLEANED UP" -ForegroundColor Red -BackgroundColor DarkRed
        Write-Log "============================================" -ForegroundColor Red
        foreach ($dead in $deadFound) {
            Write-Log-Dead "  $($dead.Name) (PID: $($dead.PID)) - $($dead.Reason) - CLEANED UP"
        }
        Write-Log "============================================" -ForegroundColor Red
        Write-Log ""
        Write-Log-Success "Fixed $fixedCount dead windows"
        Write-Log ""
    } else {
        Write-Log-Success "No dead windows detected"
    }
    
    return $deadFound
}

function Detect-Existing-Windows {
    Write-Log "Scanning for existing windows..."
    
    $windows = Get-All-Windows
    $foundWindows = @()
    
    # Simple approach - check each script and find its window using exact matching
    foreach ($script in $scripts) {
        $scriptName = $script.name
        $found = $false
        
        foreach ($win in $windows) {
            $title = $win.Title
            # Skip launcher window
            if ($title -like "*$launcherTitle*") {
                continue
            }
            
            $match = Is-Window-Match -WindowTitle $title -ScriptName $scriptName
            
            # Check if this is an active window for this script
            if ($match -eq "active") {
                Write-Log-Success "Found active window: '$title' (PID: $($win.PID))"
                $foundWindows += @{
                    Name = $script.name
                    PID = $win.PID
                    Process = (Get-Process -Id $win.PID -ErrorAction SilentlyContinue)
                    HWND = $win.HWND
                    Title = $title
                    IsEnabled = $win.IsEnabled
                }
                $processMap[$script.name] = (Get-Process -Id $win.PID -ErrorAction SilentlyContinue)
                $scriptWindowTitles[$script.name] = $title
                $found = $true
                break
            }
        }
        
        if (-not $found) {
            Write-Log-Warning "No active window found for: $scriptName"
        }
    }
    
    # Log what was found
    Write-Log "Found $($foundWindows.Count) active windows"
    foreach ($found in $foundWindows) {
        Write-Log "  - $($found.Name) (PID: $($found.PID))"
    }
    
    return $foundWindows
}

function Launch-Script {
    param([string]$ScriptName, [string]$ScriptPath)
    
    Write-Log "Launching $ScriptName..."
    
    $cmdCommand = "title $ScriptName & cd /d `"$scriptDir`" & echo ======================================== & echo   $ScriptName & echo ======================================== & echo. & $pythonExe `"$ScriptPath`""
    
    try {
        $process = Start-Process -FilePath "cmd.exe" -ArgumentList "/k $cmdCommand" -WindowStyle Normal -PassThru
        Write-Log-Success "$ScriptName launched (PID: $($process.Id))"
        $processMap[$ScriptName] = $process
        $deadWindows[$ScriptName] = $false
        return $process
    } catch {
        Write-Log-Error "ERROR launching $ScriptName : $_"
        return $null
    }
}

function Maximize-Window {
    param([string]$WindowTitle)
    
    $code = @"
using System;
using System.Runtime.InteropServices;

public class WindowManager {
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    
    [DllImport("user32.dll")]
    public static extern int GetWindowPlacement(IntPtr hWnd, ref WINDOWPLACEMENT lpwndpl);
    
    [DllImport("user32.dll")]
    public static extern bool IsZoomed(IntPtr hWnd);
    
    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    
    [DllImport("user32.dll")]
    public static extern int GetWindowText(IntPtr hWnd, System.Text.StringBuilder lpString, int nMaxCount);
    
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    
    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);
    
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    
    public struct RECT {
        public int Left;
        public int Top;
        public int Right;
        public int Bottom;
    }
    
    public struct WINDOWPLACEMENT {
        public int length;
        public int flags;
        public int showCmd;
        public POINT ptMinPosition;
        public POINT ptMaxPosition;
        public RECT rcNormalPosition;
    }
    
    public struct POINT {
        public int X;
        public int Y;
    }
    
    public const int SW_MAXIMIZE = 3;
    public const int SW_RESTORE = 9;
    public const int SW_SHOW = 5;
    
    public static IntPtr FindWindowByTitle(string title) {
        IntPtr foundHwnd = IntPtr.Zero;
        EnumWindows((hwnd, lParam) => {
            if (!IsWindowVisible(hwnd)) {
                return true;
            }
            System.Text.StringBuilder sb = new System.Text.StringBuilder(256);
            GetWindowText(hwnd, sb, 256);
            string windowTitle = sb.ToString();
            if (!string.IsNullOrEmpty(windowTitle) && windowTitle.Contains(title)) {
                foundHwnd = hwnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return foundHwnd;
    }
    
    public static bool IsWindowMaximized(IntPtr hWnd) {
        return IsZoomed(hWnd);
    }
    
    public static bool MaximizeAndFocusWindow(IntPtr hWnd) {
        try {
            WINDOWPLACEMENT placement = new WINDOWPLACEMENT();
            placement.length = Marshal.SizeOf(placement);
            GetWindowPlacement(hWnd, ref placement);
            
            if (placement.showCmd == 2) {
                ShowWindow(hWnd, SW_RESTORE);
                System.Threading.Thread.Sleep(50);
            }
            
            if (!IsZoomed(hWnd)) {
                ShowWindow(hWnd, SW_MAXIMIZE);
                System.Threading.Thread.Sleep(50);
            }
            
            SetForegroundWindow(hWnd);
            System.Threading.Thread.Sleep(50);
            
            return true;
        } catch {
            return false;
        }
    }
}
"@
    
    Add-Type -TypeDefinition $code -ErrorAction SilentlyContinue
    
    try {
        $hwnd = [WindowManager]::FindWindowByTitle($WindowTitle)
        
        if ($hwnd -ne [IntPtr]::Zero) {
            $result = [WindowManager]::MaximizeAndFocusWindow($hwnd)
            if ($result) {
                return $true
            }
        }
        return $false
    } catch {
        return $false
    }
}

function Focus-Window {
    param([string]$WindowTitle)
    
    # Skip if window is marked as dead
    if ($deadWindows[$WindowTitle] -eq $true) {
        Write-Log-Warning "Skipping focus on dead window: $WindowTitle"
        return $false
    }
    
    $maximized = Maximize-Window -WindowTitle $WindowTitle
    
    if ($maximized) {
        return $true
    }
    
    $wshell = New-Object -ComObject wscript.shell
    if ($wshell.AppActivate($WindowTitle)) {
        return $true
    }
    
    return $false
}

function Show-Window-Details {
    param([string]$ScriptName)
    
    $details = Get-Window-Details -ScriptName $ScriptName
    
    Write-Log "----------------------------------------"
    Write-Log "DETECTION DETAILS: $ScriptName"
    Write-Log "----------------------------------------"
    
    if ($details.Found) {
        Write-Log-Success "  STATUS: RUNNING"
        Write-Log-Detail "  Detection Method: $($details.DetectionMethod)"
        Write-Log-Detail "  Window Title: $($details.WindowTitle)"
        Write-Log-Detail "  PID: $($details.PID)"
        Write-Log-Detail "  Process: $($details.ProcessName)"
        Write-Log-Detail "  Responding: $($details.ProcessResponding)"
        Write-Log-Detail "  CPU Usage: $($details.ProcessCPU)%"
        Write-Log-Detail "  Memory: $($details.ProcessMemory) MB"
        Write-Log-Detail "  Window Enabled: $($details.WindowEnabled)"
        
        if ($details.DuplicateWindows.Count -gt 0) {
            Write-Log-Duplicate "  DUPLICATE DETECTED: $($details.DuplicateWindows.Count) instances"
            foreach ($dup in $details.DuplicateWindows) {
                Write-Log-Duplicate "    - PID: $($dup.PID), Title: $($dup.Title)"
            }
        }
    } else {
        Write-Log-Error "  STATUS: NOT RUNNING"
        Write-Log-Detail "  Detection Method: $($details.DetectionMethod)"
        if ($details.DeadWindowPID -gt 0) {
            Write-Log-Detail "  Dead Window PID: $($details.DeadWindowPID)"
            Write-Log-Detail "  Dead Window Title: $($details.DeadWindowTitle)"
        }
    }
    
    Write-Log "----------------------------------------"
}

# Main execution - NO PROMPTS
Write-Log "============================================================"
Write-Log "  HARVCORE - DEAD WINDOW DETECTOR + AUTO-RELAUNCH + DUPLICATE CLEANER"
Write-Log "============================================================"
Write-Log ""

# First, detect and fix dead windows
Write-Log "STEP 1: Detecting and fixing dead windows..."
$deadWindowsList = Detect-And-Fix-Dead-Windows

Write-Log ""
Write-Log "STEP 2: Detecting and fixing duplicate windows..."
$duplicateWindowsList = Detect-And-Fix-Duplicate-Windows

Write-Log ""
Write-Log "STEP 3: Detecting existing windows..."
$existingWindows = Detect-Existing-Windows

# Launch any missing scripts
if ($existingWindows.Count -gt 0) {
    Write-Log-Success "Found $($existingWindows.Count) existing windows"
    
    foreach ($script in $scripts) {
        $found = $false
        foreach ($existing in $existingWindows) {
            if ($existing.Name -eq $script.name) {
                $found = $true
                Write-Log "Using existing window for $($script.name) (PID: $($existing.PID))"
                break
            }
        }
        
        if (-not $found) {
            Write-Log "$($script.name) not found - launching new instance"
            Launch-Script -ScriptName $script.name -ScriptPath $script.path
            Start-Sleep -Seconds 2
        }
    }
} else {
    Write-Log "No existing windows found - launching all components..."
    foreach ($script in $scripts) {
        Launch-Script -ScriptName $script.name -ScriptPath $script.path
        Start-Sleep -Seconds 2
    }
}

Write-Log ""
Write-Log "All components ready!"
Write-Log "Monitoring for crashes, duplicates, and auto-relaunching..."
Write-Log "Switching windows every $switchInterval seconds"
Write-Log "Max retries per script: $maxRetries"
Write-Log ""
Write-Log "Press Ctrl+C to stop"
Write-Log ""

$cycleCount = 0
$healthCheckInterval = 6  # Check for dead windows every 6 cycles
$duplicateCheckInterval = 12  # Check for duplicates every 12 cycles

while ($true) {
    $cycleCount++
    
    # Run dead window detection and fixing periodically
    if ($cycleCount % $healthCheckInterval -eq 0) {
        Write-Log "Running dead window detection and cleanup..."
        $deadFound = Detect-And-Fix-Dead-Windows
    }
    
    # Run duplicate detection and fixing periodically (less frequently)
    if ($cycleCount % $duplicateCheckInterval -eq 0) {
        Write-Log "Running duplicate window detection and cleanup..."
        $duplicateFound = Detect-And-Fix-Duplicate-Windows
    }
    
    foreach ($script in $scripts) {
        $scriptName = $script.name
        
        # Show detailed detection info for this script
        Show-Window-Details -ScriptName $scriptName
        
        # Skip dead windows when focusing
        if ($deadWindows[$scriptName] -eq $true) {
            Write-Log "Skipping focus: $scriptName (marked as dead)"
            continue
        }
        
        Write-Log "Focusing: $scriptName"
        $focused = Focus-Window -WindowTitle $scriptName
        
        if ($focused) {
            Write-Log-Success "  Window focused successfully"
        } else {
            Write-Log-Warning "  Could not focus window"
        }
        
        Write-Log "  Waiting $switchInterval seconds..."
        Start-Sleep -Seconds $switchInterval
        Write-Log ""
    }
    
    # Focus launcher with details
    Write-Log "Focusing: LAUNCHER"
    $focused = Maximize-Window -WindowTitle $launcherTitle
    
    $wshell = New-Object -ComObject wscript.shell
    if ($wshell.AppActivate($launcherTitle)) {
        Write-Log-Success "  LAUNCHER - Focused"
    } else {
        Write-Log-Warning "  LAUNCHER - Not found"
    }
    Write-Log "  Waiting $switchInterval seconds..."
    Start-Sleep -Seconds $switchInterval
    Write-Log ""
}