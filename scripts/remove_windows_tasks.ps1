$ErrorActionPreference = "Stop"

$taskNames = @(
    "CompetitorMonitor-WebConsole",
    "CompetitorMonitor-DailyPrice",
    "CompetitorMonitor-WeeklyNew",
    "CompetitorMonitor-PriceTrend"
)

foreach ($taskName in $taskNames) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
        Write-Host "Removed: $taskName"
    } else {
        Write-Host "Not found: $taskName"
    }
}
