output "vpc_id" {
  description = "Isolated VPC ID."
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "Private subnet IDs in availability-zone input order."
  value       = [for subnet in aws_subnet.private : subnet.id]
}

output "default_security_group_id" {
  description = "Default security group with all ingress and egress removed."
  value       = aws_default_security_group.this.id
}

output "private_route_table_id" {
  description = "Route table with no internet routes."
  value       = aws_route_table.private.id
}
