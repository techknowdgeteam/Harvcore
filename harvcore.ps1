# HARVEX TRADING SUITE - LAUNCH ONCE + FOCUS ROTATOR WITH MAXIMIZE (FAST)
# Save as: HARVCORE.ps1

$scripts = @(
    @{ Name = "MARKET ANALYSIS"; Path = "C:\xampp\htdocs\harvcore\harvox\invharv\analysis.py" },
    @{ Name = "INVHARV"; Path = "C:\xampp\htdocs\harvcore\harvox\invharv\Invharv.py" },
    @{ Name = "SCREEN_AWAKE"; Path = "C:\xampp\htdocs\harvcore\harvox\invharv\screen_awake.py" },
    @{ Name = "HARVHUB"; Path = "C:\xampp\htdocs\harvcore\harvox\harvhub\harvhub.py" },
    @{ Name = "COMMUNICATOR"; Path = "C:\xampp\htdocs\harvcore\harvox\invharv\communicator.py" }
)

$pythonExe = "python"
$scriptDir = "C:\xampp\htdocs\harvcore"
$launcherTitle = "HARVCORE TRADING SUITE - CONTROL CENTER"
$switchInterval = 5  # Seconds between window switches (FAST)

function Write-Log {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] " + $Message)
}

function Launch-Script {
    param([string]$ScriptName, [string]$ScriptPath)
    
    Write-Log "Launching $ScriptName..."
    $cmdCommand = "title $ScriptName && cd /d `"$scriptDir`" && echo ======================================== && echo   $ScriptName && echo ======================================== && echo. && $pythonExe `"$ScriptPath`""
    
    try {
        Start-Process -FilePath "cmd.exe" -ArgumentList "/k $cmdCommand" -WindowStyle Normal
        Write-Log "  ✅ $ScriptName launched"
        return $true
    } catch {
        Write-Log "  ❌ ERROR launching $ScriptName : $_"
        return $false
    }
}

function Maximize-Window {
    param([string]$WindowTitle)
    
    Add-Type -TypeDefinition @"
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
            // If window is minimized, restore it first
            WINDOWPLACEMENT placement = new WINDOWPLACEMENT();
            placement.length = Marshal.SizeOf(placement);
            GetWindowPlacement(hWnd, ref placement);
            
            if (placement.showCmd == 2) { // SW_SHOWMINIMIZED
                ShowWindow(hWnd, SW_RESTORE);
                System.Threading.Thread.Sleep(50);
            }
            
            // Check if already maximized
            if (!IsZoomed(hWnd)) {
                ShowWindow(hWnd, SW_MAXIMIZE);
                System.Threading.Thread.Sleep(50);
            }
            
            // Bring to foreground
            SetForegroundWindow(hWnd);
            System.Threading.Thread.Sleep(50);
            
            return true;
        } catch {
            return false;
        }
    }
}
"@ -Language CSharp -ErrorAction SilentlyContinue
    
    try {
        # Find the window by title
        $hwnd = [WindowManager]::FindWindowByTitle($WindowTitle)
        
        if ($hwnd -ne [IntPtr]::Zero) {
            # Fast maximize and focus
            $result = [WindowManager]::MaximizeAndFocusWindow($hwnd)
            
            if ($result) {
                Write-Host "  ✅ $WindowTitle - Maximized & Focused" -ForegroundColor Green
                return $true
            } else {
                Write-Host "  ⚠️ $WindowTitle - Operation failed" -ForegroundColor Yellow
                return $false
            }
        }
        
        Write-Host "  ⚠️ $WindowTitle - Window not found" -ForegroundColor Yellow
        return $false
    } catch {
        Write-Host "  ⚠️ $WindowTitle - Error: $_" -ForegroundColor Yellow
        return $false
    }
}

function Focus-Window {
    param([string]$WindowTitle)
    
    # Try to maximize and focus
    $maximized = Maximize-Window -WindowTitle $WindowTitle
    
    if ($maximized) {
        return $true
    }
    
    # Fallback: Try to focus using COM (faster)
    $wshell = New-Object -ComObject wscript.shell
    if ($wshell.AppActivate($WindowTitle)) {
        Write-Host "  ✅ $WindowTitle - Focused (COM)" -ForegroundColor Green
        return $true
    }
    
    Write-Host "  ⚠️ $WindowTitle - Not found" -ForegroundColor Yellow
    return $false
}

# Main execution
Write-Log "============================================================"
Write-Log "  🎯 HARVCORE - FAST FOCUS ROTATOR WITH MAXIMIZE"
Write-Log "============================================================"
Write-Log ""

# LAUNCH ALL SCRIPTS ONCE
Write-Log "LAUNCHING all components (ONLY ONCE)..."
Write-Log ""

foreach ($script in $scripts) {
    Launch-Script -ScriptName $script.Name -ScriptPath $script.Path
    Start-Sleep -Seconds 1  # Reduced from 2 to 1 second
}

Write-Log ""
Write-Log "All components launched!"
Write-Log "Switching windows every $switchInterval seconds"
Write-Log ""
Write-Log "Press Ctrl+C to stop"
Write-Log ""

# FOCUS ROTATOR - FAST SWITCHING
while ($true) {
    foreach ($script in $scripts) {
        Write-Log "Focusing: $($script.Name)"
        Focus-Window -WindowTitle $script.Name
        Write-Log "  Waiting $switchInterval seconds..."
        Start-Sleep -Seconds $switchInterval
        Write-Log ""
    }
    
    Write-Log "Focusing: LAUNCHER"
    Maximize-Window -WindowTitle $launcherTitle
    
    $wshell = New-Object -ComObject wscript.shell
    if ($wshell.AppActivate($launcherTitle)) {
        Write-Host "  ✅ LAUNCHER - Focused" -ForegroundColor Green
    } else {
        Write-Host "  ⚠️ LAUNCHER - Not found" -ForegroundColor Yellow
    }
    Write-Log "  Waiting $switchInterval seconds..."
    Start-Sleep -Seconds $switchInterval
    Write-Log ""
}