data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ec2" {
  name               = "${var.project_name}-ec2-role"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid = "InvokeClaudeModels"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      "arn:aws:bedrock:*::foundation-model/anthropic.*",
    ]
  }
}

resource "aws_iam_policy" "bedrock_invoke" {
  name   = "${var.project_name}-bedrock-invoke"
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}

resource "aws_iam_role_policy_attachment" "bedrock" {
  role       = aws_iam_role.ec2.name
  policy_arn = aws_iam_policy.bedrock_invoke.arn
}

# Lets you reach the instance via SSM Session Manager without opening port 22 or
# managing an SSH key pair — recommended over the ssh_allowed_cidr path.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.ec2.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.ec2.name
}
