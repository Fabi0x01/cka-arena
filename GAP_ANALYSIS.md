# Análise de Gaps & Melhorias — CKA Arena

> Auditoria da documentação existente (`PLAN.md`, `ARCHITECTURE.md`, `LLM_SCENARIO_SPEC.md`, `UX_UI_SPEC.md`, `README.md`) contra o ambiente real e o novo requisito do usuário: **terminal no próprio browser** + **botão para ligar o cluster junto com a aplicação**.
>
> Data da auditoria: 2026-11-17 · Auditor: análise automatizada com verificação viva do ambiente.

---

## 0. Evidências Coletadas no Ambiente (Ground Truth)

Verificações executadas na máquina durante esta análise:

| Verificação | Comando | Resultado |
| :--- | :--- | :--- |
| Estado das VMs | `multipass list` | `controlplane`, `node01`, `node02` — **Running**, IPs Bridged `192.168.1.123/124/125` + NAT `192.168.252.3-5` |
| Saúde do cluster | `kubectl --context cka get nodes -o wide` | **3/3 Ready**, `v1.37.2`, `containerd://2.2.1`, kernel `5.15.0-203-generic (arm64)` |
| Contexto kubectl | `kubectl config get-contexts` | Contexto `cka` é o **corrente**; também existem 3 contextos EAX (easydesk) no mesmo kubeconfig |
| SSH nos nós (rede Bridged) | `nc -z -G 2 <ip> 22` | **OK nos 3 nós** (`PasswordAuthentication yes`, user/password `ubuntu`/`ubuntu` conforme `01-setup-hosts.sh`) |
| Ferramentas no Mac | `which` | `kubectl`, `helm`, `etcdctl`, `multipass` **presentes** |
| Ferramentas ausentes no Mac | `which` | `tmux` **ausente**, `ttyd`/`gotty`/`wetty` **ausentes** |
| Estado atual da plataforma | `ls ~/.cka-arena` | Ainda **não existe** (nenhum provisionamento feito) |
| `~/.ssh/config` | `grep cka` | **0 ocorrências** — bloco gerenciado do CKA Arena ainda não foi criado |
| Padrão de referência LLM | Cliente multi-provider próprio | Catálogo (GLM Coding Plan/Anthropic-protocol, OpenCode Go, DeepSeek, Anthropic, OpenAI-compatible) + `llm_config.json` com `provider/model/api_key/timeout_s`, configurável pela UI |
| Provisionamento do cluster | `deploy-virtual-machines.sh` + `scripts/01-setup-hosts.sh` | `BUILD_MODE=BRIDGE`; senha `ubuntu:ubuntu` via `chpasswd`; `PRIMARY_IP` exportado em `/etc/environment` dos nós |

**Conclusão:** a base técnica descrita nos documentos é real e verificada. Os gaps abaixo são de **planejamento**, não de viabilidade.

---

## 1. Pontos Fortes a Manter (O Plano Já Acerta)

1. **Validação determinística por estado resultante** (nunca por comando digitado) — igual KodeKloud/Killer.sh; o contrato `ScenarioEnvelope` com 10 check types é sólido e **permanece válido sem alterações**.
2. **Pipeline de self-healing da LLM** (schema gate → blocklist → dry-run → apply → sanity check "regra de ouro" → retry com erro exato) — padrão correto para confiabilidade de geração.
3. **Snapshot & Rollback em 3 camadas** (baseline global + backup pré-comando + guardrails de parser) — necessário para cenários que quebram control plane.
4. **Descoberta dinâmica de IPs via `kubectl get nodes -o json`** em vez de hardcode — decisão correta (ver G3 para o caso cluster desligado).
5. **Matriz curricular CNCF 2025/2026 completa** com 5 domínios e pesos corretos, incluindo tópicos novos (Gateway API, sidecar nativo, Helm/Kustomize).
6. **Sanity check anti-trivialidade** (cenário que nasce 100% PASS é regenerado) — detalhe que a maioria dos geradores ignora.

---

## 2. Gaps Críticos (Bloqueiam o Novo Requisito)

