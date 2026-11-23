# Plano Mestre de Implementação — CKA Arena

Este documento consolida a pesquisa de referências, análise de viabilidade técnica no cluster `kubeadm` local (Apple Silicon / Multipass), melhores práticas de UX/UI e o roadmap passo a passo para construir o **CKA Arena**.

---

## 1. Pesquisa de Referências & Lições Aplicáveis

Analisamos 5 referências principais do ecossistema de preparação para CKA:

| Plataforma / Projeto | O que faz melhor | Limitação no nosso contexto | O que adotamos no CKA Arena |
| :--- | :--- | :--- | :--- |
| **KodeKloud (Labs)** | Checklist granular ao clicar em *Check*, feedback claro de qual critério falhou, progressão guiada passo a passo, terminal embutido no browser. | Catálogo estático, sem geração sob demanda. | Botão **Check** com validação item a item e trava do **Next** até 100% de aprovação; **terminal embutido no browser** (PTY real do host, não webapp limitado) — requisito do usuário, ver `GAP_ANALYSIS.md` G1. |
| **Killer.sh (Simulador Oficial)** | Questões propositalmente **mais difíceis** que a prova real, combinando 3–4 requisitos na mesma tarefa + armadilhas sutis e meta rígida de tempo. | Sessões limitadas (36h), sem geração infinita sob demanda focada em um domínio específico. | Nível de dificuldade `Killer.sh Hardcore` e `Boss Fight`, cronômetro por questão (meta 6 min) e cenários multi-requisito. |
| **PSI Bridge (Exame Real)** | Banner explícito do comando de contexto (`kubectl config use-context`), peso percentual da questão, lista de questões com marcação (*Flag*) e links diretos para `kubernetes.io/docs`. | Interface pesada via VNC/XFCE e ausência de feedback imediato (*Check*). | Header estilo PSI com badge de domínio/peso, comando de contexto/SSH copiável com 1 clique e links permitidos para `kubernetes.io/docs`. |
| **K16S Exam Simulator (`immanuwell/k16s-exam-simulator`)** | Roda em cluster `kubeadm` real (não `kind`/`k3s`), permitindo quebrar `kubelet`, `etcd`, certificados e static pods com `systemd`. | Sem interface gráfica rica e sem gerador dinâmico via LLM. | Padrão arquitetural da tríade por questão: **metadata + setup (cluster/nó) + validate (estado real)** rodando sobre nós Linux reais (`controlplane`, `node01`, `node02`). |
| **CK-X (`sailor-sh/CK-X`)** | Separação limpa entre estado do cluster, timer de simulado e scripts de validação independentes de como o usuário resolveu o problema. | Baseado em scripts fixos; acoplado a VMs próprias. | Validação **baseada em estado resultante** (não em comandos digitados): se o usuário resolveu via comando imperativo ou YAML editado no `vim`, ambos passam se o estado do cluster estiver correto. |

### Conclusão Arquitetural da Pesquisa
Nenhuma plataforma existente combina:
1. Terminal **real do host macOS** (PTY `zsh -l` com seus aliases, `.vimrc` e velocidade nativa) **embutido no browser** — com terminal nativo como modo opcional +
2. Cluster **`kubeadm` multi-nó real** (`v1.37.2`, `containerd`, `systemd`, static pods) com **ciclo de vida gerenciado pela própria plataforma** (ligar/desligar no botão) +
3. **Motor de LLM gerador de cenários** (e não tutor de dicas) capaz de inventar cenários inéditos, aplicar falhas reais nos nós via SSH e validar determinísticamente a solução.

---

## 2. Matriz Curricular CKA (Currículo CNCF 2025/2026)

A plataforma deve estruturar tanto o **Estúdio Gerador via LLM** quanto a **Telemetria de Estudo** exatamente nos 5 domínios oficiais da prova e seus tópicos modernos:

