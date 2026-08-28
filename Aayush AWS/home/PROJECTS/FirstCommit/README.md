# FirstCommit

FirstCommit turns a public GitHub repository into a personalized contributor roadmap. It scans repository metadata, documentation, important files, and open issues, then uses Amazon Bedrock to provide a practical onboarding workspace.

## Live application

https://wvnzqjk5n2r2bl3s6xtw7bbwbm0zmlup.lambda-url.us-east-1.on.aws/

## What is included

- Public GitHub URL validation and repository scanning
- Important-file detection and recommended reading order
- Architecture areas, issue matching, and readiness scoring
- Repository-grounded Q&A
- Optional Amazon Bedrock enrichment with a deterministic fallback
- DynamoDB scan persistence
- Public Lambda Function URL deployment through AWS SAM

## Deploy

Prerequisites:

- AWS SAM CLI
- AWS CLI authenticated to an AWS account
- An AWS region with access to the selected Bedrock model

Build and deploy:

```bash
sam build
sam deploy --guided
```

During the guided deployment, accept the generated CloudFormation changeset, allow SAM to create the required IAM role, and keep EnableBedrock=true if the account has access to Amazon Nova Lite. If Bedrock model access is not enabled yet, deploy with EnableBedrock=false; repository scanning and the deterministic onboarding report will still work.

The deployed Function URL is printed in the CloudFormation outputs as FirstCommitUrl.

## Local development

The Lambda handler is in src/app.py and the browser application is in src/web/index.html.

```bash
sam build
sam local start-api
```

For local invocation, use the Function URL event shape or call the deployed URL. The GitHub API is public, but it can rate-limit unauthenticated requests.

## Notes

The model is instructed to use only the structured repository evidence supplied by the scanner. Recommendations are guidance and should be verified against the repository's current documentation, tests, and maintainer instructions.
