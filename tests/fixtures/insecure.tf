# Deliberately unsafe, never deployed. Excluded from the normal baseline scan.
resource "aws_security_group" "public_ssh" {
  name = "unsafe-fixture"
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "public_unencrypted" {
  ami                         = "ami-0123456789abcdef0"
  instance_type               = "t3.micro"
  associate_public_ip_address = true
  root_block_device {
    encrypted = false
  }
}

resource "aws_iam_policy" "unrestricted_write" {
  name = "unsafe-fixture"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "ec2:TerminateInstances"
      Resource = "*"
    }]
  })
}
