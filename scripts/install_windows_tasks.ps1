param(
    [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$DailyTime = "10:00",
    [string]$WeeklyNewTime = "09:30",
    [string]$PriceTrendTime = "18:30",
    [switch]$UseExe
)

$ErrorActionPreference = "Stop"

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
        $exeArgument = "--mode $Mode $ExtraArguments".Trim()
        return New-ScheduledTaskAction -Execute $runnerExe -Argument $exeArgument -WorkingDirectory (Split-Path -Parent $runnerExe)
    }

    $python = (Get-Command python -ErrorAction Stop).Source
    $runner = Join-Path $ProjectRoot "competitor_monitor\run_web_task.py"
    if (-not (Test-Path -LiteralPath $runner)) {
        throw "Task runner script not found: $runner"
    }
    $pythonArgument = ('"{0}" --mode {1} {2}' -f $runner, $Mode, $ExtraArguments).Trim()
    return New-ScheduledTaskAction -Execute $python -Argument $pythonArgument -WorkingDirectory $ProjectRoot
}

function Register-CompetitorTask {
    param(
        [string]$TaskName,
        [string]$Description,
        [Microsoft.Management.Infrastructure.CimInstance]$Action,
        [Microsoft.Management.Infrastructure.CimInstance]$Trigger
    )

    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel LeastPrivilege
    $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8)
    Register-ScheduledTask -TaskName $TaskName -Description $Description -Action $Action -Trigger $Trigger -Principal $principal -Settings $settings -Force | Out-Null
    Write-Host "Registered: $TaskName"
}

$startWebBat = Get-ChildItem -LiteralPath $ProjectRoot -Filter "*Web.bat" -File | Select-Object -First 1
if ($null -eq $startWebBat) {
    throw "Web startup bat was not found under: $ProjectRoot"
}

$webAction = New-ScheduledTaskAction -Execute $startWebBat.FullName -WorkingDirectory $ProjectRoot
$webTrigger = New-ScheduledTaskTrigger -AtLogOn
Register-CompetitorTask -TaskName "CompetitorMonitor-WebConsole" -Description "Start the local Web console after Windows logon" -Action $webAction -Trigger $webTrigger

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