| Domínio Oficial | Peso | Sub-tópicos Obrigatórios (Incluindo Atualizações 2025/2026) | Exemplos de Falhas/Cenários para LLM |
| :--- | :--- | :--- | :--- |
| **1. Troubleshooting** | **30%** | `kubelet` (`systemd`, config, certs), Static Pods (`/etc/kubernetes/manifests/`), `kube-apiserver`/`etcd`/`scheduler`/`controller-manager`, nós `NotReady`, `CoreDNS`, logs de container/pod (`CrashLoopBackOff`, `ImagePullBackOff`, OOM), CNI/Weave. | `kubelet` parado ou com `cgroupDriver` / porta errada em `node01`; flag inválida no manifesto de `kube-apiserver`; `CoreDNS` com ConfigMap corrompido; `CrashLoopBackOff` por env/command errado. |
| **2. Cluster Architecture, Installation & Configuration** | **25%** | RBAC (`Role`, `ClusterRole`, `RoleBinding`, `ClusterRoleBinding`, `ServiceAccount`), `etcd` snapshot save & restore, **Helm** (install, upgrade, rollback, `--set`, `values.yaml`), **Kustomize** (`kubectl apply -k`, overlays), CRDs & Operators, `kubeadm` (certs check/renew, upgrade plan). | Criar SA com permissão granular em múltiplos namespaces e validar via `kubectl auth can-i`; backup e restore de `etcd` em diretório específico; instalar/atualizar release Helm corrigindo values; aplicar overlay Kustomize com patch de réplicas/imagem. |
| **3. Services & Networking** | **20%** | **Gateway API** (`GatewayClass`, `Gateway`, `HTTPRoute`, traffic splitting), `Ingress` & `IngressClass`, `NetworkPolicy` (ingress/egress, namespaceSelector, podSelector, porta DNS UDP/TCP 53), Services (`ClusterIP`, `NodePort`, endpoints), CoreDNS resolution. | Criar `HTTPRoute` roteando `/api` e `/web` com pesos distintos; `NetworkPolicy` que permite tráfego de `frontend` para `backend` na porta 8080 e **não quebra egress DNS (53)**; diagnosticar Service sem Endpoints por mismatch de label. |
| **4. Workloads & Scheduling** | **15%** | Deployments (rolling update, rollback, pause/resume), DaemonSets, Jobs/CronJobs, Multi-container Pods (`initContainers`, **Native Sidecar Containers** `restartPolicy: Always`), `nodeSelector`, `nodeAffinity`, `podAntiAffinity`, Taints & Tolerations, `ResourceQuota`, `LimitRange`, `PriorityClass`. | Deployment bloqueado por taint no nó + afinidade obrigatória; sidecar nativo compartilhando volume `emptyDir` com app principal; rollout quebrado exigindo rollback para revisão específica e ajuste de `resources`. |
| **5. Storage** | **10%** | `StorageClass` (`WaitForFirstConsumer`, `Immediate`, reclaim policy `Retain`/`Delete`), `PersistentVolume`, `PersistentVolumeClaim`, expansão de volume, `accessModes`, `hostPath`/`local` em nós específicos. | Criar PV estático com `storageClassName`, `capacity` e `accessModes` exatos e vincular PVC consumido por Pod; diagnosticar PVC preso em `Pending` por mismatch de `storageClassName` ou `nodeAffinity`. |

### Modos de Dificuldade Selecionáveis (rubrica mensurável — `LLM_SCENARIO_SPEC.md` §5)

> A diferença entre níveis é **verificável no envelope** (requisitos, kinds de recurso, traps, cadeia causal, nº de checks, meta de tempo, peso) e **enforçada pelo Revisor** (Estágio C): fora da banda em ≥ 2 eixos ⇒ regeneração com delta explícito. Exemplos calibrados por nível no §5 do spec.

