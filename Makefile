TERRAFORM ?= terraform
PYTHON ?= python3
CHECKOV ?= checkov
TF_DIRS := modules/vpc modules/iam modules/budget bootstrap environments/demo
.DEFAULT_GOAL := help

.PHONY: help check fmt format init validate test terraform-test python-test policy

help:
	@printf '%s\n' \
		'make check     Run all checks without AWS credentials' \
		'make test      Run mocked Terraform and Python tests' \
		'make validate  Check Terraform configuration and provider schemas' \
		'make policy    Scan Terraform with the Checkov baseline' \
		'make fmt       Check Terraform formatting' \
		'make format    Apply Terraform formatting'

# No AWS credentials or live resources are used by these targets.
check: fmt validate test policy

fmt:
	$(TERRAFORM) fmt -check -recursive

format:
	$(TERRAFORM) fmt -recursive

init:
	@set -eu; for directory in $(TF_DIRS); do \
		$(TERRAFORM) -chdir=$$directory init -backend=false -input=false -lockfile=readonly; \
	done

validate: init
	@set -eu; for directory in $(TF_DIRS); do \
		$(TERRAFORM) -chdir=$$directory validate; \
	done

test: terraform-test python-test

terraform-test: init
	@set -eu; for directory in $(TF_DIRS); do \
		$(TERRAFORM) -chdir=$$directory test -no-color; \
	done

python-test:
	$(PYTHON) -m unittest discover -s tests -v

policy:
	$(CHECKOV) --directory . --config-file .checkov.yaml
