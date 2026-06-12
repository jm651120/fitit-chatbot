# FitBot — Chatbot RAG para o FIT IT 💪

Assistente virtual inteligente para o ginásio [FIT IT](https://fitit.pt/), construído com
RAG (Retrieval-Augmented Generation). Responde em português europeu a perguntas sobre
aulas, horários, planos, preços, inscrições e contactos — usando **exclusivamente
informação real do site fitit.pt**, nunca inventada.

## Porquê

Os membros (e potenciais membros) de um ginásio fazem sempre as mesmas perguntas:
*"Que aulas há na segunda de manhã?"*, *"Quanto custa o plano?"*, *"Como me inscrevo?"*.
O FitBot responde a isso 24/7 com dados reais do site — e como o **mapa de aulas muda
todas as semanas**, inclui um sistema de atualização automática que mantém o horário
sempre fresco sem intervenção humana.

## Como funciona

```
fitit.pt ──Firecrawl/BS4──> data/raw/*.md ──limpeza+chunking──> ChromaDB (3 coleções)
                                                                   │ schedule │ pricing │ general │
Utilizador ──pergunta──> classificador de intenção ──pesquisa semântica──> contexto
                  └──histórico de conversa──> Groq (Llama 3.3 70B) ──> resposta pt-PT
```

1. **Crawling** — o site é descoberto via sitemap, filtrado (páginas de campanhas
   antigas são excluídas) e extraído com a API Firecrawl; se uma página falhar,
   há fallback automático para BeautifulSoup.
2. **Ingestão** — limpeza agressiva de menus/cookies/rodapés (boilerplate aprendido
   por frequência entre páginas) e chunking consciente do tipo de página:
   horários divididos por dia (hora + aula nunca se separam), planos de preços
   inteiros num só chunk, uma modalidade por chunk.
3. **Pesquisa** — embeddings locais (`paraphrase-multilingual-MiniLM-L12-v2`; o
   `all-MiniLM-L6-v2` original é só-inglês e classificava pior o conteúdo português,
   validado empiricamente) em três coleções ChromaDB; um classificador de intenção
   encaminha perguntas de horário/preço para a coleção certa. Perguntas sobre um dia
   específico priorizam deterministicamente o chunk desse dia. Follow-ups
   ("e ao sábado?") são reescritos como perguntas independentes.
4. **Geração** — Groq API (Llama 3.3 70B, com fallback automático de modelos) com um
   system prompt que obriga a respostas pt-PT fiéis ao contexto; quando não sabe,
   admite e aponta para os contactos do ginásio.

## Setup

Pré-requisitos: Python 3.11+, conta gratuita [Firecrawl](https://firecrawl.dev) e [Groq](https://console.groq.com).

```bash
git clone <repo-url>
cd fitit-chatbot

python -m venv .venv
.venv\Scripts\activate          # Windows (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

copy .env.example .env          # e preencher as chaves:
# FIRECRAWL_API_KEY=fc-...
# GROQ_API_KEY=gsk_...

python ingest.py                # crawl + indexação (~5-10 min na primeira vez)
streamlit run app.py
```

Comandos úteis:

```bash
python ingest.py --skip-crawl     # re-indexar sem voltar a fazer crawl
python scripts/validate.py        # correr as 10 perguntas de validação
python scripts/validate.py --followup   # + teste de memória conversacional
```

## Sistema de atualização automática do horário

O mapa de aulas do FIT IT muda semanalmente — um chatbot com horário desatualizado
destrói a confiança dos membros. Por isso, com a app a correr, o APScheduler executa
em background (fuso Europe/Lisbon):

| Tarefa | Quando | O que faz |
|---|---|---|
| **Refresh semanal do horário** | Segunda-feira, 07:00 | Re-crawl apenas das páginas de horário; compara o hash MD5 com `data/logs/hashes.json`; se mudou, apaga a coleção `schedule`, re-indexa e atualiza o hash. Se não mudou, regista "no changes detected". |
| **Re-crawl mensal completo** | Dia 1 de cada mês, 06:00 | Re-crawl do site inteiro; re-indexa apenas as páginas cujo hash mudou; escreve um relatório de alterações em `data/logs/`. |

A data da última atualização do horário está sempre visível na barra lateral da app.
Os jobs têm `misfire_grace_time` — se a app estiver fechada às 07:00 de segunda e
abrir mais tarde nesse dia, a atualização ainda corre.

## Deploy no Streamlit Community Cloud

1. Faz push do repositório para o GitHub (o `.gitignore` já exclui `.env`, `chroma_db/` e `data/`).
2. Em [share.streamlit.io](https://share.streamlit.io) cria uma app apontando para `app.py`.
3. Em **App settings → Secrets**, adiciona:
   ```toml
   FIRECRAWL_API_KEY = "fc-..."
   GROQ_API_KEY = "gsk_..."
   ```
   (`python-dotenv` ignora o `.env` em falta; o Streamlit Cloud injeta secrets como variáveis de ambiente.)
4. Como o filesystem do Streamlit Cloud é efémero, na primeira execução a app avisa
   que o índice está vazio — corre `python ingest.py` localmente e faz commit de uma
   versão do `chroma_db/` **ou** executa a ingestão no arranque da app (para um demo,
   o mais simples é remover `chroma_db/` do `.gitignore` e versioná-lo).

> Nota: no plano gratuito a app hiberna quando não é usada; os updates agendados só
> correm com a app acordada. Para produção a sério, considerar um VPS pequeno ou
> GitHub Actions a correr `python -c "from src.updater import update_schedule; update_schedule()"`
> às segundas.

## Tecnologias

- **[Firecrawl](https://firecrawl.dev)** — crawling do site para markdown limpo
- **BeautifulSoup4** — scraper de fallback
- **[Groq](https://groq.com)** — inferência LLM (Llama 3.3 70B Versatile, free tier)
- **LangChain** (`langchain-groq`, text splitters) — orquestração do LLM e chunking
- **sentence-transformers** (`paraphrase-multilingual-MiniLM-L12-v2`) — embeddings 100% locais e multilingues, sem custos
- **ChromaDB** — base de dados vetorial persistente local
- **APScheduler** — atualizações automáticas semanais/mensais
- **Streamlit** — interface de chat com tema personalizado FIT IT

## Estrutura

```
fitit-chatbot/
  data/raw/          páginas extraídas (markdown + frontmatter)
  data/processed/    chunks limpos por página
  data/logs/         crawl_log.txt, update_log.txt, hashes.json, relatórios
  chroma_db/         índice vetorial persistente
  src/
    crawler.py       Firecrawl REST + fallback BeautifulSoup + classificação de páginas
    ingestion.py     limpeza, chunking por tipo de página, indexação
    vectorstore.py   ChromaDB (3 coleções) + embeddings locais
    retrieval.py     classificação de intenção + pesquisa encaminhada
    generation.py    Groq/Llama, persona FitBot, fallback de modelos, reescrita de follow-ups
    updater.py       deteção de alterações por hash MD5 + re-indexação seletiva
    scheduler.py     jobs APScheduler (semanal + mensal)
  app.py             interface Streamlit
  ingest.py          setup inicial: crawl + chunk + index
  scripts/validate.py  validação das 10 perguntas de aceitação
```