1. **`Exam Standard` (Padrão CKA):** 1–2 requisitos, 1 namespace, 0 armadilhas, correção de passo único. Meta: `≤ 4 min` · peso 2–5.
2. **`Killer.sh Hardcore` (Acima da Prova):** 3–4 requisitos interligados + ≥ 1 pegadinha realista (Namespace errado, `NetworkPolicy` com `egress` bloqueando DNS 53, `nodeAffinity` + toleration em `node02`, manifesto a salvar em `/opt/...`), cadeia diagnosticar → reparar. Meta: `≤ 7 min` · peso 6–10.
3. **`Boss Fight` (Incidente Crítico):** 4–6 requisitos, falha de infraestrutura de nó via SSH (`kubelet`/static pod/systemd) + workload dependente que só volta ao `Ready` após restaurar a causa raiz (cadeia ≥ 3), ≥ 2 armadilhas. Meta: `≤ 12 min` · peso 11–16.

---

## 3. Decisões Técnicas Fundamentais

1. **Terminal no Browser (padrão) + Terminal Nativo (opcional):** o navegador concentra enunciado, Check, Studio **e um terminal real** — `TerminalService` com PTY do host (`zsh -l`) renderizado em xterm.js via WebSocket, com abas `mac · controlplane · node01 · node02` e botão **Check** ao alcance dentro do painel do terminal (detalhes em `ARCHITECTURE.md` §8). Um toggle **Modo Terminal Nativo** esconde o painel embutido e restaura o fluxo dual-window 40/60 original para quem prefere iTerm2/Ghostty.
2. **Backend em Python (`FastAPI` + `Uvicorn` + `SQLite`):**
   - Reaproveita o ecossistema já validado localmente (`Python 3.14`, `uv`, `FastAPI`, `httpx`, `anthropic`).
   - Executa comandos `kubectl` (via subprocesso assíncrono com `--kubeconfig` / `--context=cka`) e SSH direto via `asyncssh` ou `ssh` nativo com `ControlMaster`.
3. **Resiliência à Falha de `multipass exec`:**
   - Como constatado na verificação do ambiente, `multipass exec controlplane` falha com `No route to host` na rede NAT.
   - O **CKA Arena** usa os **IPs Bridged (`192.168.1.123`, `.124`, `.125`)** descobertos dinamicamente via `kubectl get nodes -o wide` (com fallback para `multipass list --format json`), provisionando na primeira execução uma chave SSH dedicada (`~/.cka-arena/id_ed25519`) nos 3 nós.
4. **Provedores de LLM Multi-Engine:**
   - Suporte nativo ao catálogo de provedores do usuário (GLM Coding Plan / Z.AI, OpenCode Go, DeepSeek, Anthropic Claude, OpenAI-compatible e Ollama local `qwen2.5-coder:7b-instruct-q8_0`), com configuração pela UI (Settings → AI provider), persistida em `llm_config.json` local (sem copiar a chave para repositório versionado — leitura em runtime ou armazenamento local `.env`/`llm_config.json` ignorado no `.gitignore`).
5. **Mecanismo Anti-Catástrofe (Snapshot & Rollback):**
   - Antes de aplicar qualquer cenário que toque em nós (`etcd`, `/etc/kubernetes/manifests/`, `/var/lib/kubelet/`, `systemd`), o engine realiza backup automático em `/var/backups/cka-arena/<scenario_id>/` no nó alvo.
   - Botão **`[Reset Question]`** e botão global **`[Cluster Doctor / Restore Baseline]`** garantem que o cluster nunca fique inutilizável se um teste quebrar o `kube-apiserver`.
6. **Ciclo de Vida do Cluster Gerenciado (`ClusterPowerManager`):**
   - O cluster é **inicializado junto com a aplicação**: botão/CTA **"⏻ Power On"** na home quando as VMs estão `off`, boot instrumentado em 7 passos via SSE (VMs → SSH → ssh-config regen → `/readyz` → nós Ready → doctor → baseline) e pill de estado permanente no header (`off/starting/ready/degraded/daemon_down`).
   - IPs Bridged são **DHCP**: a cada boot o manager regenera o bloco `~/.ssh/config` e faz **self-heal do kubeconfig dedicado** (`~/.cka-arena/kubeconfig`) caso o IP do controlplane tenha mudado (detalhes em `ARCHITECTURE.md` §9).
   - Configuração `auto_start_on_launch` liga as VMs automaticamente ao abrir a app — **default ON** (decisão D3 do `IMPLEMENTATION_READINESS.md`).

