data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

resource "aws_instance" "app" {
  ami                    = data.aws_ami.al2023.id
  instance_type          = var.ec2_instance_type
  subnet_id              = aws_subnet.public[0].id
  vpc_security_group_ids = [aws_security_group.ec2.id]
  iam_instance_profile   = aws_iam_instance_profile.ec2.name
  key_name               = var.key_pair_name

  # 20GB gp3 is comfortably free-tier-eligible and enough for the app image + the
  # regenerated ~260MB CSV set.
  root_block_device {
    volume_type = "gp3"
    volume_size = 20
  }

  user_data = templatefile("${path.module}/templates/user_data.sh.tpl", {
    repo_url           = var.repo_url
    repo_ref           = var.repo_ref
    rds_endpoint       = aws_db_instance.main.address
    db_name            = var.db_name
    rds_username       = aws_db_instance.main.username
    rds_password       = random_password.rds_master.result
    app_db_password    = random_password.app_db.result
    demo_user_password = random_password.demo_user.result
    session_secret     = random_id.session_secret.hex
    aws_region         = var.aws_region
    bedrock_model_id   = var.bedrock_model_id
  })
  user_data_replace_on_change = true

  tags = { Name = "${var.project_name}-app" }

  depends_on = [aws_db_instance.main]
}
