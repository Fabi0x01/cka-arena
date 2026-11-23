# CKA Arena — Simulador Local & Gerador de Cenários CKA via LLM

> **English quickstart** — the rest of this README is in Portuguese (pt-BR).

## Quickstart (English)

One command provisions a real 3-node Kubernetes lab, seeds the question bank and
starts the platform:

```bash
git clone https://github.com/Fabi0x01/cka-arena.git && cd cka-arena
./setup.sh
```

The script detects your OS/distro, audits prerequisites and **asks before installing**
anything missing (`--yes` to skip prompts, `--check` to audit only). Supported:

| Environment | Lab driver |
| :--- | :--- |
| macOS (arm64/x86_64) | Multipass VMs (bridged network) |
| Ubuntu / Debian (x86_64/arm64) | Multipass VMs (bridged network) |
| **WSL2 (Windows 11, systemd)** | **kind containers inside WSL** (no Docker Desktop, no nested VM) |
| Fedora / Arch | best effort (Multipass when available) |

When it finishes it prints the URL to open — normally **http://127.0.0.1:8765** —
plus what you can optionally configure:

- **AI generation (optional):** open **Settings → AI provider**, pick a provider
  (GLM, DeepSeek, OpenCode, Anthropic, OpenAI-compatible), pick a **model from the
  dropdown** (presets ship the current model lineup), paste your key and hit
  **Test connection**. The key is stored locally in `llm_config.json` (git-ignored,
  masked in the UI) — or edit `llm_config.example.json` manually. Practice from the
  bundled seed bank works without it.
- **Lab password:** VMs use `ubuntu` / `ubuntu` (override with `CKA_LAB_PASSWORD`).
- **Power:** stop/start the lab from the header pill.

Requirements: ~16 GB RAM, ~30 GB free disk, and a virtualized/bridged network for
the VMs (WSL2 uses Docker instead). Logs: `~/.cka-arena/setup.log`.

### Portable DB Backup & Auto-Restore (macOS / WSL2)

The repository ships a sanitized SQLite snapshot at `backups/cka_arena_backup.db`
containing published question bank scenarios, CKA Study Codex progress, archetype
mastery, and finished session history — **without any API keys** (`llm_config.json`
remains local and git-ignored).

- **Fresh machine / WSL2 clone:** when `data/cka_arena.db` does not exist yet,
  starting the app (or running `./setup.sh`) automatically restores `backups/cka_arena_backup.db`.
- **Save current progress before pushing from this machine:**
  ```bash
  uv run python -m app.backup create
  ```
- **Force-restore pulled snapshot onto an already-initialized machine:**
  ```bash
  uv run python -m app.backup restore --force
  ```

---

Plataforma web local para treinar **Certified Kubernetes Administrator (CKA)** em ritmo acelerado no seu próprio cluster `kubeadm` multi-nó em macOS, Linux ou WSL2 (Multipass ou kind) — combinando o rigor de validação automática de **KodeKloud** e **Killer.sh** com um **Gerador de Cenários via LLM**, um **terminal real embutido no navegador** (PTY do host em xterm.js) e **gestão do ciclo de vida do cluster** (ligar/desligar as VMs Multipass no botão). A LLM cria tarefas práticas reais (YAMLs, falhas de control plane, rede, storage, Helm/Kustomize e Gateway API), aplica no cluster e a plataforma valida a resolução com checks determinísticos em tempo real.

> **Status do Projeto:** **Fases 1–5 concluídas e verificadas** (17/11/2026) — Power ring/Doctor/SSH bridge · ScenarioEngine (10 check types, teardown L0/L1/L2) · pipeline de geração A→E (Solvability Probe) · UI integrada Liquid Glass com terminal real no browser · **15 seeds validados no cluster** (todos os domínios) · **telemetria/dashboard por domínio** e **bootstrap de addons**. **Addons instalados** (metrics-server, Gateway API 1.2 + Envoy Gateway v1.2.0, local-path-provisioner; weave-npc detectado como container do weave-net) e **L2-clean validado** com eles (snapshots de VM não são suportados no Multipass/macOS). Banco com **21 questões publicadas**; **17 seeds** validados (`validate` = 17/17 PROBE OK, incluindo NetworkPolicy com egress DNS e Gateway API HTTPRoute); 41 testes verdes.

---

## Fluxo de Trabalho (Janela Única com Terminal Integrado)

A plataforma concentra **tudo no navegador** (`http://127.0.0.1:8765`) — o terminal nativo (iTerm2/Ghostty) continua disponível como modo opcional:

1. **Coluna Esquerda (~44% · Questão):** enunciado em **inglês no formato exato da prova** (anatomia killer.sh/PSI: título imperativo, contexto-sintoma, "Perform the following tasks", restrições — o sistema é 100% English), domínio e peso na prova, cronômetro, pills copiáveis com 1 clique, botão **`Check`** e botão **`Next`** (travado até 100% dos critérios do cluster estarem corretos).
2. **Coluna Direita (~56% · Terminal no Browser):** terminal **real** do host Mac (PTY `zsh -l` renderizado em xterm.js) com abas `mac · controlplane · node01 · node02` — você resolve a tarefa com `kubectl`, `vim`, `helm` e `ssh` ali mesmo e clica no **Check da barra do terminal**, sem trocar de painel.
3. **Cluster no botão:** pill de estado no header (`● Ready 3/3` / `⏻ Off`) e CTA **"Power On & Practice"** — a plataforma sobe as VMs Multipass com boot instrumentado (VMs → SSH → API → nós → baseline) antes de liberar os cenários.
4. **Estúdio de Cenários IA (publica no Banco):** marque domínios/sub-tópicos, escolha o nível (`Exam Standard`, `Killer.sh Hardcore`, `Boss Fight` — **rubricas mensuráveis e distintas**, `LLM_SCENARIO_SPEC.md` §5) e o pipeline multi-agente (Normalizador → Construtor → Revisor → gates determinísticos → prove-out no cluster com **Solvability Probe**) publica questões **comprovadamente solúveis, em inglês no formato do exame**, no banco de questões — sem LangGraph/LangChain (avaliação em `LLM_PIPELINE_SPEC.md` §1).
5. **Practice from Bank & Clean Reset:** o sorteio monta a bateria pelas **percentuais oficiais da prova** (30/25/20/15/10 — ex.: simulado de 15 → 5× Troubleshooting · 4× Cluster Architecture · 3× S&N · 2× Workloads · 1× Storage); ao final da sessão, limpeza L1 (rápida) ou **L2 — clean reset** (baseline de arquivos + restart de agentes; addons preservados) deixa o cluster zerado e limpo.

---

## Documentação do Projeto

| Documento | Finalidade |
| :--- | :--- |
| [`PLAN.md`](./PLAN.md) | Pesquisa de referências (KodeKloud, Killer.sh, PSI, K16S, CK-X), matriz curricular CNCF 2025/2026 e roadmap detalhado em 5 fases com critérios de aceite. |
| [`ARCHITECTURE.md`](./ARCHITECTURE.md) | Arquitetura técnica, diagramas, `kubectl` + SSH Bridge, SQLite, Snapshot & Rollback, **TerminalService (§8)**, **ClusterPowerManager (§9)** e segurança do terminal (§10). |
| [`LLM_SCENARIO_SPEC.md`](./LLM_SCENARIO_SPEC.md) | Contrato JSON estrito (`ScenarioEnvelope`), **formato exato de questão da prova (inglês, anatomia killer.sh/PSI)**, catálogo de assertions determinísticas, guardrails, system prompt e **rubrica de dificuldade mensurável**. |
| [`UX_UI_SPEC.md`](./UX_UI_SPEC.md) | Especificação completa de UX/UI: layout janela única questão+terminal, Copy-Pills, trava Check → Next, pill de estado do cluster, Scenario Studio e sistema visual. |
| [`GAP_ANALYSIS.md`](./GAP_ANALYSIS.md) | Auditoria com evidências do ambiente real: gaps críticos (G1–G18), melhorias priorizadas, decisões de integração e matriz de rastreabilidade (2 revisões). |
| [`LLM_PIPELINE_SPEC.md`](./LLM_PIPELINE_SPEC.md) | Pipeline de geração multi-estágio A→E (avaliação LangGraph × orquestração própria), banco de questões + sorteio por percentuais da prova, contrato formal do Check (PASS/FAIL/SKIP/ERROR) e teardown L0/L1/L2-clean. |
| [`PRODUCT.md`](./PRODUCT.md) | Verdade de produto: o que a plataforma é, para quem, o que a superfície precisa provar e compromissos de marca (inclui a direção Liquid Glass). |
| [`DESIGN.md`](./DESIGN.md) | Design System **Liquid Glass**: mundo visual, tokens, as 3 únicas receitas de vidro, shell único, inventário de componentes, gramática de motion e piso de performance — com mockup em `design/`. |
| [`SETUP_PLAN.md`](./SETUP_PLAN.md) | Plano e implementação do `setup.sh` universal (detecção de S.O./pré-requisitos, instalação com confirmação, driver Multipass/kind, publicação OSS). |
| [`IMPLEMENTATION_READINESS.md`](./IMPLEMENTATION_READINESS.md) | Veredito da auditoria final de prontidão: matriz de cobertura por fase, correções aplicadas e as **4 decisões pendentes (D1–D4)** antes de autorizar a implementação. |

---

## Topologia Real do Cluster Detectado

Durante o levantamento técnico inicial, foi validado o cluster provisionado via `certified-kubernetes-administrator-course/kubeadm-clusters/apple-silicon`:

| Nó | Papel | IP Bridged (Mac → Nó) | IP NAT (Multipass) | Versão K8s | OS / Kernel / Runtime |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `controlplane` | `control-plane` | `192.168.1.123` | `192.168.252.3` | `v1.37.2` | Ubuntu 22.04.5 LTS · `arm64` · `containerd://2.2.1` |
| `node01` | Worker | `192.168.1.124` | `192.168.252.4` | `v1.37.2` | Ubuntu 22.04.5 LTS · `arm64` · `containerd://2.2.1` |
| `node02` | Worker | `192.168.1.125` | `192.168.252.5` | `v1.37.2` | Ubuntu 22.04.5 LTS · `arm64` · `containerd://2.2.1` |

- **Contexto `kubectl` ativo:** `cka` (`~/.kube/config` e `~/.kube/config-cka`)
- **CNI:** Weave Net (`weave-net-*` em `kube-system`)
- **Observação operacional crítica:** `multipass exec` pela rede NAT apresenta falhas intermitentes (`No route to host`), enquanto os IPs Bridged (`192.168.1.123–125`) respondem em `< 1 ms`. Por isso, a arquitetura utiliza SSH direto sobre a rede Bridged com provisionamento automático de chave dedicada (`~/.cka-arena/id_ed25519`).