---

## 4. Roadmap de Implementação em 5 Fases

### Fase 1: Fundação, Cluster Power Manager, Doctor & SSH Bridge ✅ (implementada e verificada em 17/11/2026)
**Objetivo:** Subir o servidor local FastAPI e garantir comunicação 100% estável com a API Kubernetes (`v1.37.2`) e com os 3 nós via SSH Bridged.
- **Entregáveis:**
  - Estrutura do projeto `cka-arena/` com `pyproject.toml` (`uv`), `FastAPI`, `SQLite` (`aiosqlite` ou `sqlite3` com WAL), `pyyaml`, `pydantic`, `httpx`.
  - Script/endpoint `setup_ssh_bridge`: testa conectividade TCP porta 22 nos IPs Bridged correntes (descobertos via `multipass list --format json`; `kubectl` só quando o cluster já está de pé), instala chave pública `~/.cka-arena/id_ed25519.pub` nos nós via **`SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`** (OpenSSH ≥ 8.4 — verificado 10.5 no host; sem `sshpass` nem expect; senha do lab via `CKA_LAB_PASSWORD`, default `ubuntu`), grava bloco gerenciado em `~/.ssh/config` (`Host cka-controlplane`, `cka-node01`, `cka-node02`) e materializa o **kubeconfig dedicado** `~/.cka-arena/kubeconfig` copiado do `admin.conf` (o backend nunca usa o `~/.kube/config` global, que contém contextos EKS de trabalho).
  - Módulo `ClusterPowerManager`: `GET/POST /api/cluster/power` (start/stop/restart como job assíncrono único), máquina de estados `off → starting → ready → degraded` (+ `daemon_down` com orientação de correção), boot instrumentado com progresso SSE, regeneração do bloco SSH e self-heal de kubeconfig pós-DHCP.
  - Módulo `ClusterDoctor`: verifica saúde dos 3 nós, pods de `kube-system`, existência de `helm` e `etcdctl`, tira um **baseline de arquivos** inicial de `/etc/kubernetes/manifests`, `/var/lib/kubelet/config.yaml`, `/etc/containerd/config.toml` e drop-ins do kubelet nos nós — insumo do **L2 clean reset** (`LLM_PIPELINE_SPEC.md` §6). *Snapshots de VM do Multipass não são suportados no backend macOS (verificado ao vivo); o L2 não depende deles.*
- **Critério de Aceite:** `GET /api/cluster/health` retorna `3/3 Ready`, `kubectl` OK e SSH sem senha funcionando nos 3 nós em `< 500ms`. Com as VMs paradas: `POST /api/cluster/power {"action":"start"}` leva o cluster a `ready` via boot instrumentado (≤ 4 min tipico), regenerando `~/.ssh/config` e fazendo self-heal do kubeconfig se os IPs Bridged mudarem.
  - **Evidência do aceite (17/11/2026):** `stop → off` em ~12s; `start → ready` em **32s** com os 7 passos emitidos via SSE; bloco `~/.ssh/config` regenerado somente com IPs Bridged; health final `3/3`, `baseline_files: true`, SSH `123.8–141.1 ms`; 11 testes `pytest` verdes.

