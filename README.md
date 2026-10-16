# AI-Powered Cloud-Based Intelligent Project Idea Evaluation and Recommendation System

A two-student, software-only PBL project aligned with **UN SDG 9: Industry, Innovation and Infrastructure**. The supplied `index.html` has been retained and augmented rather than redesigned. The app supports local demonstration without AWS credentials and can be configured to use a new Cognito User Pool and protected AWS API after an explicitly approved deployment.

> **Deployment status:** local build only. No AWS resources have been created, updated, or deleted by this build. `frontend/config.js` intentionally contains empty Cognito/API values. Do not deploy until the preflight, template validation, resource plan, and expected charges have been reviewed.

## 1. Architecture

```text
Browser (preserved HTML/CSS/JS UI)
  ├─ Local demo auth + browser storage (default, no AWS calls)
  └─ Configured AWS mode
       ├─ Amazon Cognito User Pool (email registration/verification, login/reset)
       ├─ API Gateway REST API (Cognito User Pool authorizer)
       │    └─ AWS Lambda / Python 3.12
       │         ├─ private workspace sync endpoint
       │         ├─ rules-based evaluation and similarity engine
       │         ├─ assignments, project requests, notifications and settings routes
       │         └─ optional SES email adapter (off by default)
       ├─ Amazon DynamoDB (on-demand, encrypted, TTL, PITR, recordType GSI)
       └─ CloudWatch Logs (14-day retention)

Static hosting: AWS Amplify Hosting, configured separately using amplify.yml.
```

### Evaluation method

Six criteria are scored from 0–10 and combined using integer weights that must total 100: Innovation, Feasibility, Cost, Implementation time, Social impact, and Scalability. The result is a 0–100 score. The deterministic rules engine also returns strengths/weakness cues, risks, improvement suggestions, technology ideas, and a rough word-overlap comparison. Similarity is a heuristic, **not proof of copying** and not human-level understanding. No model is required. Bedrock inference is disabled by default.

### Authentication and roles

- The CloudFormation template creates a **new** Cognito User Pool, public App Client (no client secret), and `faculty` group.
- Public sign-ups are ordinary students; the browser cannot grant itself faculty access.
- Add faculty membership only from an administrator-controlled AWS session (example command below).
- API Gateway verifies Cognito ID tokens. Lambda uses verified claims for role/ownership checks.
- Local demo mode is intentionally not secure and must never be used for production or connected to a real API.

## 2. Project structure

```text
idea-evaluator/
├── frontend/
│   ├── index.html                 # supplied UI retained; auth/runtime integration adjusted
│   ├── config.js                  # public runtime values only; blank until real deployment outputs exist
│   └── api-client.js              # authenticated domain API integration
├── backend/
│   ├── lambda_function.py         # Lambda API routes and authorization
│   ├── evaluation.py              # deterministic evaluation, recommendations, similarity
│   └── requirements.txt
├── events/
│   ├── env.example.json
│   └── idea-submit.example.json
├── scripts/
│   ├── configure-frontend.ps1
│   ├── deploy.ps1
│   ├── smoke-test.ps1
│   ├── budget.ps1
│   └── cleanup.ps1
├── tests/
│   ├── test_evaluation.py
│   └── test_project_contract.py
├── template.yaml
├── samconfig.toml
├── amplify.yml
├── requirements-dev.txt
├── .env.example
├── .gitignore
└── README.md
```

## 3. Local setup (Windows PowerShell)

Requires Python 3.11+ (the Lambda runtime is Python 3.12), and optionally Node.js for JavaScript syntax checks. AWS CLI/SAM CLI are needed only for deployment validation and AWS tasks.

```powershell
cd path\to\idea-evaluator
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements-dev.txt
pytest -q
python -m compileall backend
```

Start the static frontend:

```powershell
python -m http.server 8000 --directory frontend
```

Open `http://localhost:8000`.

### Local demo authentication

When `frontend/config.js` has empty `userPoolId`, `userPoolClientId`, and `apiBaseUrl`, the app runs in local demo mode. Register with any valid-looking email and a password of at least eight characters; enter **`000000`** as the simulated email-verification code. For local password reset, use code `000000`. The local demo account is stored in this browser only; no password is persisted. Browser workspace data is stored in localStorage. The banner in the app explicitly identifies this mode.

