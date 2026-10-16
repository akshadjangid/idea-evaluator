[CmdletBinding()]
param([string]$StackName = "idea-evaluator", [string]$Region = "ap-south-1")
$ErrorActionPreference = "Stop"
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "AWS CLI is required." }
$stack = aws cloudformation describe-stacks --stack-name $StackName --region $Region --output json 2>$null | ConvertFrom-Json
if (-not $stack) { Write-Host "Stack '$StackName' was not found in $Region; nothing to do."; exit 0 }
Write-Host "Target stack: $StackName ($Region)" -ForegroundColor Yellow
aws cloudformation list-stack-resources --stack-name $StackName --region $Region --query 'StackResourceSummaries[*].[LogicalResourceId,ResourceType,PhysicalResourceId,ResourceStatus]' --output table
Write-Host "WARNING: The DynamoDB table has DeletionPolicy: Retain. Stack deletion leaves the table and its data behind." -ForegroundColor Yellow
Write-Host "This script will not delete retained data. Back up/export it and delete the table separately only if you explicitly want permanent data deletion."
$confirmation = Read-Host "Type the exact stack name '$StackName' to delete only this CloudFormation stack"
if ($confirmation -cne $StackName) { Write-Host "Cancelled; no deletion command was run."; exit 0 }
aws cloudformation delete-stack --stack-name $StackName --region $Region
if ($LASTEXITCODE -ne 0) { throw "Delete request failed." }
aws cloudformation wait stack-delete-complete --stack-name $StackName --region $Region
if ($LASTEXITCODE -ne 0) { throw "Stack deletion did not complete; inspect CloudFormation events." }
Write-Host "Stack deleted. Check list-stack-resources output/table retention and Amplify Hosting separately." -ForegroundColor Green
