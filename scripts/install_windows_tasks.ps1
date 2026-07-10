param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$DailyTime = "10:00",
    [string]$WeeklyNewTime = "09:30",
    [string]$PriceTrendTime = "18:30",
    [switch]$UseExe
)

$ErrorActionPreference = "Stop"

function New-WebConsoleTaskAction {
    if ($UseExe) {
        $webExe = Join-Path $ProjectRoot "dist\CompetitorMonitorWeb\CompetitorMonitorWeb.exe"
        if (-not (Test-Path -LiteralPath $webExe)) {
            throw "Web console exe not found: $webExe. Run the build bat first, or run this script without -UseExe."
        }
        return New-ScheduledTaskAction -Execute $webExe -WorkingDirectory (Split-Path -Parent $webExe)
    }

    $startWebBat = Get-ChildItem -LiteralPath $ProjectRoot -Filter "*Web.bat" -File | Select-Object -First 1
    if ($null -eq $startWebBat) {
        throw "Web startup bat was not found under: $ProjectRoot"
    }
    return New-ScheduledTaskAction -Execute $startWebBat.FullName -WorkingDirectory $ProjectRoot
}

function New-CompetitorTaskAction {
    param(
        [string]$Mode,
        [string]$ExtraArguments = ""
    )

    if ($UseExe) {
        $runnerExe = Join-Path $ProjectRoot "dist\CompetitorMonitorTaskRunner\CompetitorMonitorTaskRunner.exe"
        if (-not (Test-Path -LiteralPath $runnerExe)) {
            throw "Task runner exe not found: $runnerExe. Run the build bat first, or run this script without -UseExe."
        }
        $configPath = Join-Path $ProjectRoot "dist\CompetitorMonitorWeb\competitor_monitor\config.yaml"
        $runnerDir = Split-Path -Parent $runnerExe
        $runnerCommand = @"
`$ErrorActionPreference = "Stop"
`$runnerArgs = @("--mode", "$Mode", "--config", "$configPath")
`$extraArguments = "$ExtraArguments"
if (-not [string]::IsNullOrWhiteSpace(`$extraArguments)) {
    `$runnerArgs += `$extraArguments.Split(" ", [System.StringSplitOptions]::RemoveEmptyEntries)
}
`$process = Start-Process -FilePath "$runnerExe" -ArgumentList `$runnerArgs -WorkingDirectory "$runnerDir" -WindowStyle Hidden -Wait -PassThru
exit `$process.ExitCode
"@
        $encodedCommand = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($runnerCommand))
        $actionArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -EncodedCommand $encodedCommand"
        return New-ScheduledTaskAction -Execute "powershell.exe" -Argument $actionArgs -WorkingDirectory $runnerDir
    }

    $python = (Get-Command python -ErrorAction Stop).Source
    $runner = Join-Path $ProjectRoot "competitor_monitor\run_web_task.py"
    if (-not (Test-Path -LiteralPath $runner)) {
        throw "Task runner script not found: $runner"
    }
    $configPath = Join-Path $ProjectRoot "competitor_monitor\config.yaml"
    $pythonArgument = ('"{0}" --mode {1} --config "{2}" {3}' -f $runner, $Mode, $configPath, $ExtraArguments).Trim()
    return New-ScheduledTaskAction -Execute $python -Argument $pythonArgument -WorkingDirectory $ProjectRoot
}

function Register-CompetitorTask {
    param(
        [string]$TaskName,
        [string]$Description,
        [Microsoft.Management.Infrastructure.CimInstance]$Action,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger
    )

    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    Register-ScheduledTask -TaskName $TaskName -Description $Description -Action $Action -Trigger $Trigger -Settings $settings -Force | Out-Null
    Write-Host "Registered: $TaskName"
}

$webAction = New-WebConsoleTaskAction
$webTrigger = New-ScheduledTaskTrigger -AtLogOn
try {
    Register-CompetitorTask -TaskName "CompetitorMonitor-WebConsole" -Description "Start the local Web console after Windows logon" -Action $webAction -Trigger $webTrigger
} catch {
    Write-Warning "Web console logon task was not registered: $($_.Exception.Message)"
    Write-Warning "Daily and weekly background tasks will still be registered. Start the Web console manually when you need to view it."
}

$dailyAction = New-CompetitorTaskAction -Mode "daily_price"
$dailyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $DailyTime
Register-CompetitorTask -TaskName "CompetitorMonitor-DailyPrice" -Description "Run daily mature-product price collection and backend WeCom notification" -Action $dailyAction -Trigger $dailyTrigger

$weeklyAction = New-CompetitorTaskAction -Mode "weekly_new"
$weeklyTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday -At $WeeklyNewTime
Register-CompetitorTask -TaskName "CompetitorMonitor-WeeklyNew" -Description "Run weekly BI new-product monitoring for the previous complete work week" -Action $weeklyAction -Trigger $weeklyTrigger

$trendAction = New-CompetitorTaskAction -Mode "price_trend"
$trendTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At $PriceTrendTime
Register-CompetitorTask -TaskName "CompetitorMonitor-PriceTrend" -Description "Run Friday price trend analysis" -Action $trendAction -Trigger $trendTrigger

Write-Host ""
Write-Host "Windows scheduled tasks are installed."
Write-Host "ProjectRoot: $ProjectRoot"
Write-Host "Daily price: Monday-Friday $DailyTime"
Write-Host "Weekly new: Saturday $WeeklyNewTime"
Write-Host "Price trend: Friday $PriceTrendTime"