For a clean test, use a private browser window or clear site storage. The included seed examples are illustrative content, not real users or official faculty accounts. For a quick local UI walkthrough, use **Open faculty demo** on the login screen. This is a browser-only preview shortcut; it is not a real faculty account and must never be treated as authorization for a deployed app. In AWS, faculty access must be granted by an authorized administrator through the Cognito `faculty` group.

## 4. SAM validation and build

Install the AWS CLI v2 and AWS SAM CLI using their official installers. These commands do not deploy resources:

```powershell
sam validate --lint --template-file template.yaml
sam build --template-file template.yaml
```

The current environment used for this build may not have SAM installed; if the command is unavailable, run it on your Windows machine before deployment. Do not infer successful SAM validation from Python tests alone.

## 5. Prepare AWS (do not deploy until approved)

Use an IAM Identity Center/SSO profile or a dedicated least-privilege deployment role, with MFA. Avoid root credentials and never paste access keys into project files.

```powershell
aws configure sso
aws sso login --profile YOUR_PROFILE
$env:AWS_PROFILE = "YOUR_PROFILE"
aws sts get-caller-identity --region ap-south-1
```

Review the resource list and costs in the next section. The deployment script validates/builds, shows the planned resources, and requires the exact word `DEPLOY` before it runs `sam deploy`:

```powershell
.\scripts\deploy.ps1 -StackName idea-evaluator -Region ap-south-1 -AllowedOrigin http://localhost:8000
```

**This is a future user-run deployment step, not something executed as part of the local build.** The first deploy can use localhost as the allowed origin while you validate the backend. After Amplify Hosting is configured and its actual branch URL is known, redeploy with that exact URL as `AllowedOrigin` so CORS remains restricted.

### Configure the frontend from real CloudFormation outputs

After an approved deployment, retrieve actual outputs (never guess IDs):

```powershell
aws cloudformation describe-stacks --stack-name idea-evaluator --region ap-south-1 --query "Stacks[0].Outputs" --output table
```

After the API is deployed and you know the exact allowed frontend origin, run the helper to populate `frontend/config.js` from real CloudFormation outputs (it makes a `.bak` first):

```powershell
.\scripts\configure-frontend.ps1 -StackName idea-evaluator -Region ap-south-1 -AllowedOrigin http://localhost:8000
```

Use the actual Amplify branch origin instead of localhost for a published frontend, and ensure the backend stack was deployed with that exact same `AllowedOrigin`. Do not add credentials or a client secret. Rebuild/redeploy the Amplify static frontend after updating this file.

Example configuration shape only (replace placeholders with actual output values):

```javascript
window.APP_CONFIG = Object.freeze({
  region: "ap-south-1",
  userPoolId: "<actual UserPoolId output>",
  userPoolClientId: "<actual UserPoolClientId output>",
  apiBaseUrl: "<actual ApiUrl output>",
  allowedOrigin: "https://<actual-amplify-branch-domain>",
  localDemoMode: false
});
```

### Provision a faculty account

1. Register and verify a normal account through the app.
2. Obtain the exact username/email and user-pool ID from the real outputs/admin console.
3. From an authorized admin profile, add that existing user to the faculty group:

```powershell
aws cognito-idp admin-add-user-to-group --user-pool-id ACTUAL_USER_POOL_ID --username faculty@example.edu --group-name faculty --region ap-south-1
```

Do not give students permission to call this admin command. Sign out and back in after group membership changes so the ID token contains the updated group claim.

### Amplify Hosting

Connect the repository in the Amplify console and use `amplify.yml`. The build publishes the `frontend/` directory as static files. Configure `frontend/config.js` with the actual outputs before the frontend build. Once Amplify returns the branch domain, update the backend stack's `AllowedOrigin` parameter to the exact origin and verify CORS. Hosting and backend are separate deployable components.

## 6. AWS resources and expected charges

| Resource | Purpose | Cost notes |
|---|---|---|
| Cognito User Pool + App Client + group | Registration, verification, authentication, faculty role | MAU-based pricing/free allowance depends on current AWS terms and identity features. Email delivery limits apply. |
| API Gateway REST API | Protected application API | Requests are billable; throttling is configured. |
| Lambda | Python evaluation/API logic | Request and compute charges; small student usage is often inexpensive but not guaranteed free. |
| DynamoDB on-demand table + GSI | Persistent application records and workspace sync | Reads/writes and storage billed; GSI adds storage/throughput usage. |
| DynamoDB point-in-time recovery | Recovery from accidental writes/deletes | **Billable**; disable only after reviewing the recovery tradeoff. |
| CloudWatch Logs | Diagnostics/monitoring | Ingestion/storage billable; retention is set to 14 days. |
| Amplify Hosting | Static frontend delivery/builds | Build minutes and data transfer may be billed. |
| SES (optional) | Email notifications | Disabled until a verified sender is configured; separate SES setup/sandbox limits may apply. |
| Bedrock (optional) | LLM enhancement | Disabled by default and not required. Enabling inference may add charges. |