### Fase 2: Engine de Execução de Cenários (`Setup`, `Check`, `Cleanup`) ✅ (implementada e verificada em 17/11/2026)
**Objetivo:** Executar qualquer cenário estruturado (JSON `ScenarioEnvelope`) no cluster real, avaliando as respostas do usuário com precisão determinística.
- **Entregáveis:**
  - `ScenarioEngine`:
    - `apply_setup(scenario)`: cria namespaces, aplica manifests via `kubectl apply -f -`, executa comandos de falha controlada via SSH nos nós após salvar backups dos paths afetados.
    - `run_checks(scenario)`: executa cada assertion em paralelo/sequência (usando `kubectl get -o json`, `kubectl auth can-i`, `kubectl run` / pod efêmero para testar DNS/HTTP quando necessário, ou comandos SSH read-only nos nós como `systemctl is-active kubelet`).
    - `cleanup(scenario)`: restaura backups dos nós (se houver) e remove namespaces/recursos criados pelo cenário (`kubectl delete --ignore-not-found --wait=false`).
  - Catálogo de **10+ Check Types determinísticos** (documentados em `LLM_SCENARIO_SPEC.md`).
  - `teardown.py` — Teardown em 3 níveis: **L0** por questão (no `Next`/`Pular`), **L1** fim de sessão (varredura por label `cka-arena.io/managed`, restauração de backups, drift check vs baseline) e **L2 clean reset**: L1 + restauração do baseline de arquivos dos nós + `restart containerd/kubelet` + wait Ready + drift check. **Sem snapshots de VM** — o backend Multipass/macOS não os implementa (verificado); addons são preservados (`LLM_PIPELINE_SPEC.md` §6).
  - **3 Seeds exemplares (decisão D4):** `scenarios/seed/` com 1 questão cada de Troubleshooting, Cluster Architecture e Services & Networking (não-destrutivas; etcd apenas `snapshot save`) — validam setup→check→cleanup no engine **antes** de existir pipeline LLM, e são publicadas no banco como `source: seed`.
- **Critério de Aceite:** Um cenário de teste com 3 checks (1 pass, 2 fail) retorna relatório detalhado de cada item, impede o avanço para a próxima questão e, após corrigir no terminal, libera o botão `Next`.
  - **Evidência do aceite (17/11/2026):** seed `ts-crashloop-fix` → **1 PASS / 2 FAIL** (bloqueia) → correção → **3/3 PASS**; seed `ca-rbac-pod-reader` → 2 PASS/2 FAIL → 4/4 PASS; seed `sn-expose-service` (sonda efêmera `curlimages/curl`) → 3 FAIL → 3/3 PASS; `cleanup` remove namespaces em todos; `drift=false` nos 3 nós após L1 (backups restaurados, nenhum resíduo); backup/restore de nó validado E2E (`/etc/hosts` restaurado). 23 testes `pytest` verdes · 3 seeds publicados no banco.

### Fase 3: Pipeline de Geração Multi-Estágio (A→E) + Banco de Questões ✅ (implementada e verificada em 17/11/2026)
**Objetivo:** Usuário seleciona domínios + sub-tópicos + dificuldade + quantidade no Studio e clica "Generate with AI"; o pipeline de agentes (**A** Normalizador → **B** Construtor → **C** Revisor) com gates determinísticos (**D**) e prove-out real no cluster (**E**) **publica questões comprovadamente solúveis, em inglês no formato exato da prova, no banco**. Practice vira fluxo separado que sorteia do banco pelas percentuais da prova.
- **Entregáveis:**
  - `LLMClient`: adaptador multi-provider (Anthropic + OpenAI-compatible + Ollama), padrão multi-provider próprio (GLM Coding Plan, DeepSeek, OpenCode Go, Claude, custom), fallback de provider em timeout/429 (DeepSeek como segunda opção, conforme `IMPLEMENTATION_READINESS.md` D1) — **sem LangGraph/LangChain** (avaliação e gatilhos de revisão documentados em `LLM_PIPELINE_SPEC.md` §1).
  - `pipeline.py` — **A** Normalizador (modelo flash, temperature 0, saída `GenerationRequest` Pydantic canônica); **B** Construtor (modelo principal, 1 envelope por chamada, N paralelas, bloco `solution` automatizável); **C** Revisor (flash, rubrica fixa, `approve|patch`); **D** gates de código (schema, `yaml.safe_load_all`, blocklist, `--dry-run=server`, whitelist arm64); **E** prove-out em namespace efêmero de prova: **sanity** (checks DEVEM falhar pós-setup) + **Solvability Probe** (aplica `solution` e exige 100% PASS). Auto-reparo ≤ 2 com erro exato; reprovadas vão para `draft` (quarentena, nunca servem para prática).
  - `bank.py` — banco de questões: dedup semântico (`envelope_hash`), ciclo de vida `draft → probed → published → retired` (envelope imutável pós-publicação), métricas por questão (acerto 1ª tentativa, tempo médio) e **`draw_exam_sample`**: largest remainder sobre os pesos oficiais (30/25/20/15/10), renormalização por filtros, fallback de célula vazia e ordenação `times_used ASC, random()`.
  - **Settle Window:** entre apply e sanity, aguardar pods estáveis (`Running`/`CrashLoopBackOff`/`ImagePullBackOff` ou 90s) — evita falso-veredito por latência de image pull (`GAP_ANALYSIS.md` G6).
