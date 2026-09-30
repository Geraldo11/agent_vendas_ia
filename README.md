# Agentes de vendas fora da carteira (Databricks)

Consórcio + capitalização, pipeline medalhão, agentes com tools, código das regras e manual em PDF.

## Começando

```bash
cp .env.example .env        # preencha host e token
docker compose run --rm dev # abre o shell com Terraform, Databricks CLI e Python
```

Dentro do container:

```bash
cd terraform
terraform init
terraform plan
terraform apply
```

## Se o catálogo já existe (você rodou o notebook 01 antes)

O Terraform não cria o que já existe. Importe antes do `apply`:

```bash
terraform import databricks_catalog.vendas_ia vendas_ia
terraform import 'databricks_schema.camadas["bronze"]' vendas_ia.bronze
terraform import 'databricks_schema.camadas["silver"]' vendas_ia.silver
terraform import 'databricks_schema.camadas["gold"]' vendas_ia.gold
terraform import 'databricks_schema.camadas["apoio"]' vendas_ia.apoio
terraform import databricks_volume.raw vendas_ia.bronze.raw
terraform import databricks_volume.docs vendas_ia.apoio.docs
```

## Estrutura

- `terraform/`: infraestrutura (catálogo, schemas, volumes; depois grants e jobs)
- `notebooks/`: notebooks do pipeline
- `regras/`: um módulo de regras por produto, com interface comum
- `agentes/`: orquestrador, tools e prompts
- `docs/`: manuais em PDF
- `tests/`: testes (pytest)

## Notas

- O state do Terraform fica local (`terraform/terraform.tfstate`) e não vai para o Git. Para uso em equipe, migrar para backend remoto.
- Nunca versionar `.env` nem `*.tfvars`.
