# Otimização de rotas para distribuição de medicamentos e insumos

Projeto 2 do Tech Challenge da Fase 2 (Pós Tech FIAP, IA para Devs).

Um hospital precisa entregar medicamentos e insumos em unidades de saúde e em domicílios. Algumas entregas são críticas, algumas exigem refrigeração, e cada veículo tem seu limite de carga e de autonomia. O projeto resolve esse problema em duas partes:

1. **Algoritmo genético:** define qual veículo atende cada entrega, e em que ordem. Parte do código base `genetic_algorithm_tsp`.
2. **LLM pré-treinada:** transforma o plano em instruções para motoristas e em relatórios, sugere melhorias e responde a perguntas sobre as rotas.

> Os dados são sintéticos e as economias são medidas contra um despacho simulado, não contra a operação real de um hospital.

## Onde cada requisito é atendido

| Requisito do desafio | Onde está |
| --- | --- |
| Representação genética para as rotas | [medroute/fitness.py](medroute/fitness.py) |
| Seleção, cruzamento e mutação | [medroute/genetic_algorithm.py](medroute/genetic_algorithm.py), [medroute/engine.py](medroute/engine.py) |
| Fitness com distância, prioridade e restrições | [medroute/fitness.py](medroute/fitness.py) |
| Prioridades, capacidade, autonomia e múltiplos veículos | [medroute/fitness.py](medroute/fitness.py), [data/instancia_sao_paulo.json](data/instancia_sao_paulo.json) |
| Restrições adicionais: cadeia fria, prazos, jornada, frota heterogênea | [medroute/fitness.py](medroute/fitness.py) |
| Visualização das rotas em mapa | [medroute/viz_map.py](medroute/viz_map.py), [live_view.py](live_view.py) |
| Instruções para motoristas e equipes | [medroute/llm/assistant.py](medroute/llm/assistant.py), [medroute/llm/prompts.py](medroute/llm/prompts.py) |
| Relatórios diários e semanais | [medroute/metrics.py](medroute/metrics.py), [medroute/simulation.py](medroute/simulation.py) |
| Sugestões de melhoria a partir de padrões | `find_patterns` em [medroute/metrics.py](medroute/metrics.py) |
| Perguntas em linguagem natural | `ask` e `chat` em [medroute/cli.py](medroute/cli.py) |
| Site com painel de insights (adicional ao desafio) | [app.py](app.py), [medroute/web_app.py](medroute/web_app.py), [medroute/insights.py](medroute/insights.py) |
| Cadastro da operação conduzido pela LLM (adicional ao desafio) | [medroute/llm/intake_agent.py](medroute/llm/intake_agent.py), [medroute/intake.py](medroute/intake.py) |
| Comparativo com outras abordagens | [medroute/baselines.py](medroute/baselines.py), [medroute/experiments.py](medroute/experiments.py) |
| Testes automatizados | [tests/](tests/) |
| Documentação e diagramas | [docs/arquitetura.md](docs/arquitetura.md) |
| Relatório técnico | [docs/relatorio_tecnico.md](docs/relatorio_tecnico.md) |
| Roteiro do vídeo | [docs/roteiro_video.md](docs/roteiro_video.md) |

## Instalação

Use Python 3.14, a versão em que os resultados registrados foram gerados. No Python 3.15, o projeto também funciona, mas o `ortools` ainda não tem pacote: `requirements.txt` pula essa dependência, e o comparativo sai sem a linha do OR-Tools, com um aviso. No Windows, o gerenciador do Python instala a versão indicada com `py install 3.14`.

A visualização ao vivo usa o `pygame-ce`, substituto direto do `pygame`, que tem pacotes para as versões recentes do Python. O código continua com `import pygame`.

No Windows (PowerShell), a partir desta pasta:

```powershell
py -V:3.14 -m venv $env:USERPROFILE\.venvs\medroute
& $env:USERPROFILE\.venvs\medroute\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

O ambiente fica fora do projeto de propósito: dentro de uma pasta do OneDrive, os milhares de arquivos do `.venv` seriam sincronizados.

No Linux ou macOS:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Como usar

### Site

```powershell
streamlit run app.py
```

O site abre em `http://localhost:8501` e tem quatro páginas:

- **Novo planejamento:** o cadastro em conversa com a LLM, com os dados e as pendências sempre à vista. Quem não tem chave pode abrir o exemplo de São Paulo.
- **Painel do dia:** indicadores, alertas com o que fazer, comparação com o despacho simples, mapa, uso dos limites de cada veículo, entregas com menos folga e custo por veículo.
- **Visão da semana:** simula cinco dias com a frota cadastrada e mostra padrões de atraso, de uso e de pico. A demanda é sintética, e a página informa isso.
- **Assistente:** perguntas, instruções aos motoristas, relatórios e sugestões. O texto só é gerado quando você pede.

Os alertas vêm de regras em Python ([medroute/insights.py](medroute/insights.py)), não da LLM: funcionam sem chave e não inventam números.

> O site não tem login e usa a chave de API da máquina. Por isso, ele atende apenas `localhost`. Não o publique na internet sem antes acrescentar autenticação.

### Demonstração completa

```powershell
python demo.py --quick    # orçamento pequeno, para testar a instalação
python demo.py            # orçamento completo
```

A demonstração gera o plano, simula a semana e chama todas as funções do assistente. Os arquivos ficam em `outputs/`. Abra `outputs/rotas.html` no navegador para ver o mapa.

### Comandos

| Comando | O que faz |
| --- | --- |
| `python -m medroute intake` | Conversa com a LLM para cadastrar a operação e, depois de confirmada, otimiza as rotas |
| `python -m medroute solve` | Otimiza as rotas. Gera `plan.json`, `rotas.html`, `convergencia.png` e `rotas_por_veiculo.png` |
| `python -m medroute compare` | Compara o AG com despacho sequencial, vizinho mais próximo e OR-Tools |
| `python -m medroute simulate-week` | Simula uma semana. Gera `historico.json` e `semana_distancia.png` |
| `python -m medroute instructions --vehicle V1` | Gera as instruções de um veículo; sem `--vehicle`, de todos |
| `python -m medroute report --period daily` | Gera o relatório diário |
| `python -m medroute report --period weekly` | Gera o relatório semanal |
| `python -m medroute improve` | Sugere melhorias a partir do histórico |
| `python -m medroute ask "Qual veículo leva a insulina?"` | Responde a uma pergunta |
| `python -m medroute chat` | Abre uma conversa no terminal |
| `python -m medroute llm-models` | Lista os modelos do provedor |

### Cadastro assistido

```powershell
python -m medroute intake            # cadastra e otimiza
python -m medroute intake --resume   # continua um cadastro interrompido
```

A LLM pede tudo o que o otimizador precisa: centro de distribuição, horário de saída, jornada, cada veículo (capacidade, autonomia, velocidade, custo por km, refrigeração) e cada entrega (destino, tipo, item, peso, prioridade, prazo, tempo de atendimento, refrigeração). Nenhum limitador tem valor padrão.

O Python, e não a LLM, decide o que falta. Ele recusa a finalização enquanto houver pendências ou dados impossíveis, como uma carga que não cabe em nenhum veículo, e mostra um resumo para o usuário confirmar. O resultado fica em `outputs/instancia.json`, no mesmo formato de `data/instancia_sao_paulo.json`.

Os endereços são convertidos em coordenadas pelo Nominatim, do OpenStreetMap. Com `--geocoder none`, só coordenadas são aceitas, e nada é enviado a esse serviço. O que você digita vai para a API do Gemini, por isso use dados fictícios e nunca informe dados de pacientes. Nas entregas domiciliares, a LLM pede só a rua ou o bairro.

Parâmetros comuns:

- `solve`, `compare`, `simulate-week` e `intake`: `--output`, `--seed`, `--population`, `--generations`. Os três primeiros também aceitam `--instance`.
- Comandos de texto: `--llm`, `--model` e, quando faz sentido, `--plan`, `--history` e `--save`.

Este projeto não tem API REST. As interfaces são o site e a linha de comando acima. Para usar como biblioteca, comece por `run_genetic_algorithm` em [medroute/engine.py](medroute/engine.py) e `RouteAssistant` em [medroute/llm/assistant.py](medroute/llm/assistant.py).

### Evolução em tempo real

```powershell
python live_view.py           # instância de São Paulo
python live_view.py --att48   # benchmark do código base
```

Abre a janela Pygame herdada do código base. Para encerrar, feche a janela ou pressione Q.

## Configuração da LLM