- **Critério de Aceite:** gerar `Troubleshooting + Services & Networking` em `Killer.sh Hardcore` publica ≥ 1 questão que (a) **está em inglês no formato exato da prova** (título imperativo + contexto-sintoma + "Perform the following tasks" + restrições), (b) **falha** o Check logo após o setup e (c) passa **100%** após a aplicação do `solution` no probe, com complexidade dentro da banda do nível (Revisor rejeita mal encaixe); e o sorteio de 15 questões do banco devolve exatamente **5/4/3/2/1** por domínio.
  - **Evidência do aceite (17/11/2026):** job real via `POST /api/generate` publicou `q-ff6f432969b5` — "Fix Broken Service Endpoints and Readiness" (Troubleshooting · **killer_hardcore** · peso 8 · 6 min · 6 checks), com probe passando sanity (checks falham pós-setup) + **solvability** (solution aplicada → 100% PASS) e envelope em inglês no formato de prova; gates rejeitaram automaticamente propostas fora da banda durante as tentativas (11 checks/peso 12, peso 16). Alocação **5/4/3/2/1** validada por teste com banco sintético de 15 questões (`largest_remainder`); draw no banco real devolve as disponíveis + fallbacks sinalizados. 37 testes `pytest` verdes. **Otimizações de velocidade** (medidas): `thinking: disabled` no DeepSeek (45.8s → 4.7s/chamada), fast-first/deep-retry, gates antes do Revisor, normalizador fast-path, slots paralelos com probe serializado e settle único — job de **3 questões publicado em 76s** (~25s/questão, antes ~200–300s/questão).