### 🔴 G1 — Contradição central: "Zero Terminal no Browser" × novo requisito "terminal no browser"
- **Evidência:** `PLAN.md` decisão nº 1 ("Zero Terminal no Browser... o terminal nativo do Mac executa kubectl e ssh") e `UX_UI_SPEC.md` §1 (ergonomia 40/60 com terminal nativo obrigatório).
- **Impacto:** todo o UX (split 480px, wireframe, copy-pills pensados para janela estreita) e a arquitetura (backend não tem nenhum componente de terminal) precisam ser revistos.
- **Correção aplicada:** decisão nº 1 reescrita para **Terminal Web integrado (padrão) + modo terminal nativo (opcional)**. Novo componente `TerminalService` especificado em `ARCHITECTURE.md` §8; layout novo em `UX_UI_SPEC.md` §2. O usuário pode continuar usando o terminal nativo se preferir — o embedded é que passa a ser o fluxo primário, o que **habilita o botão Check ao lado do terminal** (requisito: "executar os comandos dos cenarios e pedir validaçao" no mesmo lugar).

### 🔴 G2 — Ausência total de gestão de ciclo de vida do cluster (ligar/desligar)
- **Evidência:** nenhum documento menciona `multipass start/stop`. O `ClusterDoctor` assume cluster já saudável; `ARCHITECTURE.md` §4 fala de restaurar baseline via SSH, mas não de **bootar as VMs**.
- **Impacto:** requisito central do usuário ("cluster inicializado junto com a aplicação, com botão na tela para ligar") não tem dono no design.
- **Correção aplicada:** novo componente **ClusterPowerManager** (`ARCHITECTURE.md` §9): máquina de estados `off → starting → ready → degraded`, endpoint `POST /api/cluster/power`, sequência de boot instrumentada (VMs → SSH 22 → ssh-config regen → `/readyz` → nós Ready → doctor rápido → baseline se ausente) com progresso via SSE. UI: pill de estado no header + CTA "Ligar Cluster" quando `off` (`UX_UI_SPEC.md` §3). Flag `auto_start_on_launch` opcional nas Configurações.

### 🔴 G3 — IPs Bridged são DHCP: kubeconfig e `~/.ssh/config` podem quebrar após reboot das VMs
- **Evidência:** `deploy-virtual-machines.sh` usa `--bridged` (DHCP do roteador); `README.md`/`ARCHITECTURE.md` tratam `192.168.1.123–125` como fixos; o kubeconfig do contexto `cka` aponta para `https://192.168.1.123:6443` hardcoded.
- **Impacto:** se o DHCP reatribuir IPs após `multipass stop/start`, **tudo** para de funcionar (kubectl, SSH, checks) sem diagnóstico óbvio. É o gap mais provável de virar incidente real.
- **Correção aplicada:** no fim do boot, o PowerManager (a) lê IPs atuais via `multipass list --format json`, (b) **regenera o bloco gerenciado** `# >>> CKA-ARENA MANAGED >>>` do `~/.ssh/config`, e (c) faz **self-heal do kubeconfig**: se `kubectl --context cka get --raw /readyz` falhar mas SSH responder, baixa `/etc/kubernetes/admin.conf` do controlplane via SSH, reescreve `server: https://<ip-atual>:6443` e atualiza o contexto `cka` via `kubectl config set-cluster`. Detalhado em `ARCHITECTURE.md` §9.3.

### 🔴 G4 — Bootstrap da chave SSH: fluxo de primeira execução não especificado (e sem `sshpass`)
- **Evidência:** `PLAN.md` Fase 1 menciona "solicitando/usando a senha padrão do lab `ubuntu` uma única vez", mas sem mecanismo; `sshpass` **não está instalado** no Mac (verificado).
- **Correção aplicada:** **`SSH_ASKPASS` + `SSH_ASKPASS_REQUIRE=force`** (OpenSSH ≥ 8.4; host verificado em 10.5) para instalar a chave pública sem interação — sem `sshpass` e sem expect. Especificado em `ARCHITECTURE.md` §3 (item 5) e validado na implementação da Fase 1.

