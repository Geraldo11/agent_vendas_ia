output "catalogo" {
  value = databricks_catalog.vendas_ia.name
}

output "schemas" {
  value = [for s in databricks_schema.camadas : s.name]
}

output "volumes" {
  value = {
    raw  = "/Volumes/${var.catalog_name}/bronze/raw"
    docs = "/Volumes/${var.catalog_name}/apoio/docs"
  }
}
