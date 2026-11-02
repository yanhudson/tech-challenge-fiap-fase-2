# Resultados dos experimentos

Gerados por `run_experiments.py`, com 10 sementes no comparativo.

## Comparativo entre métodos

| Método | Execuções | Fitness média | Desvio | Melhor fitness | Distância (km) | Custo (R$) | Tempo em rota (min) | Veículos | No prazo (%) | Críticas no prazo (%) | Execuções viáveis | Tempo de execução (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Despacho sem otimização | 1 | 41.870,0 | 0,0 | 41.870,0 | 428,7 | 865,47 | 1.260,2 | 4 | 70,0 | 37,5 | 1 | 0,00 |
| Vizinho mais próximo | 1 | 17.258,0 | 0,0 | 17.258,0 | 294,0 | 555,82 | 975,2 | 4 | 73,3 | 37,5 | 1 | 0,00 |
| OR-Tools | 1 | 420,8 | 0,0 | 420,8 | 232,3 | 416,76 | 842,0 | 5 | 100,0 | 100,0 | 1 | 30,05 |
| Algoritmo genético | 10 | 438,8 | 8,4 | 430,6 | 255,0 | 451,16 | 886,4 | 4,9 | 100,0 | 100,0 | 10 | 1,94 |

## Efeito de cada correção no att48

| Variante | Execuções | Distância média | Desvio | Melhor distância | Acima do ótimo (%) | Tempo de execução (s) |
| --- | --- | --- | --- | --- | --- | --- |
| Código base (sem cruzamento efetivo) | 5 | 86.563,9 | 3.917,0 | 80.687,4 | 158,2 | 1,86 |
| Base + OX corrigido | 5 | 64.931,5 | 5.254,3 | 59.453,9 | 93,7 | 2,14 |
| Base + OX + novas mutações | 5 | 61.140,5 | 6.333,2 | 56.355,5 | 82,4 | 2,21 |
| Base + OX + novas mutações + torneio e elitismo de 4 | 5 | 35.478,9 | 898,9 | 34.764,1 | 5,8 | 2,29 |
| Todas as anteriores + vizinho mais próximo | 5 | 35.023,2 | 429,8 | 34.405,5 | 4,5 | 2,28 |

## Sensibilidade aos parâmetros

| Configuração | Execuções | Fitness média | Desvio | Melhor fitness | Distância (km) | Custo (R$) | Tempo em rota (min) | Veículos | No prazo (%) | Críticas no prazo (%) | Execuções viáveis | Tempo de execução (s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Referência | 5 | 437,2 | 5,6 | 430,6 | 253,1 | 443,77 | 880,5 | 5 | 100,0 | 100,0 | 5 | 1,97 |
| População de 100 | 5 | 445,9 | 14,6 | 437,6 | 247,7 | 464,40 | 877,0 | 4,6 | 100,0 | 100,0 | 5 | 1,07 |
| População de 400 | 5 | 439,7 | 10,5 | 425,7 | 245,6 | 443,95 | 871,0 | 4,8 | 100,0 | 100,0 | 5 | 4,41 |
| Mutação de 20% | 5 | 442,3 | 18,3 | 421,8 | 253,4 | 457,40 | 886,4 | 4,8 | 100,0 | 100,0 | 5 | 2,52 |
| Mutação de 80% | 5 | 437,9 | 10,5 | 426,6 | 253,4 | 448,34 | 883,3 | 5 | 100,0 | 100,0 | 5 | 2,62 |
| Cruzamento PMX | 5 | 444,6 | 13,1 | 430,0 | 247,2 | 439,57 | 871,9 | 4,8 | 100,0 | 100,0 | 5 | 1,97 |
| Seleção por roleta | 5 | 444,2 | 10,5 | 432,3 | 256,8 | 453,63 | 890,9 | 5 | 100,0 | 100,0 | 5 | 2,69 |
| Elitismo de 1 | 5 | 445,9 | 13,4 | 431,3 | 254,2 | 464,26 | 888,2 | 4,6 | 100,0 | 100,0 | 5 | 2,27 |
| Sem semente do vizinho mais próximo | 5 | 441,6 | 8,3 | 432,4 | 259,9 | 457,31 | 897,4 | 5 | 100,0 | 100,0 | 5 | 1,96 |
| Sem promoção de prioridade | 5 | 448,1 | 28,1 | 423,1 | 255,5 | 443,36 | 886,2 | 4,8 | 100,0 | 100,0 | 5 | 1,92 |

## Semana simulada

| Data | Dia | Entregas | Distância do AG (km) | Distância da referência (km) | Críticas no prazo (%) |
| --- | --- | --- | --- | --- | --- |
| 2026-11-02 | segunda-feira | 26 | 221,4 | 381,2 | 100,0 |
| 2026-11-03 | terça-feira | 25 | 218,2 | 350,0 | 100,0 |
| 2026-11-04 | quarta-feira | 25 | 213,5 | 417,6 | 100,0 |
| 2026-11-05 | quinta-feira | 24 | 224,7 | 390,1 | 100,0 |
| 2026-11-06 | sexta-feira | 25 | 231,6 | 347,5 | 100,0 |

**Total do período:** 125 entregas e 1.109,4 km. Em relação à referência simulada: 777,0 km a menos (41,2%), R$ 1.991,14 a menos (49,4%) e 1.649,9 min a menos em rota (30,1%). Dias com violação de restrição: 0.