### 🔴 G5 — Nenhum componente de terminal web especificado (backend nem frontend)
- **Evidência:** `ARCHITECTURE.md` §5 (árvore de diretórios) não tem `terminal.py` nem assets xterm; dependências do `pyproject` não listam nada de WebSocket/PTY.
- **Impacto:** requisito central sem design.
- **Correção aplicada:** **TerminalService** completo em `ARCHITECTURE.md` §8: PTY in-process (`pty.openpty` + `TIOCSWINSZ` + reader task por sessão, zero dependências extras — FastAPI/uvicorn já suportam WebSocket), frontend `xterm.js` **vendored em `static/vendor/`** (sem CDN, funciona offline), abas com presets (`mac`, `controlplane`, `node01`, `node02`), resize, reconnect em reload de página (PTY vive no backend), limite de sessões e timeout de idle. **Rejeitadas** as alternativas `ttyd`/`gotty` (binário externo, sem audit de telemetria, sem controle de ciclo de vida) e `tmux` (não instalado — verificado; desnecessário dado o registro de PTYs no backend).

---

## 3. Gaps Médios (Riscos Reais, Não Bloqueantes)

### 🟡 G6 — Sanity check pode gerar falso "cenário OK" por latência de image pull
- **Evidência:** `LLM_SCENARIO_SPEC.md` estágio 4 aplica setup e roda checks imediatamente; um check `pod_status_ready` pode "falhar inicialmente" apenas porque a imagem ainda está baixando — e **passar sozinho** segundos depois, ou pior: um cenário legítimo ser rejeitado porque o check demorou a falhar por estado real.
- **Correção proposta:** após o apply, aguardar **settle window** (pods atingirem condição estável: `Running`/`CrashLoopBackOff`/`ImagePullBackOff` ou timeout de 90s) **antes** de rodar o sanity check; documentado como melhoria do pipeline (P1) em `PLAN.md` Fase 3.

### 🟡 G7 — `multipass` daemon fora do ar não tratado
- **Evidência:** `deploy-virtual-machines.sh` tem watchdogs para daemon travado (comentários no script), mas o plano do CKA Arena ignora o caso.
- **Correção proposta:** PowerManager detecta `multipass list` falhando e retorna estado `daemon_down` com instrução acionável (`sudo launchctl kickstart -k system/com.canonical.multipass`). Adicionado a `ARCHITECTURE.md` §9.

### 🟡 G8 — Segurança do WebSocket de terminal não especificada
- **Evidência:** novo vetor de ataque: PTY de shell do host exposto via WS. Exposição remota via tailscale-serve é um uso real desta máquina.
- **Correção aplicada:** terminal WS **somente em `127.0.0.1`**, validação de header `Origin` (same-origin), recusa explícita se o app estiver bindado fora de loopback sem auth, aviso permanente na tela de Configurações. `ARCHITECTURE.md` §10.

### 🟡 G9 — Telemetria atual não enxerga *como* o usuário resolveu
- **Evidência:** `check_runs` registra tentativas, mas nada captura a abordagem (imperativo × declarativo, uso de `--dry-run`, etc.).
- **Correção proposta (opcional, opt-in):** com o terminal no browser, o backend pode manter ring buffer do PTY e extrair comandos (split em prompt) vinculados ao `scenario_id` ativo — tabela `command_audit`. **Privacidade:** local-only, opt-in nas Configurações, purge por sessão. `ARCHITECTURE.md` §6.

### 🟡 G10 — Colisão de portas e conflito de kubeconfig com outros projetos
- **Evidência:** app planejado na `8765` (porta livre). Porém o `~/.kube/config` compartilhado contém **3 contextos EKS de trabalho** (verificado); qualquer operação `kubectl` do backend **deve** sempre passar `--context cka` explícito (nunca confiar no current-context, que o usuário troca durante o dia).
- **Correção aplicada:** regra explícita em `ARCHITECTURE.md` §3 (wrapper `cluster.py` sempre injeta `--context`); backend usa kubeconfig dedicado `~/.cka-arena/kubeconfig` copiado do `admin.conf` no primeiro doctor (imune a trocas de current-context do usuário).