### Fase 4: Interface Web Integrada (`Exam Workspace` + `Terminal` + `Scenario Studio`) ✅ (implementada e verificada em 17/11/2026)
**Objetivo:** Construir a interface web enxuta com **questão e terminal integrados na mesma janela** (e modo terminal nativo opcional), seguindo integralmente o `UX_UI_SPEC.md`.
- **Entregáveis:**
  - Layout de **janela única** (questão à esquerda ~44% · terminal embutido à direita ~56%, colapsável) com degradação elegante para o layout 40% dual-window original no **Modo Terminal Nativo** — identidade visual **Liquid Glass** conforme `DESIGN.md` (3 materiais de vidro, shell único persistente, motion 120–480ms), Vanilla JS modular ou Alpine/HTMX sem build pesado, mantendo setup instantâneo.
  - **Design System antes das visões:** `static/css/tokens.css` + `glass.css` (`glass-1/2/clear`) + o **shell persistente** (header + região de conteúdo + status strip) construídos primeiro — é o shell que garante que nenhuma visão pareça uma página diferente (`DESIGN.md` §5/§10); referência visual: `design/mockup-workspace.svg`.
  - **Visão 1 — Exam Workspace (Tela de Estudo):**
    - Fila de questões lateral recolhível / pills numeradas (`Q1 ✓`, `Q2 ●`, `Q3 🔒`).
    - Card da questão com badge de Domínio + Dificuldade + Peso + Timer regressivo.
    - Banner de Contexto/Acesso copiável (`kubectl config use-context cka` / `ssh cka-node01`).
    - **Copy-Pills automáticas** em nomes de pods, namespaces, arquivos e labels no texto.
    - Drawer de Resultado do `Check` (lista verde/vermelha com motivo técnico de cada falha).
    - Barra inferior fixa: **`[Check]`** + **`[Next]`** (bloqueado com cadeado até 100% `PASS`).
    - Botão de emergência controlado: **`[Reset Scenario]`**, **`[Skip (unlock after confirmation)]`** e **`[View Reference Solution]`** (apenas após passar no Check ou confirmar desistência).
    - **Painel de Terminal Integrado (xterm.js vendored, sem CDN):** abas `mac · controlplane · node01 · node02`, reconexão automática em reload de página (PTY persiste no backend), Copy-Pills que copiam **e** focam o terminal para ⌘V, e botão **`Check`** na barra de rodapé do próprio terminal (⌘↵ funciona com o terminal focado).
  - **Visão 2 — Scenario Studio (Gerador LLM):**
    - Checkboxes dos 5 domínios da CKA com seus pesos oficiais + chips de sub-tópicos.
    - Seletor de dificuldade (`Exam Standard`, `Killer.sh Hardcore`, `Boss Fight`).
    - Quantidade (`1 cenário rápido`, `Bateria 3 cenários`, `Bateria 5 cenários`, `Simulado 15 cenários`).
    - **Live job card** via SSE refletindo os estágios A–E por cenário (mini-stages, tentativas, detalhe atual), heartbeat de 4s, contadores e barra de progresso, com recuperação em reload (`GET /api/generate/status` + `generation.snapshot`) e event log recolhível (`UX_UI_SPEC.md` §4), com grade de cobertura 5×3; CTA **`[▶ Practice]`** com preview da distribuição por percentuais da prova e tela de fim de sessão com limpeza L1/L2 (`UX_UI_SPEC.md` §5).
  - **Visão 3 — Configurações (LLM + Cluster Doctor):**
    - Testar conexão com a LLM, escolher provider/modelo, testar saúde do cluster e restaurar baseline.
  - **Evidência do aceite (17/11/2026, Chromium headless via Playwright):** shell único com os 3 materiais de vidro; **terminal real no browser** (PTY do host) executando `kubectl get nodes` → 3/3 Ready; sessão de prática sorteada do banco aplicada no cluster com **Check** itemizado (FAIL/PASS/FAIL com evidência `expected/actual`) e **Next bloqueado** até passar; skip → next → **fim de sessão com limpeza L1 e `drift=false`**; viewport 560px sem scroll horizontal; **zero erros de console**. Screenshots: `/tmp/uicheck/shots/` (01-shell, 02-terminal, 05-session, 06-check, 08-end-summary, 09-narrow). 40 testes `pytest` verdes. *(Observação: `screencapture`/computer tool bloqueado por falta de permissão de gravação de tela no macOS; verificação feita na mesma superfície HTTP com navegador real headless.)*

