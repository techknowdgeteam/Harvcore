# Watchdog script for launching terminals and VS Code
while ($true) {
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Checking for investors.json, developers.json, and harvhub_investors.json files...")
    
    # Find all JSON files
    $files = Get-ChildItem -Path 'C:\xampp\htdocs\harvcore' -Include 'investors.json','developers.json','harvhub_investors.json' -Recurse -File
    
    # Collect all terminal paths
    $allTerminals = @()
    if ($files) {
        foreach ($file in $files) {
            Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Found: " + $file.FullName)
            $json = Get-Content $file.FullName | ConvertFrom-Json
            
            # Loop through all properties in the JSON
            foreach ($prop in $json.PSObject.Properties) {
                $obj = $prop.Value
                if ($obj.PSObject.Properties) {
                    foreach ($innerProp in $obj.PSObject.Properties) {
                        $value = $innerProp.Value
                        if ($value -is [string] -and $value -match '\.exe') {
                            $allTerminals += $value
                        }
                    }
                }
            }
        }
    } else {
        Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] No JSON files found")
    }
    
    # Remove duplicates
    $allTerminals = $allTerminals | Select-Object -Unique
    
    # Launch each terminal that isn't running
    if ($allTerminals.Count -gt 0) {
        foreach ($terminal in $allTerminals) {
            $exe = Split-Path $terminal -Leaf
            $name = $exe -replace '\.exe$',''
            $isRunning = Get-Process -Name $name -ErrorAction SilentlyContinue
            
            $alreadyRunning = $false
            if ($isRunning) {
                foreach ($proc in $isRunning) {
                    if ($proc.Path -eq $terminal) {
                        $alreadyRunning = $true
                        break
                    }
                }
            }
            
            if (-not $alreadyRunning) {
                Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Launching: " + $terminal)
                Start-Process -FilePath $terminal
            } else {
                Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Already running: " + $exe)
            }
        }
    }
    
    # Wait for all terminals to be active
    if ($allTerminals.Count -gt 0) {
        Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Waiting for terminals to be active...")
        foreach ($terminal in $allTerminals) {
            $exe = Split-Path $terminal -Leaf
            $name = $exe -replace '\.exe$',''
            Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Waiting for: " + $exe)
            
            $retries = 0
            $found = $false
            while ($retries -lt 30) {
                $isRunning = Get-Process -Name $name -ErrorAction SilentlyContinue
                if ($isRunning) {
                    foreach ($proc in $isRunning) {
                        if ($proc.Path -eq $terminal) {
                            Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Active: " + $exe)
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
                Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Timeout waiting for: " + $exe)
            }
        }
    }
    
    # Open VS Code
    Write-Host ("[" + (Get-Date -Format 'HH:mm:ss') + "] Opening harvcore in VS Code...")
    Start-Process -FilePath "code" -ArgumentList "C:\xampp\htdocs\harvcore" -WindowStyle Hidden
    
    # Wait and send Ctrl+Shift+B
    Start-Sleep -Seconds 2
    $wshell = New-Object -ComObject wscript.shell
    $retries = 0
    while ($retries -lt 5) {
        if ($wshell.AppActivate('Visual Studio Code')) {
            Start-Sleep -Milliseconds 500
            $wshell.SendKeys('^+{b}')
            break
        }
        Start-Sleep -Milliseconds 500
        $retries++
    }
    
    Start-Sleep -Seconds 5
}