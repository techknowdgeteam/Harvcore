# Admin elevation removed - script runs with current user privileges

$firstLoop = $true
$initialKeysSent = $false
$terminalsLaunched = $false

function Write-Log {
    param([string]$Message)
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] " + $Message)
}

function SendInitialKeys {
    Write-Log "Sending initial setup keys to VS Code..."
    
    $wshell = New-Object -ComObject wscript.shell
    $windowTitles = @(
        'Visual Studio Code [Administrator]',
        'Visual Studio Code',
        'Code'
    )
    
    # Try to activate VS Code window
    $activated = $false
    foreach ($title in $windowTitles) {
        Write-Log "  Trying to activate: '$title'"
        if ($wshell.AppActivate($title)) {
            $activated = $true
            Write-Log "  Activated with title: '$title'"
            break
        }
        Start-Sleep -Milliseconds 200
    }
    
    if (-not $activated) {
        Write-Log "  Could not activate VS Code, trying Alt+Tab..."
        $wshell.SendKeys('%{TAB}')
        Start-Sleep -Milliseconds 500
        for ($i = 1; $i -le 10; $i++) {
            $wshell.SendKeys('%{TAB}')
            Start-Sleep -Milliseconds 200
            foreach ($title in $windowTitles) {
                if ($wshell.AppActivate($title)) {
                    $activated = $true
                    Write-Log "  Activated via Alt+Tab (attempt $i)"
                    break
                }
            }
            if ($activated) { break }
        }
    }
    
    if (-not $activated) {
        Write-Log "  WARNING: Could not activate VS Code window"
        return $false
    }
    
    # Wait for VS Code to be ready
    Start-Sleep -Milliseconds 1000
    
    # KEY 1: Ctrl+Shift+B - Build/Compile
    Write-Log "  Sending Ctrl+Shift+B..."
    $wshell.SendKeys('^+{b}')
    Start-Sleep -Milliseconds 800
    
    # KEY 2: Ctrl+Alt+I - Toggle Chat panel (close it)
    Write-Log "  Sending Ctrl+Alt+I (Close Chat)..."
    $wshell.SendKeys('^%{i}')
    Start-Sleep -Milliseconds 800
    
    # KEY 3: Try multiple methods to close secondary panel
    Write-Log "  Trying to close Secondary Panel..."
    
    # Method A: Ctrl+Alt+B (standard)
    Write-Log "    Method A: Ctrl+Alt+B"
    $wshell.SendKeys('^%{b}')
    Start-Sleep -Milliseconds 800
    
    # Method B: Ctrl+Shift+E (Explorer toggle)
    Write-Log "    Method B: Ctrl+Shift+E (Toggle Explorer)"
    $wshell.SendKeys('^+{e}')
    Start-Sleep -Milliseconds 800
    
    # Method C: Ctrl+B (Toggle Sidebar)
    Write-Log "    Method C: Ctrl+B (Toggle Sidebar)"
    $wshell.SendKeys('^{b}')
    Start-Sleep -Milliseconds 800
    
    Write-Log "  Initial setup keys sent successfully"
    return $true
}

function SendCtrlShiftB {
    Write-Log "Sending Ctrl+Shift+B to VS Code..."
    
    $wshell = New-Object -ComObject wscript.shell
    $windowTitles = @(
        'Visual Studio Code [Administrator]',
        'Visual Studio Code',
        'Code'
    )
    
    # Try to activate VS Code window
    $activated = $false
    foreach ($title in $windowTitles) {
        if ($wshell.AppActivate($title)) {
            $activated = $true
            Write-Log "  Activated with title: '$title'"
            break
        }
        Start-Sleep -Milliseconds 200
    }
    
    if (-not $activated) {
        Write-Log "  Could not activate VS Code, trying Alt+Tab..."
        $wshell.SendKeys('%{TAB}')
        Start-Sleep -Milliseconds 500
        for ($i = 1; $i -le 10; $i++) {
            $wshell.SendKeys('%{TAB}')
            Start-Sleep -Milliseconds 200
            foreach ($title in $windowTitles) {
                if ($wshell.AppActivate($title)) {
                    $activated = $true
                    Write-Log "  Activated via Alt+Tab (attempt $i)"
                    break
                }
            }
            if ($activated) { break }
        }
    }
    
    if (-not $activated) {
        Write-Log "  WARNING: Could not activate VS Code window"
        return $false
    }
    
    # Wait for VS Code to be ready
    Start-Sleep -Milliseconds 500
    
    # Send Ctrl+Shift+B
    Write-Log "  Sending Ctrl+Shift+B..."
    $wshell.SendKeys('^+{b}')
    Start-Sleep -Milliseconds 500
    
    Write-Log "  Ctrl+Shift+B sent successfully"
    return $true
}