Copie `.env.example` para `.env` e preencha `GEMINI_API_KEY`, com uma chave criada no [Google AI Studio](https://aistudio.google.com/apikey). O projeto usa o Gemini, pelo SDK oficial do Google, e o modelo padrão é `gemini-3.5-flash-lite`, que tem plano gratuito com limites de uso.

> **Dados no plano gratuito:** o Google pode usar o conteúdo enviado para melhorar seus produtos, revisores humanos podem lê-lo, e os termos proíbem enviar informações sensíveis, confidenciais ou pessoais. Os dados deste projeto são fictícios. Para dados reais, use uma cota paga, depois de avaliar a LGPD.

| `--llm` | Variável | Modelo padrão |
| --- | --- | --- |
| `gemini` | `GEMINI_API_KEY` ou `GOOGLE_API_KEY` | `gemini-3.5-flash-lite` |
| `offline` | nenhuma | nenhum modelo: usa templates |

Os modelos disponíveis mudam com o tempo. Se o padrão for descontinuado, use `--model` ou `LLM_MODEL`, e consulte a lista com `llm-models`.

Para trocar de provedor, crie um módulo que implemente `LLMClient` e `Conversation`, de [medroute/llm/base.py](medroute/llm/base.py), e acrescente uma entrada em `PROVIDERS`, em [medroute/llm/client.py](medroute/llm/client.py). O restante do projeto não muda. Veja o exemplo em [docs/arquitetura.md](docs/arquitetura.md).

Com `--llm auto`, que é o padrão, o programa usa a chave que encontrar. Sem chave, usa o **modo offline**: um template determinístico, sempre identificado por um aviso no início do texto. O modo offline permite rodar o projeto sem chave, mas **não é uma LLM**. Para demonstrar o requisito de LLM, use o Gemini. O comando `intake` não funciona em modo offline.

Se a chamada falhar ou o modelo recusar o pedido, o programa mostra o erro. Ele não troca para o modo offline sem avisar. Ao atingir um limite do plano gratuito, repete o pedido algumas vezes antes de mostrar o erro.

## Testes e experimentos

```powershell
pytest                           # testes automatizados; não usam rede nem chave
python run_experiments.py --quick    # teste rápido; grava em outputs/quick_results
python run_experiments.py            # gera docs/results e atualiza as tabelas do relatório
```

A execução completa de `run_experiments.py` roda o algoritmo genético dezenas de vezes e leva alguns minutos. Os resultados atuais estão em [docs/results/resultados.md](docs/results/resultados.md).

## Estrutura

```text
medroute/
  models.py             entregas, veículos e problema
  data.py               leitura das instâncias e demanda diária sintética
  intake.py             dados do cadastro assistido: pendências e validação
  geocoding.py          conversão de endereços em coordenadas
  fitness.py            codificação do cromossomo e função fitness
  genetic_algorithm.py  operadores genéticos
  engine.py             laço evolutivo
  baselines.py          abordagens de comparação
  metrics.py            métricas do plano e padrões do histórico
  simulation.py         simulação da semana
  experiments.py        comparativo, ablação e sensibilidade
  insights.py           alertas do plano e da semana, em regras
  web_app.py            telas do site
  web_charts.py         gráficos do site
  viz_map.py            mapa interativo
  viz_charts.py         gráficos estáticos
  cli.py                linha de comando
  llm/                  contrato e provedores, prompts, validação, modo offline, assistente e agente de cadastro
data/                   instância de demonstração
tests/                  testes automatizados
docs/                   arquitetura, relatório, roteiro e resultados
app.py                  site (streamlit run app.py)
demo.py                 demonstração completa
run_experiments.py      experimentos do relatório
live_view.py            evolução em tempo real
```

## Limitações principais

- As distâncias são retas multiplicadas por um fator de 1,35. Não há roteamento por ruas nem trânsito em tempo real.
- As linhas do mapa ligam as paradas em reta e não mostram o caminho real.
- Cada veículo faz uma única viagem por dia, com velocidade constante.
- O texto da LLM pode conter erros. A validação confere a ordem das paradas e aponta números que não estão nos dados, mas não substitui a revisão humana.
- As instruções são logísticas. O sistema não dá orientação clínica.

Os detalhes estão no [relatório técnico](docs/relatorio_tecnico.md).

## Créditos

- O algoritmo genético deriva de `genetic_algorithm_tsp`, de Sérgio Polimante, disponibilizado pela FIAP. O `README` desse repositório cita a licença MIT, mas o arquivo `LICENSE` é CC0. O benchmark att48 vem do mesmo repositório.
- A geração de dois filhos por cruzamento e o conceito de intensidade de mutação vêm de `genetic_algorithm_camouflage`.