### 🟡 G11 — Cenários de `etcd` restore: `etcdctl` existe no Mac, mas restore tem de rodar no nó
- **Evidência:** `/opt/homebrew/bin/etcdctl` presente no Mac; porém snapshot/restore do CKA exige os certificados e o `etcdctl` da versão correta **no controlplane**, com API v3 e `--data-dir`.
- **Correção proposta:** spec do gerador (system prompt) já deve restringir comandos etcd a `node: controlplane` via SSH; adicionado como nota no `LLM_SCENARIO_SPEC.md` (check `node_command_exit_zero` com `node: controlplane`). *(Ajuste menor aplicado ao template em §4 do spec.)*

### 🟡 G12 — Weave Net × NetworkPolicy: dependência do `weave-npc`
- **Evidência:** cenários de NetworkPolicy assumem enforcement; Weave só aplica NetworkPolicy se o `weave-npc` estiver rodando.
- **Correção proposta:** `ClusterDoctor` verifica pods `weave-npc-*` e reporta addon "NetworkPolicy enforcement: on/off". Adicionado à lista de addons em `ARCHITECTURE.md` §7.

---

## 4. Melhorias Recomendadas (Priorizadas)

| ID | Melhoria | Prioridade | Onde entra |
| :--- | :--- | :--- | :--- |
| M1 | Terminal web integrado (PTY + xterm.js) com abas por nó e Check ao alcance da mão | **P0** | `ARCHITECTURE.md` §8, `UX_UI_SPEC.md` §2, `PLAN.md` Fase 2/4 |
| M2 | Cluster Power Manager com boot instrumentado + CTA "Ligar Cluster" + `auto_start_on_launch` | **P0** | `ARCHITECTURE.md` §9, `UX_UI_SPEC.md` §3, `PLAN.md` Fase 1 |
| M3 | Self-heal de kubeconfig + regeneração do bloco SSH pós-boot (DHCP) | **P0** | `ARCHITECTURE.md` §9.3 |
| M4 | Kubeconfig dedicado `~/.cka-arena/kubeconfig` (imune a current-context do usuário) | **P1** | `ARCHITECTURE.md` §3 |
| M5 | Bootstrap da chave via `SSH_ASKPASS` (sem `sshpass`/expect) com fallback manual | **P1** | `ARCHITECTURE.md` §3 |
| M6 | Settle window antes do sanity check (G6) | **P1** | `PLAN.md` Fase 3 |
| M7 | Audit opcional de comandos do terminal → telemetria de abordagem | **P2** | `ARCHITECTURE.md` §6, §8.5 |
| M8 | Catálogo de providers (GLM/OpenCode/DeepSeek/Claude/OpenAI-compat) como base do `llm_client.py` | **P1** | `PLAN.md` Fase 3 |
| M9 | Estado `daemon_down` do multipass com instrução de correção | **P1** | `ARCHITECTURE.md` §9 |
| M10 | Importação do histórico do `cka-30-dias/learning-records` para recomendação do próximo domínio | **P2** | `PLAN.md` Fase 5 |
| M11 | Gateway API / metrics-server / local-path: instalar via Cluster Doctor com detecção `weave-npc` | **P1** | `ARCHITECTURE.md` §7 |

---

## 5. Decisões de Integração (Síntese do Que Foi Especificado)

```mermaid
flowchart LR
    subgraph Browser["Browser — http://127.0.0.1:8765 (janela única)"]
        UI["Exam Workspace\n(questão · check · timer)"]
        Term["Terminal Integrado (xterm.js)\nabas: mac · controlplane · node01 · node02"]
        Pwr["Pill Cluster: ⏻ Off / ⟳ Starting / ● Ready"]
    end
    subgraph Backend["FastAPI (127.0.0.1)"]
        WS["/ws/terminal/{tab}\nTerminalService (PTY host)"]
        PM["ClusterPowerManager\nmultipass start/stop + boot checks"]
        SE["ScenarioEngine\nsetup → check → cleanup"]
        LLM["LLM Generator\n(envelope + self-healing)"]
    end
    Term <-->|WebSocket| WS
    WS -->|zsh no host: kubectl/ssh/helm| Host["macOS Host"]
    Pwr -->|POST /api/cluster/power| PM
    PM -->|multipass CLI| MPX["Multipass Daemon\ncontrolplane · node01 · node02"]
    PM -->|SSH bridged (IPs dinâmicos)| MPX
    UI -->|Check| SE
    SE -->|kubectl --context cka / SSH| MPX
    LLM -->|envelope| SE
```