function LaunchVSCode {
    Write-Log "Launching VS Code..."
    
    $codePath = "C:\Users\Administrator\AppData\Local\Programs\Microsoft VS Code\Code.exe"
    if (-not (Test-Path $codePath)) {
        $codePath = "C:\Program Files\Microsoft VS Code\Code.exe"
    }
    
    # Try common user profile path if admin path doesn't exist
    if (-not (Test-Path $codePath)) {
        $userName = $env:USERNAME
        $codePath = "C:\Users\$userName\AppData\Local\Programs\Microsoft VS Code\Code.exe"
    }
    
    if (Test-Path $codePath) {
        Write-Log "Launching with --disable-gpu flag..."
        # FIX: Removed -PassThru and -Wait to detach from parent process
        Start-Process -FilePath $codePath -ArgumentList "C:\xampp\htdocs\harvcore", "--disable-gpu" -WindowStyle Normal
        Write-Log "VS Code launched and detached from this process"
        return $true
    } else {
        Write-Log "VS Code executable not found at any expected location!"
        Write-Log "Tried paths:"
        Write-Log "  - C:\Users\Administrator\AppData\Local\Programs\Microsoft VS Code\Code.exe"
        Write-Log "  - C:\Program Files\Microsoft VS Code\Code.exe"
        Write-Log "  - C:\Users\$($env:USERNAME)\AppData\Local\Programs\Microsoft VS Code\Code.exe"
        return $false
    }
}

