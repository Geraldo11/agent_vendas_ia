# Regras de negócio

Interface única: `avaliar_venda(venda) -> Resultado(elegivel, regra_id, motivo)`.

Campos esperados no dicionário `venda`:
`id_venda, produto, id_vendedor, canal, data_venda, vendedor_data_inicio,
vendedor_data_desligamento, data_pagamento, data_cancelamento,
tipo_consorcio, modalidade, forma_pagamento`

Ordem de avaliação: COM-02, COM-01, COM-03, depois as regras do produto.
A primeira regra que bloqueia define o resultado.

| ID | Regra |
|----|-------|
| COM-01 | Vendedor ativo na data da venda (no dia do desligamento já está inativo) |
| COM-02 | Digital sem vendedor identificado fica fora |
| COM-03 | Cancelamento em até 7 dias (arrependimento) não conta |
| CONS-01 | Só imóvel e auto entram |
| CONS-02 | Só conta após pagamento da 1ª parcela |
| CAP-01 | Só modalidades tradicional e incentivo entram |
| CAP-02 | Pagamento único conta na hora; mensal só após a 1ª mensalidade |
| CAP-03 | Cancelamento em até 60 dias (carência) não conta |