### Fase 5: Banco Seed Offline (15 Cenários) + Pré-requisitos de Infra & Telemetria ✅ (implementada e verificada em 17/11/2026)
**Objetivo:** Garantir utilidade imediata (zero espera de LLM quando quiser treino instantâneo) + suporte aos novos tópicos do currículo CNCF 2025/2026 + histórico de evolução.
- **Entregáveis:**
  - **Bootstrap opcional de ferramental CKA no cluster:** verificar/instalar no `controlplane` e/ou cluster `metrics-server` (já há scripts em `certified-kubernetes-administrator-course/metrics-staging-scripts/`), `helm`, e CRDs da **Gateway API** + controlador leve (ex.: Envoy Gateway ou NGINX Gateway Fabric) ou flag clara informando quais addons estão ativos no cluster.
  - **12 Cenários Seed restantes (D4: 3 exemplares já entregues na Fase 2, totalizando 15):** completam `scenarios/seed/` cobrindo os 5 domínios (incluindo `etcd` snapshot save (restore só via LLM com `destructive`), `kubelet` quebrado, `kube-apiserver` static pod quebrado, `NetworkPolicy` egress DNS 53, `Helm` rollback, `Kustomize` overlay, `Gateway API`/`HTTPRoute`, Sidecar nativo e expansão de PVC) e são **publicados no banco** após passarem pelos mesmos gates A–E (seed não pula prove-out).
  - **Dashboard de Desempenho por Domínio:** taxa de acerto na 1ª tentativa, tempo médio vs meta de 6 min, recomendações automáticas do próximo domínio a gerar e **grade de cobertura do banco** (contagem `published` por domínio×dificuldade).
  - **Evidência do aceite (17/11/2026):** **17 seeds** passaram por **gates determinísticos + Solvability Probe no cluster** (`python -m app.seed validate`: 17/17 PROBE OK, incluindo kubelet/node01 via SSH, etcd snapshot save, Helm upgrade com chart local, taints, PV/PVC, **NetworkPolicy com egress DNS 53 e prova negativa**, e **Gateway API `HTTPRoute` aceito pelo controller**); banco com **21 questões publicadas** cobrindo os 5 domínios; **telemetria por domínio** (`/api/telemetry`: acerto/1ª tentativa/tempo médio + recomendação) no Studio; **bootstrap plan** em Settings (vazio após instalação). 41 testes `pytest` verdes.
  - **Addons instalados (17/11/2026):** metrics-server (patch `--kubelet-insecure-tls`; `kubectl top` OK), **Gateway API 1.2 CRDs + Envoy Gateway v1.2.0** (data plane validado com `HTTP 200` real), **local-path-provisioner v0.0.30** (StorageClass `local-path`), e `weave-npc` **já presente como container do DaemonSet weave-net** (detecção corrigida no doctor). **L2-clean implementado e validado ao vivo** (snapshots de VM não suportados no Multipass/macOS): reset com `drift=false`, 3/3 Ready e **addons preservados**. *Gateway em kubeadm sem LoadBalancer fica `Programmed=False` por falta de IP externo; o tráfego via ClusterIP do data plane foi validado (HTTP 200) e os checks usam o status `Accepted` do HTTPRoute.*

---

## 5. Verificação de Prontidão Após Implementação

Quando todas as fases forem concluídas, o plano de testes deverá validar:
1. Testes unitários (`pytest`) para o parser da LLM, schema `Pydantic`, renderização de assertions e lógica de bloqueio `Check -> Next`.
2. Teste de integração real contra o cluster `cka` (`v1.37.2`): aplicar um cenário de cada tipo (K8s manifest + SSH node fault), confirmar que `Check` reprova antes da correção, corrigir via `kubectl`/SSH, confirmar que `Check` aprova `100%`, avançar no `Next` e verificar `cleanup` completo do namespace de teste.
3. Inspeção visual da UI em viewport estreita (`480px`–`600px` simulando lado esquerdo da tela com terminal ao lado) e desktop (`1440px`) — incluindo **conformidade com o design system Liquid Glass** (`DESIGN.md`): apenas os 3 materiais de vidro definidos, mesmos raios/curvas em todas as visões, terminal nunca sob vidro, ≤ 2 camadas de vidro empilhadas, nenhuma animação fora da gramática de motion.
4. Testes do `TerminalService` (sessão PTY por aba, resize via `TIOCSWINSZ` ecoando `stty size`, input→output, limite de 6 abas, timeout de idle) e do `ClusterPowerManager` (transições de estado com `multipass` stubado; self-heal de kubeconfig simulando mudança de IP do controlplane).
5. Smoke E2E do requisito central de integração: app aberta com cluster `off` → CTA "⏻ Power On" → boot instrumentado conclui → estado `ready` → terminal aberto no browser executa `kubectl get nodes` (3/3 Ready) → cenário seed aplicado → resolvido **no terminal do browser** → `Check` 100% PASS → `Next` liberado.
6. Testes do banco e do teardown: `draw_exam_sample` retorna exatamente `5/4/3/2/1` para N=15 e `2/1/1/1/0` para N=5 (largest remainder 30/25/20/15/10); fallback de célula vazia completa proporcionalmente e avisa; E2E de fim de sessão: L1 remove tudo com label `cka-arena.io/managed` e zera o drift check; L2-clean restaura o baseline de arquivos, reinicia containerd/kubelet, retorna `drift=false` e preserva os addons.