# Main watchdog loop
while ($true) {
    Write-Log "Starting watchdog cycle..."
    Write-Log "Checking for investors.json, developers.json, and harvhub_investors.json files..."
    
    # Find all JSON files
    $files = Get-ChildItem -Path 'C:\xampp\htdocs\harvcore' -Include 'investors.json','developers.json','harvhub_investors.json' -Recurse -File
    
    # Collect all terminal paths
    $allTerminals = @()
    if ($files) {
        foreach ($file in $files) {
            Write-Log "Found JSON file: $($file.FullName)"
            try {
                $json = Get-Content $file.FullName -Raw | ConvertFrom-Json
                
                # Loop through all properties in the JSON
                foreach ($prop in $json.PSObject.Properties) {
                    $obj = $prop.Value
                    if ($obj.PSObject.Properties) {
                        foreach ($innerProp in $obj.PSObject.Properties) {
                            $value = $innerProp.Value
                            if ($value -is [string] -and $value -match '\.exe') {
                                Write-Log "  - Found terminal path: $value"
                                $allTerminals += $value
                            }
                        }
                    }
                }
            } catch {
                Write-Log "ERROR parsing JSON file $($file.Name): $_"
            }
        }
    } else {
        Write-Log "No JSON files found"
    }
    
    # Remove duplicates
    $allTerminals = $allTerminals | Select-Object -Unique
    Write-Log "Total unique terminals found: $($allTerminals.Count)"
    
    # Launch each terminal that isn't running (check every loop)
    if ($allTerminals.Count -gt 0) {
        foreach ($terminal in $allTerminals) {
            $exe = Split-Path $terminal -Leaf
            $name = $exe -replace '\.exe$',''
            $isRunning = Get-Process -Name $name -ErrorAction SilentlyContinue
            
            $alreadyRunning = $false
            if ($isRunning) {
                foreach ($proc in $isRunning) {
                    try {
                        if ($proc.Path -eq $terminal) {
                            $alreadyRunning = $true
                            Write-Log "Terminal already running: $exe (PID: $($proc.Id))"
                            break
                        }
                    } catch {
                        # If we can't access the path, assume it's the right one
                        $alreadyRunning = $true
                        Write-Log "Terminal may be running: $exe (PID: $($proc.Id)) - Access denied to path"
                        break
                    }
                }
            }
            
            if (-not $alreadyRunning) {
                Write-Log "Launching terminal: $terminal"
                try {
                    Start-Process -FilePath $terminal
                    Write-Log "  - Launch command sent"
                } catch {
                    Write-Log "  - ERROR launching: $_"
                }
            }
        }
    }
    
    # Wait for all terminals to be active (check every loop)
    if ($allTerminals.Count -gt 0) {
        Write-Log "Waiting for terminals to be active..."
        foreach ($terminal in $allTerminals) {
            $exe = Split-Path $terminal -Leaf
            $name = $exe -replace '\.exe$',''
            Write-Log "Waiting for: $exe"
            
            $retries = 0
            $found = $false
            while ($retries -lt 30) {
                $isRunning = Get-Process -Name $name -ErrorAction SilentlyContinue
                if ($isRunning) {
                    foreach ($proc in $isRunning) {
                        try {
                            if ($proc.Path -eq $terminal) {
                                Write-Log "Terminal active: $exe (PID: $($proc.Id))"
                                $found = $true
                                break
                            }
                        } catch {
                            # If path access denied, assume it's the right one
                            Write-Log "Terminal active (assumed): $exe (PID: $($proc.Id))"
                            $found = $true
                            break
                        }
                    }
                    if ($found) { break }
                }
                Start-Sleep -Seconds 1
                $retries++
            }
            if (-not $found) {
                Write-Log "Timeout waiting for terminal: $exe"
            }
        }
    }
    
    # VS CODE SECTION - Reset disabled
    if ($firstLoop) {
        Write-Log "==================== FIRST RUN - NO RESET PERFORMED ===================="
        Write-Log "VS Code settings preserved - running normally"
        $firstLoop = $false
        Write-Log "Waiting 5 seconds before launching VS Code..."
        Start-Sleep -Seconds 5
    } else {
        Write-Log "Waiting 3 seconds before launching VS Code (SUBSEQUENT RUNS)..."
        Start-Sleep -Seconds 3
    }
    
    # LAUNCH VS CODE
    Write-Log "==================== LAUNCHING VS CODE ===================="
    
    # Check if VS Code is already running
    $running = Get-Process -Name "code", "Code" -ErrorAction SilentlyContinue
    if ($running) {
        Write-Log "VS Code is already running with $($running.Count) process(es)"
        
        # Check if any have windows
        $hasWindow = $false
        foreach ($proc in $running) {
            try {
                if ($proc.MainWindowHandle -ne 0) {
                    $hasWindow = $true
                    break
                }
            } catch {}
        }
        
        if (-not $hasWindow) {
            Write-Log "VS Code is running but has no window - attempting to focus existing instance..."
            # Try to bring existing instance to front instead of killing it
            $wshell = New-Object -ComObject wscript.shell
            $wshell.AppActivate('Visual Studio Code')
            Write-Log "Attempted to focus VS Code window"
        } else {
            Write-Log "VS Code already has a visible window"
        }
    } else {
        LaunchVSCode
    }
    
    # Wait for VS Code to fully load
    Write-Log "Waiting 8 seconds for VS Code to stabilize..."
    Start-Sleep -Seconds 8
    
    # Send keys based on whether initial setup was done
    if (-not $initialKeysSent) {
        Write-Log "==================== INITIAL SETUP - SENDING ALL KEYS ===================="
        $success = SendInitialKeys
        if ($success) {
            $initialKeysSent = $true
            Write-Log "Initial setup keys sent successfully!"
        } else {
            Write-Log "Initial setup keys failed, will retry next cycle"
        }
    } else {
        Write-Log "==================== SUBSEQUENT LOOP - SENDING CTRL+SHIFT+B ONLY ===================="
        SendCtrlShiftB
    }
    
    Write-Log "Cycle complete. Looping immediately..."
    Write-Log ""
}