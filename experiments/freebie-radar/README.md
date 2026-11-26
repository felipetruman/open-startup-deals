# Freebie Radar — laboratório Open Startup Deals

Upstream fixado: https://github.com/ZiChuanLan/freebie-radar/commit/0bcd789595662893fc61c0e935f5f8641eae1f2f (1.1.7).

O adaptador utiliza GET /api/items com merge=0 e paginação, sem dependências Python externas. A saída é fila de investigação privada, não um catálogo validado. País, elegibilidade, valor, URL oficial e data de verificação permanecem nulos. O filtro é heurístico; coincidências com o catálogo são potenciais duplicatas, não confirmações.

## Teste local
```sh
cd experiments/freebie-radar
python -m unittest discover -s tests -v
python radar_bridge.py --radar-url http://127.0.0.1:18788 --existing ../../data/deals.json --output out/candidates.json
```

## Smoke real no GitHub Actions

O workflow experimental roda somente no pull request da branch experiment/freebie-radar deste próprio repositório para main, em runner descartável. Constrói a imagem upstream no commit fixado, usa banco temporário, scheduler desligado, sem push, IA, login, bypass ou tokens de terceiros. Coleta exclusivamente openrouter-free e github-free-for-dev, verifica status persistido em SQLite e compara a fila com o snapshot público. Registra apenas métricas agregadas. O conteúdo externo não é publicado nem enviado como artefato. Não confundir testes de transporte/coleta com validação de elegibilidade.

O coletor OpenRouter cobre modelos gratuitos recentes (janela padrão de 14 dias); não é inventário completo. Um resultado vazio pode ser legítimo para esse coletor; uma fila inteiramente vazia bloqueia o smoke.

O catálogo privado continua fonte da verdade. Não alterar main, data/deals.json, automações ou candidaturas; não inventar uma API privada de escrita. Não fazer commit de saídas, bancos, credenciais ou exportações privadas. A decisão de produção depende da revisão do upstream, coleta real, validação oficial e integração autorizada.
