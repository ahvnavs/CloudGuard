mock_provider "aws" {
  mock_data "aws_availability_zones" {
    defaults = {
      names = ["ap-south-1a", "ap-south-1b", "ap-south-1c"]
    }
  }
  mock_data "aws_ami" {
    defaults = { id = "ami-0123456789abcdef0" }
  }
}

variables {
  budget_email = "owner@example.com"
}

run "no_instance_by_default" {
  command = plan

  assert {
    condition     = length(aws_instance.demo) == 0 && length(data.aws_ami.amazon_linux) == 0 && output.demo_instance_id == null
    error_message = "The default demo must not create an instance or look up an AMI."
  }
}

run "secure_optional_instance" {
  command = plan
  variables {
    enable_demo_instance = true
    tags = {
      AutoStop    = "true"
      Project     = "overridden"
      Environment = "overridden"
      ManagedBy   = "overridden"
    }
  }

  assert {
    condition     = !aws_instance.demo[0].associate_public_ip_address && aws_instance.demo[0].root_block_device[0].encrypted && aws_instance.demo[0].root_block_device[0].volume_type == "gp3"
    error_message = "The optional instance must have no public IP and must use encrypted gp3 root storage."
  }
  assert {
    condition     = aws_instance.demo[0].metadata_options[0].http_tokens == "required" && aws_instance.demo[0].metadata_options[0].http_put_response_hop_limit == 1
    error_message = "IMDSv2 and a hop limit of one must be required."
  }
  assert {
    condition     = aws_instance.demo[0].tags.AutoStop == "false" && aws_instance.demo[0].tags.Project == "CloudGuard" && aws_instance.demo[0].tags.Environment == "demo" && aws_instance.demo[0].tags.ManagedBy == "Terraform"
    error_message = "User tags must not override opt-in or project security tags."
  }
}

run "explicit_shutdown_opt_in_and_ami" {
  command = plan
  variables {
    enable_demo_instance = true
    auto_stop            = true
    ami_id               = "ami-0123456789abcdef0"
  }

  assert {
    condition     = aws_instance.demo[0].tags.AutoStop == "true" && aws_instance.demo[0].ami == "ami-0123456789abcdef0" && length(data.aws_ami.amazon_linux) == 0
    error_message = "Honor explicit shutdown and AMI settings without an unnecessary AMI lookup."
  }
}