**Princípios fixados:**
1. O terminal executa **no host macOS** (onde vivem `kubectl`, `helm`, `~/.ssh/config`) — nunca dentro de um container; abas de nó são `ssh cka-<nó>` automáticos.
2. Um **único cenário ativo por vez** no cluster (setup do próximo só no clique de Next) — regra mantida.
3. O terminal é **persistente no backend**: reload da página reconecta ao mesmo PTY (registro de sessões por `tab_id`).
4. `Check` é acessível **do painel do terminal** (botão + atalho global ⌘↵) — requisito "executar e pedir validação" no mesmo lugar.
5. Cluster `off` **bloqueia** Studio e Workspace; a única ação disponível é Ligar (ou restaurar baseline com cluster em estado degradado).

---

## 6. Matriz de Rastreabilidade (Gap → Documentação)

| Gap | Correção documentada em |
| :--- | :--- |
| G1 terminal browser | `ARCHITECTURE.md` §1/§5/§8 · `UX_UI_SPEC.md` §1/§2 · `PLAN.md` §3.1 |
| G2 ciclo de vida | `ARCHITECTURE.md` §9 · `UX_UI_SPEC.md` §3 · `PLAN.md` §3.6/Fase 1 |
| G3 DHCP/kubeconfig | `ARCHITECTURE.md` §9.3 |
| G4 bootstrap chave | `ARCHITECTURE.md` §3 |
| G5 spec terminal | `ARCHITECTURE.md` §8 · árvore §5 · DB §6 |
| G6 settle window | `PLAN.md` Fase 3 |
| G7 daemon multipass | `ARCHITECTURE.md` §9 |
| G8 segurança WS | `ARCHITECTURE.md` §10 |
| G9 audit comandos | `ARCHITECTURE.md` §6/§8.5 (opt-in) |
| G10 kubeconfig dedicado | `ARCHITECTURE.md` §3 |
| G11 etcd no nó | `LLM_SCENARIO_SPEC.md` §4 (nota) |
| G12 weave-npc | `ARCHITECTURE.md` §7 |

## 7. Fora de Escopo Desta Revisão

- Implementação de código (o projeto segue em fase de planejamento; as specs agora cobrem os novos requisitos).
- Multiusuário / exposição remota da plataforma (local-only por design; ver §10 da arquitetura).
- Suporte a clusters outros além do `cka` Multipass (kind/k3s/minikube) — arquitetura permite no futuro via interface `ClusterDriver`, mas não é planejado.


---

## 8. Segunda Auditoria — Geração LLM, Banco de Questões, Check & Teardown (Revisão 2)

> Nova rodada sobre: fluxo de geração com agentes (LangGraph?), banco de questões com sorteio pelas percentuais da prova, contrato do Check e reset limpo do cluster ao fim da sessão. Especificação resultante: **`LLM_PIPELINE_SPEC.md`** (novo).

### 🔴 G13 — Geração acoplada à sessão (sem banco de questões)
- **Evidência:** `ARCHITECTURE.md` §6 original: tabela `scenarios` com `session_id` — a fila gerada *era* a sessão; questões boas não eram reutilizadas e "praticar de novo" exigia nova geração (custo LLM + risco).
- **Correção aplicada:** desacoplamento total — geração **publica** em `bank_questions` (ciclo `draft → probed → published → retired`, dedup semântico, envelope imutável, métricas por questão); sessões só referenciam (`session_items`). `ARCHITECTURE.md` §6/§11 · `LLM_PIPELINE_SPEC.md` §3.

