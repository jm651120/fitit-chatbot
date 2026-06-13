<div align="center">

# 💪 FitBot — AI Assistant for FIT IT Gym

**A production-grade RAG chatbot that answers questions about classes, schedules, plans and prices for a real Portuguese gym — grounded exclusively in live data from [fitit.pt](https://fitit.pt/).**

### 🔗 **[LIVE DEMO → fitit-chatbot.streamlit.app](https://fitit-chatbot.streamlit.app/)**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.58-FF4B4B?logo=streamlit&logoColor=white)
![Groq](https://img.shields.io/badge/LLM-Llama%203.3%2070B%20via%20Groq-F55036)
![ChromaDB](https://img.shields.io/badge/Vector%20DB-ChromaDB-5C2D91)
![License](https://img.shields.io/badge/embeddings-100%25%20local-2EA44F)

</div>

---

## 📋 Project Overview

Gym members and prospects ask the same questions every day — *"What classes are on Monday morning?"*, *"How much is the membership?"*, *"How do I sign up?"*. FitBot answers them 24/7 in **European Portuguese**, citing real class times, instructor names and prices taken directly from the gym's website.

The hard part: **the class timetable changes every week.** A chatbot serving last week's schedule destroys user trust instantly. FitBot solves this with an automated update pipeline that re-crawls the schedule page weekly, detects changes via content hashing, and re-indexes only what changed — no human intervention required.

Built end-to-end as a real commercial project: crawling, cleaning, chunking, retrieval, generation, UI, and automated freshness.

## ✨ Key Features

- **Grounded answers, zero hallucination policy** — the system prompt forbids inventing schedules or prices; when the context lacks an answer, the bot says so honestly and renders a *"Talk to the FIT IT team →"* call-to-action.
- **Booking-widget JSON parsing** — the schedule page embeds its timetable as a raw JSON blob from the gym's booking system. FitBot parses it directly into one structured chunk per weekday (time, class, modality, instructor, studio) instead of scraping a rendered HTML table. Exact data, every time.
- **Intent-routed retrieval** — a query classifier routes schedule questions to the `schedule` collection and price questions to `pricing`; general questions search all three collections merged by relevance. Questions naming a weekday deterministically prioritise that day's chunk.
- **Conversational memory** — follow-ups like *"E ao sábado?"* are rewritten into standalone queries by a small fast model before retrieval, so multi-turn conversations just work.
- **Self-healing LLM layer** — automatic model fallback chain (Llama 3.3 70B → Llama 3.1 8B → GPT-OSS 120B) with rate-limit-aware retries; Groq decommissioning a model never takes the bot down.
- **Automated freshness** — weekly schedule refresh (Mondays 07:00) and monthly full-site re-crawl (1st of each month, 06:00), Europe/Lisbon timezone, with MD5 change detection and full audit logs.
- **100% local embeddings** — multilingual sentence-transformers model, no embedding API costs, no data leaving the machine.
- **Custom-branded UI** — FIT IT's real brand palette (gold/purple on near-black, extracted from their site), custom chat bubbles, typing indicator, quick-action buttons and a schedule-freshness badge.

## 🏗️ Architecture / Data Flow

```
            ┌────────────── APScheduler (background thread) ──────────────┐
            │   weekly: schedule page · monthly: full site · MD5 diffing  │
            ▼                                                             │
 fitit.pt ──► Firecrawl API ──► data/raw/*.md ──► cleaning + type-aware ──► ChromaDB
              (BeautifulSoup     (markdown +       chunking                ├─ schedule (per weekday)
               fallback)          frontmatter)                             ├─ pricing  (per plan)
                                                                           └─ general  (500-token chunks)
                                                                                    │
 User question ──► intent classifier ──► routed semantic search ◄──────────────────┘
      │            (schedule/pricing/general)        │
      └──► chat history ──► follow-up rewriting ─────┤
                            (Llama 3.1 8B)           ▼
                              Groq · Llama 3.3 70B (model fallback chain)
                                                     │
                                                     ▼
                                    European Portuguese answer + sources
                                    (or honest "I don't know" + contact CTA)
```

**Chunking is page-type aware:** timetables are split by weekday (a class time is never separated from its class name), each membership plan stays whole in a single chunk, each modality gets its own chunk, and general content uses ~500-token chunks with overlap. Site-wide boilerplate (menus, cookie banners, footers) is learned by cross-page frequency analysis and stripped — except on the contacts page, where the footer holds the gym's address.

## 🛠️ Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Crawling | [Firecrawl](https://firecrawl.dev) + BeautifulSoup4 fallback | Sitemap-driven discovery; stale campaign pages filtered out |
| LLM inference | [Groq](https://groq.com) — Llama 3.3 70B Versatile | Free tier; automatic fallback chain + retry on rate limits |
| Embeddings | sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` | Local & free; multilingual model chosen after the English-only default measurably failed Portuguese retrieval |
| Vector store | ChromaDB (persistent, local) | Three collections: `schedule` / `pricing` / `general` |
| Orchestration | LangChain (`langchain-groq`, text splitters) | Prompting, chunking utilities |
| Scheduling | APScheduler (background thread) | Weekly + monthly cron jobs, Europe/Lisbon |
| UI | Streamlit + extensive custom CSS | Fully branded, no default styling |
| Config | python-dotenv | Keys in `.env`, template in `.env.example` |

## 🚀 Local Setup

Prerequisites: Python 3.11+, free [Firecrawl](https://firecrawl.dev) and [Groq](https://console.groq.com) accounts.

```bash
git clone <repo-url>
cd fitit-chatbot

python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

copy .env.example .env            # then fill in your keys:
# FIRECRAWL_API_KEY=fc-...
# GROQ_API_KEY=gsk_...

python ingest.py                  # crawl + chunk + index (~5–10 min first run)
streamlit run app.py
```

Useful commands:

```bash
python ingest.py --skip-crawl          # re-index without re-crawling
python scripts/validate.py             # run the 10-question acceptance suite
python scripts/validate.py --followup  # + conversational memory test
```

## ☁️ Deployment & Automated Updates

The **[live demo](https://fitit-chatbot.streamlit.app/)** runs on Streamlit Community Cloud:

1. The repo ships with a **pre-built ChromaDB index** (`chroma_db/` is committed), because Streamlit Cloud's filesystem is ephemeral — the app boots ready to answer without crawling.
2. API keys are injected via **App settings → Secrets** (TOML format); `python-dotenv` quietly ignores the missing `.env`.
3. While the app is awake, APScheduler runs in a background thread:

| Job | When | What it does |
|---|---|---|
| **Weekly schedule refresh** | Mondays 07:00 (Lisbon) | Re-crawls only the timetable page, compares MD5 hashes against `data/logs/hashes.json`; on change, rebuilds the `schedule` collection and updates the freshness badge. Otherwise logs "no changes detected". |
| **Monthly full re-crawl** | 1st of month, 06:00 | Re-crawls the whole site, re-indexes only pages whose hash changed, writes a change report to `data/logs/`. |

The last schedule sync time is always visible in the app's sidebar.

## ⚠️ Project Limitations / Known Issues

- **Groq free-tier rate limits** — large schedule contexts can hit the tokens-per-minute cap (HTTP 429). Mitigated by the model fallback chain with pauses, but under heavy traffic an occasional "technical difficulties" answer can still surface.
- **Scheduler vs. hibernation** — APScheduler only runs while the app process is alive. Streamlit Community Cloud hibernates idle apps, so the hosted demo's Monday-07:00 refresh fires only if the app is awake (a `misfire_grace_time` lets it catch up if woken later the same day). For guaranteed freshness, the cron must live outside the app (see Next Steps).
- **Ephemeral cloud filesystem** — index updates performed on Streamlit Cloud don't survive a restart; the app reverts to the committed snapshot. Acceptable for a demo, not for production hosting.
- **Booking-widget coupling** — the per-weekday schedule parsing depends on the JSON format embedded by the gym's booking widget. If that format changes, the system degrades gracefully to text-based chunking, but per-day precision may drop until the parser is updated.
- **Read-only assistant** — FitBot informs; it cannot book classes or manage memberships (no integration with the gym's member system).
- **Demo snapshot staleness** — the live demo answers from the index committed at deploy time; prices/schedule reflect the site as of the last ingest run.

## 🔮 Next Steps / Future Improvements

- **Decouple the cron from the app** — run the weekly update via GitHub Actions (`python -c "from src.updater import update_schedule; update_schedule()"`) and commit/push the refreshed index, making freshness independent of app uptime.
- **Conversation telemetry** — log anonymised questions, retrieval hits/misses and "no info" rates to find content gaps and measure answer quality over time; add 👍/👎 feedback buttons.
- **Booking integration** — connect to the gym's member portal (MY FIT IT) so users can jump from "what classes are on Monday?" to actually reserving a spot.
- **Retrieval upgrades** — add a cross-encoder re-ranker and hybrid (BM25 + dense) search for even sharper precision on price-table questions.
- **Streaming responses** — token-by-token streaming in the UI for perceived speed.
- **Multi-tenant white-label** — the crawl → chunk → route → answer pipeline is gym-agnostic; parametrise branding and URLs to serve other local businesses.
- **Docker image** — one-command self-hosted deployment with a persistent volume, solving the ephemeral-filesystem and hibernation limits at once.

__________________________

<div align="center">

# 💪 FitBot — Assistente de IA do Ginásio FIT IT

**Um chatbot RAG de nível de produção que responde a perguntas sobre aulas, horários, planos e preços de um ginásio português real — baseado exclusivamente em dados reais de [fitit.pt](https://fitit.pt/).**

### 🔗 **[DEMO AO VIVO → fitit-chatbot.streamlit.app](https://fitit-chatbot.streamlit.app/)**

</div>

---

## 📋 Visão Geral do Projeto

Os sócios (e potenciais sócios) de um ginásio fazem todos os dias as mesmas perguntas — *"Que aulas há na segunda de manhã?"*, *"Quanto custa a mensalidade?"*, *"Como me inscrevo?"*. O FitBot responde-lhes 24/7 em **português europeu**, citando horários de aulas, nomes de instrutores e preços retirados diretamente do site do ginásio.

A parte difícil: **o mapa de aulas muda todas as semanas.** Um chatbot que sirva o horário da semana passada destrói instantaneamente a confiança dos utilizadores. O FitBot resolve isto com um pipeline de atualização automática que faz re-crawl semanal da página do horário, deteta alterações por hashing de conteúdo e re-indexa apenas o que mudou — sem qualquer intervenção humana.

Construído de ponta a ponta como projeto comercial real: crawling, limpeza, chunking, pesquisa, geração, interface e atualização automática.

## ✨ Funcionalidades Principais

- **Respostas fundamentadas, política de zero alucinação** — o system prompt proíbe inventar horários ou preços; quando o contexto não contém a resposta, o bot admite-o honestamente e mostra um botão *"Falar com a equipa FIT IT →"*.
- **Parsing do JSON do widget de reservas** — a página do horário incorpora o mapa de aulas como um bloco JSON do sistema de reservas do ginásio. O FitBot interpreta-o diretamente, gerando um chunk estruturado por dia da semana (hora, aula, modalidade, instrutor, estúdio) em vez de raspar uma tabela HTML renderizada. Dados exatos, sempre.
- **Pesquisa encaminhada por intenção** — um classificador de intenção encaminha perguntas de horário para a coleção `schedule` e perguntas de preço para `pricing`; perguntas gerais pesquisam as três coleções com fusão por relevância. Perguntas que mencionam um dia da semana priorizam deterministicamente o chunk desse dia.
- **Memória conversacional** — follow-ups como *"E ao sábado?"* são reescritos como perguntas independentes por um modelo pequeno e rápido antes da pesquisa, pelo que conversas com várias trocas funcionam naturalmente.
- **Camada LLM resiliente** — cadeia automática de fallback de modelos (Llama 3.3 70B → Llama 3.1 8B → GPT-OSS 120B) com retries sensíveis a limites de tráfego; a descontinuação de um modelo pela Groq nunca derruba o bot.
- **Frescura automática** — atualização semanal do horário (segundas-feiras às 07:00) e re-crawl mensal completo do site (dia 1 de cada mês às 06:00), fuso Europe/Lisbon, com deteção de alterações por MD5 e registos de auditoria completos.
- **Embeddings 100% locais** — modelo multilingue de sentence-transformers, sem custos de API de embeddings, sem dados a sair da máquina.
- **Interface com a marca do clube** — paleta real do FIT IT (dourado/roxo sobre quase-preto, extraída do site), bolhas de chat personalizadas, indicador de escrita, botões de ação rápida e selo de frescura do horário.

## 🏗️ Arquitetura / Fluxo de Dados

```
            ┌────────────── APScheduler (thread em background) ───────────┐
            │  semanal: página do horário · mensal: site completo · MD5   │
            ▼                                                             │
 fitit.pt ──► API Firecrawl ──► data/raw/*.md ──► limpeza + chunking ─────► ChromaDB
              (fallback          (markdown +      por tipo de página       ├─ schedule (por dia da semana)
               BeautifulSoup)     frontmatter)                             ├─ pricing  (por plano)
                                                                           └─ general  (chunks ~500 tokens)
                                                                                    │
 Pergunta ──► classificador de intenção ──► pesquisa semântica encaminhada ◄───────┘
      │       (horário/preços/geral)                 │
      └──► histórico ──► reescrita de follow-ups ────┤
                         (Llama 3.1 8B)              ▼
                            Groq · Llama 3.3 70B (cadeia de fallback)
                                                     │
                                                     ▼
                                  resposta em português europeu + fontes
                                  (ou um honesto "não sei" + botão de contacto)
```

**O chunking é consciente do tipo de página:** os horários são divididos por dia da semana (a hora de uma aula nunca se separa do nome da aula), cada plano de adesão fica inteiro num único chunk, cada modalidade tem o seu próprio chunk e o conteúdo geral usa chunks de ~500 tokens com sobreposição. O boilerplate transversal ao site (menus, banners de cookies, rodapés) é aprendido por análise de frequência entre páginas e removido — exceto na página de contactos, onde o rodapé contém a morada do ginásio.

## 🛠️ Stack Tecnológica

| Camada | Tecnologia | Notas |
|---|---|---|
| Crawling | [Firecrawl](https://firecrawl.dev) + fallback BeautifulSoup4 | Descoberta via sitemap; páginas de campanhas antigas filtradas |
| Inferência LLM | [Groq](https://groq.com) — Llama 3.3 70B Versatile | Plano gratuito; cadeia de fallback automática + retry em limites de tráfego |
| Embeddings | sentence-transformers `paraphrase-multilingual-MiniLM-L12-v2` | Locais e gratuitos; o modelo multilingue foi escolhido depois de o modelo só-inglês falhar mensuravelmente na pesquisa em português |
| Base vetorial | ChromaDB (persistente, local) | Três coleções: `schedule` / `pricing` / `general` |
| Orquestração | LangChain (`langchain-groq`, text splitters) | Prompting e utilitários de chunking |
| Agendamento | APScheduler (thread em background) | Jobs semanais + mensais, Europe/Lisbon |
| Interface | Streamlit + CSS personalizado extensivo | Totalmente com a identidade do clube, sem estilos por omissão |
| Configuração | python-dotenv | Chaves em `.env`, modelo em `.env.example` |

## 🚀 Instalação Local

Pré-requisitos: Python 3.11+, contas gratuitas [Firecrawl](https://firecrawl.dev) e [Groq](https://console.groq.com).

```bash
git clone <url-do-repositorio>
cd fitit-chatbot

python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt

copy .env.example .env            # e preencher as chaves:
# FIRECRAWL_API_KEY=fc-...
# GROQ_API_KEY=gsk_...

python ingest.py                  # crawl + chunking + indexação (~5–10 min na primeira execução)
streamlit run app.py
```

Comandos úteis:

```bash
python ingest.py --skip-crawl          # re-indexar sem voltar a fazer crawl
python scripts/validate.py             # correr a bateria de 10 perguntas de aceitação
python scripts/validate.py --followup  # + teste de memória conversacional
```

## ☁️ Deployment e Atualizações Automáticas

A **[demo ao vivo](https://fitit-chatbot.streamlit.app/)** corre no Streamlit Community Cloud:

1. O repositório inclui um **índice ChromaDB pré-construído** (a pasta `chroma_db/` está versionada), porque o sistema de ficheiros do Streamlit Cloud é efémero — a app arranca pronta a responder sem fazer crawl.
2. As chaves de API são injetadas via **App settings → Secrets** (formato TOML); o `python-dotenv` ignora silenciosamente a ausência do `.env`.
3. Enquanto a app está ativa, o APScheduler corre numa thread em background:

| Tarefa | Quando | O que faz |
|---|---|---|
| **Atualização semanal do horário** | Segundas-feiras, 07:00 (Lisboa) | Faz re-crawl apenas da página do mapa de aulas e compara hashes MD5 com `data/logs/hashes.json`; se houver alterações, reconstrói a coleção `schedule` e atualiza o selo de frescura. Caso contrário, regista "no changes detected". |
| **Re-crawl mensal completo** | Dia 1 de cada mês, 06:00 | Faz re-crawl do site inteiro, re-indexa apenas as páginas cujo hash mudou e escreve um relatório de alterações em `data/logs/`. |

A data da última sincronização do horário está sempre visível na barra lateral da app.

## ⚠️ Limitações do Projeto / Problemas Conhecidos

- **Limites do plano gratuito da Groq** — contextos grandes de horário podem atingir o limite de tokens por minuto (HTTP 429). O impacto é mitigado pela cadeia de fallback com pausas, mas sob tráfego intenso pode ainda surgir ocasionalmente uma resposta de "dificuldades técnicas".
- **Scheduler vs. hibernação** — o APScheduler só corre enquanto o processo da app está vivo. O Streamlit Community Cloud hiberna apps inativas, pelo que a atualização de segunda-feira às 07:00 da demo alojada só dispara se a app estiver acordada (um `misfire_grace_time` permite recuperar se a app acordar mais tarde no mesmo dia). Para frescura garantida, o cron tem de viver fora da app (ver Próximos Passos).
- **Sistema de ficheiros efémero na cloud** — atualizações ao índice feitas no Streamlit Cloud não sobrevivem a um restart; a app regressa ao snapshot versionado. Aceitável para uma demo, não para alojamento em produção.
- **Acoplamento ao widget de reservas** — o parsing do horário por dia da semana depende do formato JSON incorporado pelo widget de reservas do ginásio. Se esse formato mudar, o sistema degrada graciosamente para chunking por texto, mas a precisão por dia pode baixar até o parser ser atualizado.
- **Assistente apenas de leitura** — o FitBot informa; não consegue reservar aulas nem gerir adesões (não há integração com o sistema de sócios do ginásio).
- **Desatualização do snapshot da demo** — a demo ao vivo responde a partir do índice versionado no momento do deploy; preços e horário refletem o site à data da última ingestão.

## 🔮 Próximos Passos / Melhorias Futuras

- **Separar o cron da app** — correr a atualização semanal via GitHub Actions (`python -c "from src.updater import update_schedule; update_schedule()"`) e fazer commit/push do índice atualizado, tornando a frescura independente do uptime da app.
- **Telemetria de conversas** — registar perguntas anonimizadas, acertos/falhas de pesquisa e taxas de "sem informação" para encontrar lacunas de conteúdo e medir a qualidade das respostas ao longo do tempo; adicionar botões de feedback 👍/👎.
- **Integração de reservas** — ligar ao portal de sócios do ginásio (MY FIT IT) para o utilizador passar de "que aulas há na segunda?" para reservar efetivamente um lugar.
- **Melhorias de pesquisa** — adicionar um re-ranker cross-encoder e pesquisa híbrida (BM25 + densa) para precisão ainda maior em perguntas sobre tabelas de preços.
- **Respostas em streaming** — streaming token a token na interface para maior velocidade percebida.
- **White-label multi-cliente** — o pipeline crawl → chunking → encaminhamento → resposta é agnóstico ao ginásio; parametrizar a identidade visual e os URLs permite servir outros negócios locais.
- **Imagem Docker** — deployment self-hosted com um único comando e volume persistente, resolvendo de uma vez os limites do sistema de ficheiros efémero e da hibernação.
