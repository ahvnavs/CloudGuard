# AWS setup and demo walkthrough

[← Back to CloudGuard](../README.md)

This is the optional live path. Run [the local checks](../README.md#run-locally) first; those do not need AWS. The steps below create real resources in one account and region. Deployment and cleanup use your local AWS credentials, not the GitHub plan role.

## 1. Bootstrap state and workflow access

Use an AWS account you control and an authorized local AWS CLI profile. Confirm the account before applying:

```bash
export AWS_PROFILE=your-sandbox-profile
aws sts get-caller-identity
cp bootstrap/terraform.tfvars.example bootstrap/terraform.tfvars
```

Edit `bootstrap/terraform.tfvars` with a globally unique state bucket name and your GitHub `owner/repository`. Keep `aws_region = "ap-south-1"` unless you intend to change the region everywhere.

If the account already has the GitHub Actions OIDC provider, set `existing_oidc_provider_arn` to reuse it. Otherwise bootstrap creates one.

```bash
terraform -chdir=bootstrap init
terraform -chdir=bootstrap plan
terraform -chdir=bootstrap apply
terraform -chdir=bootstrap output
```

Bootstrap creates the encrypted, versioned, private S3 bucket, OIDC trust, and separate plan and shutdown roles. It uses **local Terraform state** to avoid storing its state in a bucket it manages. Keep that ignored state file and a secure backup until cleanup is complete.

## 2. Deploy the demo

```bash
cp environments/demo/backend.hcl.example environments/demo/backend.hcl
cp environments/demo/terraform.tfvars.json.example environments/demo/terraform.tfvars.json
```

Edit `backend.hcl` with the bootstrap bucket name and matching region. Keep `key = "demo/terraform.tfstate"`, `encrypt = true`, and `use_lockfile = true`. Use the default Terraform workspace; the workflow roles and runner target that exact key.

Edit `terraform.tfvars.json` with your budget email and owner tag. The defaults create the network and a USD 5 **account-wide** monthly budget; EC2 stays disabled. Use this one JSON variables file rather than adding an HCL copy that could override it. Keep project, environment, and region consistent with bootstrap.

```bash
terraform -chdir=environments/demo init -backend-config=backend.hcl
terraform -chdir=environments/demo plan
terraform -chdir=environments/demo apply
```

Review the plan before applying. Local variables, backend configuration, and state are ignored by Git. Never commit state, saved plans, or credentials.

## 3. Configure GitHub Actions

In the repository, open **Settings → Secrets and variables → Actions**. Add:

| Kind | Name | Value |
| --- | --- | --- |
| Variable | `AWS_REGION` | `ap-south-1`, matching the deployment |
| Variable | `AWS_STATE_BUCKET` | Bootstrap `state_bucket_name` output |
| Variable | `AWS_PLAN_ROLE_ARN` | Bootstrap `plan_role_arn` output |
| Variable | `AWS_SHUTDOWN_ROLE_ARN` | Bootstrap `shutdown_role_arn` output |
| Secret | `CLOUDGUARD_TFVARS_JSON` | Entire contents of the deployed `terraform.tfvars.json` |
| Variable | `CLOUDGUARD_AWS_ENABLED` | Set to `true` after deployment and configuration |
| Variable | `CLOUDGUARD_STOP_ENABLED` | Leave unset or `false` for scheduled dry runs |

The JSON secret is the canonical copy of deployed inputs, including the budget email, tags, network settings, and any instance overrides. Update it whenever you change the deployment. No AWS access-key secrets are needed.

| Workflow | When it runs | Result |
| --- | --- | --- |
| [Credential-free checks](../.github/workflows/checks.yml) | Every PR, pushes to `main`, or manual run | Local checks, with no AWS access |
| [Optional AWS PR checks](../.github/workflows/aws-pr.yml) | Owner-authored, same-repository PR to `main`, with AWS enabled | Candidate plan plus independent base-branch drift check |
| [Optional daily drift detection](../.github/workflows/drift.yml) | Daily at 7:30 a.m. IST or manual run on `main` | Refresh-only drift check |
| [Optional idle-instance shutdown](../.github/workflows/shutdown.yml) | Nightly at 10:30 p.m. IST or manual run on `main` | CPU assessment; dry run unless explicitly enabled |

Disabled AWS jobs explain why they are skipped. Fork PRs receive the credential-free checks. Enabling AWS with missing required configuration fails the relevant workflow so a setup problem is visible. Manual shutdown runs stay in dry run unless their **execute** checkbox is selected, even when scheduled stopping is enabled. Scheduled execution requires `CLOUDGUARD_STOP_ENABLED=true`.

The trust policy restricts the repository and OIDC audience; shutdown also restricts the branch. Repository write access is a trusted boundary. Live plan jobs publish status and change counts rather than raw plans or state. The plan role can read state and manage only its `.tflock` object; it cannot apply. The shutdown role cannot start or terminate instances or access state.

## Demonstrate the behavior

### Policy rejection and a real PR plan

Run `make python-test` to exercise the negative policy fixture. Public SSH, unrestricted IAM writes, unencrypted EC2 root storage, and a public instance IP must all be rejected. The fixture is never deployed.

For a live plan, open an owner-authored PR that adds a harmless tag to the VPC resource in `modules/vpc/main.tf`. Check the credential-free workflow and, after AWS setup, the optional AWS jobs. The candidate plan uses the PR configuration and deployed JSON inputs; the drift job uses the base branch configuration and the same inputs. A normal plan reporting changes is successful; execution errors fail the job.

### Detect and resolve drift

After an apply, change the VPC's `Name` tag in the AWS console. Run **Optional daily drift detection** manually on `main`. It should fail with `Drift: detected.` Restore the declared tag with a reviewed local plan and apply.

The drift runner uses `plan -refresh-only -detailed-exitcode`: unchanged state succeeds, detected drift fails with a distinct result, and execution errors fail separately. Missing or empty managed state is a setup error, never an unchanged result. Deploy the `main` configuration before treating a base-branch drift check as evidence.

### Preview and stop an idle instance

1. Set `enable_demo_instance` and `auto_stop` to `true` in the JSON variables file. For a repeatable demo, also set a region-specific `ami_id`; otherwise Terraform looks up the latest matching Amazon Linux 2023 x86_64 image.
2. Review a local plan, apply it, and update `CLOUDGUARD_TFVARS_JSON` to match.
3. Leave the instance running for at least 75 minutes, then manually run shutdown on `main` with **execute unchecked**. Check the decision report for `DRY-RUN` or a reason for skipping.
4. To demonstrate a real stop, repeat the manual run with **execute checked**. Scheduled stopping is a separate opt-in through `CLOUDGUARD_STOP_ENABLED=true`.

Only running, on-demand, EBS-backed instances with all three tags are candidates: `Project=CloudGuard`, `Environment=demo`, and `AutoStop=true`. Custom project/environment values come from the deployed JSON. All twelve five-minute CPU averages must be below 5% across a complete hour ending at least five minutes ago. Missing or invalid metrics, recent starts, and Auto Scaling instances are skipped. State and tags are checked again immediately before a stop request. Dry run makes no stop API calls.

The demo instance has an encrypted root volume and requires IMDSv2. It has no public IP, internet route, SSH ingress, instance profile, or software workload. There is no automatic restart.

An intentional stop may appear in refresh-only drift because Terraform records the observed instance state. Review `terraform -chdir=environments/demo plan -refresh-only`, then use `terraform -chdir=environments/demo apply -refresh-only` to accept an intentional state change. A normal plan does not automatically restart the stopped instance.

## Costs and operating limits

Low CPU is an idle heuristic, not proof that an application is unused. Budget emails depend on billing updates and do not cap spending. EC2, EBS, S3 state storage, API use, and other services may incur charges; stopped instances retain storage costs. The project does not assume free-tier eligibility or measured savings.

GitHub schedules are best effort: runs can be delayed, and public-repository schedules can be disabled after inactivity. Use manual runs for the walkthrough. Local mocked checks do not prove a live deployment; record the workflow results only after completing these steps.

## Teardown

Set `CLOUDGUARD_AWS_ENABLED=false` and `CLOUDGUARD_STOP_ENABLED=false` first. Confirm the account again, then review and destroy the demo using your local profile:

```bash
aws sts get-caller-identity
terraform -chdir=environments/demo plan -destroy
terraform -chdir=environments/demo destroy
```

Verify demo deletion before touching its backend. Preserve any state needed for recovery. To remove bootstrap:

1. Confirm that this is the dedicated CloudGuard state bucket and that the demo is gone.
2. Explicitly remove the bucket's `prevent_destroy` protection in `bootstrap/main.tf`.
3. Empty **all object versions and delete markers** in that dedicated bucket. Deleting only current objects leaves version history behind.
4. Review `terraform -chdir=bootstrap plan -destroy`, then run `terraform -chdir=bootstrap destroy`.

A supplied existing OIDC provider is not owned or deleted by bootstrap. Keep local bootstrap state until teardown finishes. Remove the GitHub variables and secret when the deployment is retired.

References: [Terraform provider mocking](https://developer.hashicorp.com/terraform/language/tests/mocking), [S3 state locking](https://developer.hashicorp.com/terraform/language/backend/s3), [Terraform plan modes](https://developer.hashicorp.com/terraform/cli/commands/plan), [GitHub OIDC for AWS](https://docs.github.com/en/actions/how-tos/secure-your-work/security-harden-deployments/oidc-in-aws).