### 🔴 G14 — Sem sorteio pelas percentuais da prova
- **Evidência:** nenhum documento definia como montar a bateria de prática; o Studio antigo gerava N questões direto para a fila.
- **Correção aplicada:** `draw_exam_sample` com **largest remainder** sobre os pesos CNCF (30/25/20/15/10), renormalização por filtros, fallback de célula vazia e anti-repetição (`times_used ASC, random()`); preview da distribuição na UI antes de iniciar. Calibração: N=15 → 5/4/3/2/1; N=5 → 2/1/1/1/0; N=3 → 1/1/1/0/0. `LLM_PIPELINE_SPEC.md` §4 · `UX_UI_SPEC.md` §5a.

### 🔴 G15 — Nenhuma garantia de que a questão é solúvel
- **Evidência:** o sanity check só provava que os checks **falhavam** antes do usuário agir — nada provava que existia caminho de solução; questão insolúvel só seria descoberta na prática (o pior momento).
- **Correção aplicada:** bloco obrigatório **`solution`** no envelope (manifests/comandos automatizáveis) + **Solvability Probe** no Estágio E: aplica a solução num clone de prova e exige 100% PASS antes de publicar. `LLM_SCENARIO_SPEC.md` §1.1 · `LLM_PIPELINE_SPEC.md` §2E.

### 🔴 G16 — Teardown de fim de sessão inexistente
- **Evidência:** cleanup era só por questão (`cleanup(scenario)`); aborto de sessão no meio de um Boss Fight deixava resíduo acumulando entre sessões. O requisito "cluster zerado e reiniciado limpo" não tinha dono.
- **Correção aplicada:** teardown em 3 níveis — **L0** por questão, **L1** fim de sessão (label sweep `cka-arena.io/managed` + drift check) e **L2 clean reset** (L1 + restauração do baseline de arquivos dos nós + restart de `containerd`/`kubelet` + drift check). **Atualização da Fase 5 (evidência ao vivo):** snapshots de VM **não são implementados** no backend do Multipass/macOS (`The snapshots feature is not implemented on this backend`) — o L2 foi redefinido sem snapshots e validado com `drift=false`, 3/3 Ready e addons preservados. `LLM_PIPELINE_SPEC.md` §6 · `ARCHITECTURE.md` §12 · `UX_UI_SPEC.md` §5b.

### 🟡 G17 — Semântica do Check informal
- **Evidência:** o catálogo definia *o que* verificar, mas não *como decidir*: sem distinção FAIL (estado do usuário) × ERROR (infra), sem política de retry, sem veredito formal da questão.
- **Correção aplicada:** contrato formal — status `PASS`/`FAIL`/`SKIP`/`ERROR` com política de retry (FAIL nunca re-executa sozinho; ERROR 2× com backoff; rodada inválida não consome tentativa), veredito **all-or-nothing** (como a CKA real), evidência `expected/actual` por item, hint com revelação progressiva, timeouts por tipo e settle window. `LLM_PIPELINE_SPEC.md` §5 · `LLM_SCENARIO_SPEC.md` §2.

### 🟡 G18 — Framework de agentes (LangGraph/LangChain) sem avaliação registrada
- **Evidência:** proposta do usuário de 3 agentes encadeados (normalizador → construtor → validador) sem análise de orquestração.
- **Correção aplicada:** avaliação comparativa (`LLM_PIPELINE_SPEC.md` §1): os 3 agentes **são mantidos** como estágios LLM com contrato estrito, orquestrados por **máquina de estados própria em async Python** — sem LangGraph/LangChain (fluxo linear com retries limitados não justifica peso/dependência/churn; independência de provider já vem do cliente multi-provider próprio). Gatilhos de revisita documentados (tool-use autônomo, human-in-the-loop resumível).

### Rastreabilidade da Revisão 2

| Gap | Correção documentada em |
| :--- | :--- |
| G13 banco | `LLM_PIPELINE_SPEC.md` §3 · `ARCHITECTURE.md` §6/§11 · `PLAN.md` Fase 3 |
| G14 sorteio | `LLM_PIPELINE_SPEC.md` §4 · `UX_UI_SPEC.md` §5a · `PLAN.md` verificação 6 |
| G15 solvability | `LLM_SCENARIO_SPEC.md` §1.1 + regra 10 · `LLM_PIPELINE_SPEC.md` §2E |
| G16 teardown | `LLM_PIPELINE_SPEC.md` §6 · `ARCHITECTURE.md` §12 · `UX_UI_SPEC.md` §5b · `PLAN.md` Fases 1/2 |
| G17 contrato check | `LLM_PIPELINE_SPEC.md` §5 · `LLM_SCENARIO_SPEC.md` §2 |
| G18 orquestração | `LLM_PIPELINE_SPEC.md` §1 (comparativo + gatilhos) |

