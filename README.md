# Open Startup Deals

Catálogo público de créditos, free tiers, descontos e benefícios para startups, desenvolvedores solo e estudantes.

## Publicação sem expor dados privados

- Fonte da verdade: catálogo **privado** do Site Open Startup Deals. A API privada requer autenticação.
- Dataset público: [data/deals.json](data/deals.json). Nunca copiar a resposta bruta do Site: contém campos operacionais que não devem ser publicados.
- Publicação: radar existente, com execução às **09:00 e 21:00** no fuso America/Sao_Paulo. O radar autentica no Site, constrói uma cópia sanitizada e publica via GitHub conectado. Sem acesso de leitura/escrita, não publicar e relatar o bloqueio.
- Verificação independente: [GitHub Actions](.github/workflows/catalog-health.yml), às **09:50 e 21:50** (horário de Brasília), testa schema, segurança e idade do snapshot.
- Falha segura: não publicar snapshots incompletos, duplicados, suspeitos de PII, com links inválidos ou cuja contagem caia inesperadamente. Não atualizar `snapshot_at` quando não houver leitura real.

## Testes

Python 3.12+, sem dependências:

```bash
python -m unittest discover -s tests -v
python scripts/catalog_public.py check --input data/deals.json
python scripts/catalog_public.py check --input data/deals.json --max-age-hours 13
```

A última verificação falha deliberadamente quando o dataset passa de 13 horas sem uma nova captura. O GitHub Actions sinaliza o problema, mas não acessa a API privada nem possui tokens dela.

## Exportação manual autorizada

Obtenha, usando acesso legítimo ao Site, um JSON completo do `GET /api/catalog-sync`, salve-o temporariamente como `private-catalog.json` (fora do controle de versão) e execute:

```bash
python scripts/catalog_public.py export --input private-catalog.json --previous data/deals.json --output data/deals.json
python scripts/catalog_public.py check --input data/deals.json
```

Somente os seguintes campos podem sair do Site para o dataset público: `id`, `name`, `org`, `category`, `country`, `audience`, `stage`, `eligibility`, `requirements`, `value`, `amount`, `currency`, `validity`, `deadline`, `status`, `confidence`, `official`, `evidence`, `verified`.

Os demais campos, como histórico, notas, candidaturas, documentos, tokens, contatos, dados de pagamento e saldos privados, são descartados. Se um campo público contiver padrões de e-mail, telefone ou segredo, a publicação é bloqueada.

`snapshot_at` é a data/hora de coleta do catálogo. `verified` identifica a última verificação da oferta. Não confundir valor máximo anunciado com crédito aprovado.

**Nunca faça commit** de um export bruto do Site ou de credenciais.
