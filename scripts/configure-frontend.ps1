[CmdletBinding()]
param(
  [string]$StackName = "idea-evaluator",
  [string]$Region = "ap-south-1",
  [Parameter(Mandatory=$true)][string]$AllowedOrigin
)
$ErrorActionPreference = "Stop"
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "AWS CLI is required." }
if ($AllowedOrigin -notmatch '^https?://[^/]+$') { throw "AllowedOrigin must be an exact origin, e.g. https://main.example.amplifyapp.com (no path or trailing slash)." }
$raw = aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].Outputs' --output json
if ($LASTEXITCODE -ne 0) { throw "Could not read stack outputs. Confirm stack name, region, and AWS profile." }
$outputs = $raw | ConvertFrom-Json
function OutputValue([string]$key) {
  $item = $outputs | Where-Object { $_.OutputKey -eq $key } | Select-Object -First 1
  if (-not $item -or -not $item.OutputValue) { throw "CloudFormation output '$key' was not found." }
  return [string]$item.OutputValue
}
$api = OutputValue 'ApiUrl'
$pool = OutputValue 'UserPoolId'
$client = OutputValue 'UserPoolClientId'
$configPath = Join-Path (Split-Path $PSScriptRoot -Parent) 'frontend\config.js'
$backupPath = "$configPath.bak"
Copy-Item $configPath $backupPath -Force
$content = @"
/* Public runtime configuration generated from CloudFormation outputs. Never put secrets here. */
window.APP_CONFIG = Object.freeze({
  region: "$Region",
  userPoolId: "$pool",
  userPoolClientId: "$client",
  apiBaseUrl: "$api",
  allowedOrigin: "$AllowedOrigin",
  localDemoMode: false
});
"@
Set-Content -Path $configPath -Value $content -Encoding utf8
Write-Host "Updated $configPath using actual stack outputs. Backup: $backupPath" -ForegroundColor Green
Write-Host "Verify that the backend AllowedOrigin parameter exactly matches '$AllowedOrigin' before publishing the frontend." -ForegroundColor Yellow
