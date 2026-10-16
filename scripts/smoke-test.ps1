[CmdletBinding()]
param(
  [Parameter(Mandatory=$true)][string]$ApiUrl,
  [Parameter(Mandatory=$true)][string]$IdToken
)
$ErrorActionPreference = "Stop"
$base = $ApiUrl.TrimEnd('/')
$headers = @{ Authorization = $IdToken }
$checks = @(
  @{ Path = '/ideas'; Label = 'ideas API' },
  @{ Path = '/assignments'; Label = 'assignments API' },
  @{ Path = '/projects'; Label = 'faculty projects API' },
  @{ Path = '/settings'; Label = 'scoring settings API' },
  @{ Path = '/notifications'; Label = 'notifications API' },
  @{ Path = '/library'; Label = 'public project library API' }
)
Write-Host "Checking authenticated Idea Evaluator API routes..." -ForegroundColor Cyan
foreach ($check in $checks) {
  try {
    $result = Invoke-RestMethod -Method Get -Uri "$base$($check.Path)" -Headers $headers -TimeoutSec 20
    if ($null -eq $result) { throw "Empty response." }
    Write-Host "PASS: $($check.Label)" -ForegroundColor Green
  } catch {
    Write-Error "FAIL: $($check.Label). Check the API URL, ID token, Cognito role, and CloudWatch logs. $($_.Exception.Message)"
    exit 1
  }
}
Write-Host "Smoke tests passed. This verifies API reachability, not all student/faculty authorization cases." -ForegroundColor Green
