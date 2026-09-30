output "app_url" {
  description = "Public URL of the deployed chat app. Stable across EC2 replacements (Elastic IP)."
  value       = "http://${aws_eip.app.public_ip}"
}

output "ec2_public_ip" {
  value = aws_eip.app.public_ip
}

output "rds_endpoint" {
  value = aws_db_instance.main.address
}

output "demo_user_password" {
  description = "Shared login password for the 23 seeded demo users (see db/load_data.py for emails/roles)."
  value       = random_password.demo_user.result
  sensitive   = true
}

output "rds_master_password" {
  value     = random_password.rds_master.result
  sensitive = true
}
