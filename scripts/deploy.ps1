[CmdletBinding()]
param(
  [string]$StackName = "idea-evaluator",
  [string]$Region = "ap-south-1",
  [string]$AllowedOrigin = "http://localhost:8000"
)
$ErrorActionPreference = "Stop"

Write-Host "Idea Evaluator deployment preflight" -ForegroundColor Cyan
if (-not (Get-Command aws -ErrorAction SilentlyContinue)) { throw "AWS CLI v2 is not installed or not on PATH." }
if (-not (Get-Command sam -ErrorAction SilentlyContinue)) { throw "AWS SAM CLI is not installed or not on PATH." }
aws sts get-caller-identity --region $Region
if ($LASTEXITCODE -ne 0) { throw "AWS identity check failed. Configure an SSO/profile and retry." }

Write-Host "\nPlanned resources: Cognito User Pool, public App Client, faculty group, DynamoDB table + GSI, API Gateway REST API, Lambda function, IAM role/policies, CloudWatch log group." -ForegroundColor Yellow
Write-Host "Region: $Region | Stack: $StackName | Initial allowed origin: $AllowedOrigin"
Write-Host "No Bedrock model or SES sender is enabled by default. DynamoDB PITR may incur charges."
Write-Host "This script will validate/build before it asks permission to deploy."

sam validate --lint --template-file template.yaml
if ($LASTEXITCODE -ne 0) { throw "SAM validation failed." }
sam build --template-file template.yaml
if ($LASTEXITCODE -ne 0) { throw "SAM build failed." }

$confirmation = Read-Host "To create/update the listed AWS resources, type DEPLOY"
if ($confirmation -cne "DEPLOY") { Write-Host "Cancelled. No deployment command was run."; exit 0 }
sam deploy --stack-name $StackName --region $Region --capabilities CAPABILITY_IAM --resolve-s3 --parameter-overrides "AllowedOrigin=$AllowedOrigin" "SenderEmail=" "EmailDomain=" "TzOffsetMin=330" --no-fail-on-empty-changeset
if ($LASTEXITCODE -ne 0) { throw "SAM deployment command failed; inspect CloudFormation events before retrying." }
Write-Host "Deployment command completed. Verify actual stack outputs with:" -ForegroundColor Green
Write-Host "aws cloudformation describe-stacks --stack-name $StackName --region $Region --query 'Stacks[0].Outputs'"
