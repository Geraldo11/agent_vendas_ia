terraform {
  required_version = ">= 1.5"

  required_providers {
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.50"
    }
  }
}

# Autenticação via variáveis de ambiente DATABRICKS_HOST e DATABRICKS_TOKEN
provider "databricks" {}
