resource "random_password" "rds_master" {
  length  = 32
  special = false # avoid characters Postgres connection strings need escaping
}

resource "random_password" "app_db" {
  length  = 32
  special = false
}

resource "random_password" "demo_user" {
  length  = 20
  special = false
}

resource "random_id" "session_secret" {
  byte_length = 32
}

resource "aws_db_instance" "main" {
  identifier     = "${var.project_name}-db"
  engine         = "postgres"
  engine_version = "16"

  instance_class    = var.rds_instance_class
  allocated_storage = var.rds_allocated_storage_gb
  storage_type      = "gp3"
  storage_encrypted = true

  # Without this, an instance_class change (or any other modifiable-in-place change)
  # only takes effect at the next maintenance window, not on `terraform apply` - not
  # what you want when sizing up specifically to fix a live timeout. Causes a brief
  # (a few minutes) reboot for class changes; does not affect stored data or the
  # endpoint/Elastic IP.
  apply_immediately = true

  db_name  = var.db_name
  username = "pgadmin"
  password = random_password.rds_master.result

  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.rds.id]
  publicly_accessible    = false
  multi_az               = false # single-AZ keeps this within free-tier-friendly cost

  backup_retention_period = 1
  skip_final_snapshot     = true
  deletion_protection     = false # take-home demo; would be true in a real deployment

  tags = { Name = "${var.project_name}-db" }
}