No exact monthly total can be guaranteed without request volume, storage, hosting transfer, region pricing, and account free-tier eligibility. Set an AWS Budget alert in the Billing console before a public demo; budget alerts do not automatically stop spending. `scripts/budget.ps1` attempts to display current-month Cost Explorer data if the account has Cost Explorer and IAM permissions enabled.

## 7. Monitoring, backup, recovery, cleanup

- Lambda logs: `/aws/lambda/<stack-name>-api`; retention 14 days.
- DynamoDB encryption at rest is enabled; point-in-time recovery is enabled.
- Verify CloudFormation stack events and API responses after any deployment.
- Export/backup important data before changing retention or deleting resources.
- `IdeasTable` has `DeletionPolicy: Retain` and `UpdateReplacePolicy: Retain`; deleting the stack intentionally leaves the table and its data behind.

To clean up only the named project stack, inspect the listed physical resources and run:

```powershell
.\scripts\cleanup.ps1 -StackName idea-evaluator -Region ap-south-1
```

The script requires typing the exact stack name. It does **not** delete the retained DynamoDB table. If you explicitly want to permanently remove project data, first export/backup it, then verify the exact retained table name from CloudFormation outputs and delete that table separately through the AWS console/CLI. Remove Amplify Hosting separately if it was created outside this stack. Do not delete resources belonging to any other stack.

## 8. Test checklist and results

Tests are intentionally split between what can run offline and what requires AWS:

- [x] Deterministic scoring function and weight validation implemented.
- [x] Structured rule-based review, risks, recommendations, technology hints, and similarity disclaimer implemented.
- [x] New Cognito resources are defined in CloudFormation; no old Cognito pool/client/domain references remain in frontend/template.
- [x] Runtime public configuration is separated from HTML and contains no secrets.
- [x] Domain API adapter loads/saves ideas, assignments, faculty projects, scoring settings, notifications, and the public library; local-demo users never send data to AWS.
- [x] Legacy `/sync` API remains isolated to verified-token per-user workspace storage; it is not used to share data between users.
- [x] GSI-based data retrieval is implemented for backend record types; no full-table scan is used by `scan_all()`.
- [x] Python unit tests — **17 passed** in the build environment (`pytest -q`) after the domain API integration contract was updated.
- [x] Python compilation — `python -m compileall -q backend` passed.
- [x] Frontend syntax — HTML parser and both inline JavaScript blocks passed; `frontend/api-client.js` and `frontend/config.js` passed Node syntax checks.
- [x] CloudFormation YAML syntax — parsed successfully with a custom loader for intrinsic tags; this is not equivalent to SAM schema validation.
- [ ] SAM lint/validation and build — not run because the SAM CLI is not installed in this environment. Run the commands in section 4.
- [ ] Real Cognito registration/verification/login/reset — requires deployed AWS resources and a verified email delivery path.
- [ ] Deployed API ownership/role smoke tests and CloudWatch log review — requires deployment.
- [ ] Amplify build, live API CORS, and end-to-end cross-account faculty review — requires deployment and additional integration testing.

## 9. Known limitations to resolve before calling this production-ready

1. The preserved UI uses its existing browser-side data model. The frontend now loads and saves ideas, assignments, faculty projects, scoring weights, notifications, and public library records through the dedicated authenticated domain API routes. Generated record/request IDs are refreshed from the server after writes. Cross-account student-to-faculty workflows still require live AWS end-to-end tests before a live college rollout; local demo mode remains browser-only and is not an authorization boundary.
2. The existing AI-review button is a separate optional enhancement in the supplied UI; the deterministic backend evaluation is the default. No external AI key or Bedrock permission is configured.
3. SES email is off by default. Cognito verification uses Cognito's default email delivery until separately configured.
4. Deployment has not been run. Resource readiness, account permissions, actual URLs/IDs, current AWS pricing, and SAM lint results remain to be verified in the target AWS account.
5. The app is a student-project prototype, not a substitute for human faculty judgment or formal plagiarism detection.
