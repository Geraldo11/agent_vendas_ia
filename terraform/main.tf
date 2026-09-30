resource "databricks_catalog" "vendas_ia" {
  name          = var.catalog_name
  comment       = "Projeto de agentes: vendas fora da carteira (consórcio e capitalização)"
  storage_root  = var.catalog_storage_root
  force_destroy = false

  lifecycle {
    ignore_changes  = [storage_root, properties]
    prevent_destroy = true
  }
}

resource "databricks_schema" "camadas" {
  for_each      = var.schemas
  catalog_name  = databricks_catalog.vendas_ia.name
  name          = each.key
  comment       = "Camada ${each.key}"
  force_destroy = false
}

# Arquivos brutos de entrada
resource "databricks_volume" "raw" {
  catalog_name = databricks_catalog.vendas_ia.name
  schema_name  = databricks_schema.camadas["bronze"].name
  name         = "raw"
  volume_type  = "MANAGED"
  comment      = "Arquivos brutos"
}

# Manuais em PDF e cópias do código das regras
resource "databricks_volume" "docs" {
  catalog_name = databricks_catalog.vendas_ia.name
  schema_name  = databricks_schema.camadas["apoio"].name
  name         = "docs"
  volume_type  = "MANAGED"
  comment      = "Manuais em PDF e código das regras"
}
