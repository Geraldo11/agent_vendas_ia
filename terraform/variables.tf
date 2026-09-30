variable "catalog_name" {
  description = "Nome do catálogo no Unity Catalog"
  type        = string
  default     = "vendas_ia"
}

variable "catalog_storage_root" {
  description = "Storage root do catálogo. Deixe null para usar o default do metastore/workspace"
  type        = string
  default     = null
}

variable "schemas" {
  description = "Schemas da arquitetura medalhão + apoio (gabarito e docs)"
  type        = set(string)
  default     = ["bronze", "silver", "gold", "apoio"]
}
