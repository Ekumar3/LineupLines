# Remote state configuration.
# Fill in bucket and dynamodb_table after running state_bootstrap/main.tf.
# The key can stay as-is — each environment can use a different key prefix.

terraform {
  backend "s3" {
    # Replace with the output from state_bootstrap
    bucket         = "lineuplines-terraform-state-REPLACE_WITH_ACCOUNT_ID"
    key            = "production/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "lineuplines-terraform-locks"
    encrypt        = true
  }
}