---

## 9. Terceira Auditoria — Idioma, Formato de Prova e Dificuldade (Revisão 3)

> Mudança de escopo do dono: **sistema 100% inglês** (a prova CKA é em inglês), questões no **formato exato da prova** e níveis de dificuldade **mensuravelmente distintos**.

### 🔴 G19 — Sistema especificado em PT-BR, oposto ao idioma da prova
- **Evidência:** envelope com `prompt_pt_br`/`reference_solution_pt_br`, regra 1 do system prompt exigindo "Português do Brasil", UI com labels `[Verificar]`/`[Próxima]`/`[Ligar Cluster]` em todos os wireframes e no mockup.
- **Impacto:** treinar lendo tarefas em PT-BR não constrói a memória muscular de leitura do enunciado em inglês — parte real da performance na prova.
- **Correção aplicada:** campos renomeados `prompt`/`reference_solution`; regra 1 do prompt e rubrica do Revisor (item 6) exigem **exam voice em inglês**; UI 100% English em todos os specs, wireframes, CTAs (`[Check]`, `[Next]`, `[Skip]`, `⏻ Power On & Practice`, `▶ Practice`, `SESSION COMPLETE`…) e no mockup. `PRODUCT.md` registra o compromisso; docs internos seguem PT-BR. Referência de formato: [killer.sh](https://killer.sh/cka) (simulador oficial) — nova seção `LLM_SCENARIO_SPEC.md` §1.2 com a anatomia exata (título imperativo · Task weight · Use context · contexto-sintoma · "Perform the following tasks" · restrições).

### 🔴 G20 — Níveis de dificuldade subjetivos (não verificáveis)
- **Evidência:** a definição anterior dos níveis era prosa ("1 a 2 requisitos claros…") sem banda mensurável nem enforcement — um `boss_fight` fraco passaria.
- **Correção aplicada:** **rubrica mensurável** (`LLM_SCENARIO_SPEC.md` §5): 8 eixos medidos direto do envelope (requisitos, kinds, escopo, traps, cadeia causal, checks, meta de tempo, peso) com bandas disjuntas por nível + **enforcement no Revisor** (fora da banda em ≥ 2 eixos ⇒ regeneração com delta) e no Gate D (`boss_fight` sem falha de nó é rejeitado). Metas recalibradas: ≤ 4 / ≤ 7 / ≤ 12 min; exemplos calibrados do mesmo domínio nos três níveis ilustram a separação real.

### 🟡 G21 — Formato da questão não aderia ao padrão do exame
- **Evidência:** o `prompt` antigo era prosa livre em PT-BR ("No namespace X, existem os deployments…"), sem título, sem `Task weight`, sem "Use context:", sem bloco de restrições.
- **Correção aplicada:** anatomia canônica do exame (§1.2) como obrigação do Construtor e critério do Revisor; critério de aceite da Fase 3 (`PLAN.md`) exige questão "(a) em inglês no formato exato da prova".

### Rastreabilidade da Revisão 3

| Gap | Correção documentada em |
| :--- | :--- |
| G19 idioma | `LLM_SCENARIO_SPEC.md` §1/§1.2/§4-regra 1 · `LLM_PIPELINE_SPEC.md` §2 A–C · `UX_UI_SPEC.md` §1/labels · `PRODUCT.md` · `README.md` · `design/mockup-workspace.svg` |
| G20 dificuldade | `LLM_SCENARIO_SPEC.md` §5 (+ regra 2 do prompt) · `PLAN.md` §2 e Fase 3 |
| G21 formato de prova | `LLM_SCENARIO_SPEC.md` §1.2 · `PLAN.md` Fase 3 (critério de aceite) |