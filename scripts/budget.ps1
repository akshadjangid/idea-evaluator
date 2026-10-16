[CmdletBinding()]
param([string]$Region = "ap-south-1")
$ErrorActionPreference = "Continue"
Write-Host "Idea Evaluator cost-control checklist" -ForegroundColor Cyan
Write-Host "- DynamoDB uses on-demand billing; point-in-time recovery is enabled and is billable by stored-data size."
Write-Host "- Lambda/API Gateway/CloudWatch usage may be within free allowances but is not guaranteed free."
Write-Host "- Cognito default email has service limits; SES is disabled unless a verified sender is configured."
Write-Host "- Bedrock is disabled by default; enabling a model may add inference charges."
Write-Host "- Amplify Hosting usage may incur charges depending on build minutes and data transfer."
Write-Host "\nCurrent-month service cost query (requires Cost Explorer permissions):"
$start = (Get-Date -Day 1).ToString('yyyy-MM-dd')
$end = (Get-Date).Date.AddDays(1).ToString('yyyy-MM-dd')
aws ce get-cost-and-usage --time-period "Start=$start,End=$end" --granularity MONTHLY --metrics UnblendedCost --group-by "Type=DIMENSION,Key=SERVICE" --region us-east-1 --output table
if ($LASTEXITCODE -ne 0) { Write-Host "Cost query unavailable; check Cost Explorer activation and IAM permissions." }
