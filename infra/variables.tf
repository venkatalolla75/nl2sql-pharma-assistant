variable "aws_region" {
  description = "AWS region to deploy into. Must have Bedrock + the chosen Claude model enabled."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  type    = string
  default = "nl2sql-pharma"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "public_subnet_cidrs" {
  type    = list(string)
  default = ["10.42.1.0/24", "10.42.2.0/24"]
}

variable "private_subnet_cidrs" {
  type    = list(string)
  default = ["10.42.11.0/24", "10.42.12.0/24"]
}

variable "ec2_instance_type" {
  description = "Free-tier eligible by default."
  type        = string
  default     = "t3.micro"
}

variable "rds_instance_class" {
  description = "Free-tier eligible by default. db.t4g.small would give more buffer cache headroom, but this AWS account's free-tier plan rejects it outright (FreeTierRestrictionError on ModifyDBInstance) - blocked until the account's billing plan is upgraded or a support request lifts the restriction; see PLAN.md blockers. The default-period backend enforcement + db/03_indexes.sql's account-name expression index (see git log) already fixed the reported timeout without needing this, so it's not urgent."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_allocated_storage_gb" {
  type    = number
  default = 20
}

variable "db_name" {
  type    = string
  default = "pharma"
}

variable "ssh_allowed_cidr" {
  description = "CIDR allowed to SSH into the EC2 instance. Restrict to your own IP/32 — do not leave as 0.0.0.0/0 beyond initial setup."
  type        = string
  default     = "0.0.0.0/0"
}

variable "key_pair_name" {
  description = "Existing EC2 key pair name for SSH access. Leave null to disable SSH (recommended if you don't need shell access)."
  type        = string
  default     = null
}

variable "bedrock_model_id" {
  type    = string
  default = "amazon.nova-pro-v1:0"
}

variable "budget_monthly_limit_usd" {
  description = "Monthly AWS Budget threshold in USD. Alert fires at 80% and 100%."
  type        = number
  default     = 25
}

variable "budget_alert_email" {
  type    = string
  default = "venkatalolla75@gmail.com"
}

variable "repo_url" {
  description = "Public GitHub HTTPS clone URL for this repo (EC2 clones it to build + deploy). No default — set explicitly once the repo is pushed (see PLAN.md blocker on gh auth)."
  type        = string
}

variable "repo_ref" {
  description = "Git branch/tag to deploy."
  type        = string
  default     = "master"
}
