# Especificação de UX & UI — CKA Arena

> **Modo de Superfície:** *Operate* (ferramenta de alta concentração operacional). A interface deve desaparecer para dentro da tarefa: zero decoração gratuita, zero animações lentas, escaneabilidade instantânea e conforto visual para sessões longas de estudo.

> **Documento de referência** de UX. Onde divergir do que está implementado em `static/`, o código prevalece.

---

## 1. Princípio Central: Janela Única com Terminal Integrado (Dual-Window Opcional)

O fluxo primário é **tudo dentro do navegador**, em uma única janela:
- **Coluna Esquerda (~44%):** enunciado, contexto obrigatório, Copy-Pills, resultado do Check e a barra **Check → Next**.
- **Coluna Direita (~56%):** **terminal real** (xterm.js sobre PTY do host) com abas criadas pelo popover **`+ Shell`** (`Local shell · controlplane · node01 · node02`) — `kubectl`, `vim`, `helm` e `ssh` executam ali mesmo. O shell local nasce numa **workdir isolada** (`~/.cka-arena/scratch/<tab>`, exibida no rodapé): YAMLs e temporários nunca sujam a pasta do projeto, e o `kubectl` usa o kubeconfig dedicado (context `cka`).
- **Check tem uma única ação** — botão no rodapé da coluna da questão, repetido na barra do terminal — e é disparável de qualquer foco via **`⌘↵`** (interceptado antes do xterm): o ciclo *editar → verificar → corrigir* acontece sem trocar de painel.
- **Toggle `[⌗ Native]`** (rodapé do terminal): recolhe o painel embutido e devolve a ergonomia dual-window original (40% browser / 60% terminal nativo) para quem prefere o terminal do SO; as Copy-Pills continuam copiando para o clipboard.
- **Idioma da UI: 100% inglês** (Revisão 3): labels, botões, toasts, previews, enunciados e hints — a prova CKA é em inglês e o treino inclui ler tarefas e feedback no idioma do exame. Strings de UI mostradas neste spec (wireframes, CTAs) já estão em inglês.

**Regra de Responsividade Estrutural:**
- `≥ 1100px`: split Questão | Terminal lado a lado (padrão de estudo).
- `700–1099px`: terminal vira painel alternável por tabs no rodapé (`[Questão] ⇄ [Terminal]`) — nunca scroll horizontal.
- `480–699px`: coluna única; terminal abre em bottom-sheet de `70vh` (preserva o uso em janela estreita ao lado do terminal nativo).
- O `Check Result Drawer` expande **inline sob o enunciado** e jamais cobre o terminal durante o Check.

---

## 2. Wireframes (Workspace Integrado · Home com Cluster Off)

**a) Exam Workspace — as duas colunas abaixo vivem lado a lado na mesma janela (≥ 1100px):**

```text
┌──────────── Coluna Esquerda ~44% (Questão) ────────────┐
│ CKA ARENA [Q1 ✓][Q2 ●][Q3 🔒]  Cluster: ● 3/3 [⏻]      │  ← header GLOBAL (ver c)
│ Troubleshooting (30%) · Peso 8% · Hardcore ⏱ 04:32/07:00 │
│ ────────────────────────────────────────────────────── │
│ REQUIRED CONTEXT                                        │
│ > kubectl config use-context cka                 [Copy] │
│ > ssh cka-node01                                  [Copy] │
│ ────────────────────────────────────────────────────── │
│ TASK                                                   │
│ A Deployment `web-api` in `prod-checkout` is running   │
│ 1/3 replicas after node maintenance...                │
│ Perform the following tasks:                          │
│ 1. Restore the `kubelet` on `node01` until Ready      │
│ 2. Scale `web-api` to `3` replicas                   │
│ 3. Pin all pods to `node01` via `nodeSelector`       │
│ Docs: ↗ Node Troubleshooting ↗ Assigning Pods to Nodes │
│ ────────────────────────────────────────────────────── │
│ CHECK RESULTS (after clicking Check)                  │
│ ✅ [PASS] Node `node01` reports `Ready=True`          │
│ ❌ [FAIL] `web-api` has 1/3 replicas ready            │
│    ↳ Expected 3 ready; current: 1.                    │
│ ❌ [FAIL] Pods missing nodeSelector for `node01`      │
│    ↳ `spec.template.spec.nodeSelector` missing.       │
│ ────────────────────────────────────────────────────── │
│ [↻ Reset] [🏳 Skip] [✓ Check (⌘↵)]  [🔒 Next →]       │
└────────────────────────────────────────────────────────┘

┌──────────── Coluna Direita ~56% (Terminal) ────────────┐
│ TERMINAL  [mac][controlplane][node01][node02] [+] [⏹] │
│ $ kubectl config use-context cka                       │
│ Switched to context "cka".                             │
│ $ kubectl -n prod-checkout get deploy web-api          │
│ NAME      READY   UP-TO-DATE   AVAILABLE               │
│ web-api   1/3     1            1                       │
│ $ ▌                                                    │
│        (PTY do host · reconecta em reload)             │
│ ────────────────────────────────────────────────────── │
│ [⌥T New Tab] [⌘K Clear]   [✓ Check (⌘↵)]  📋        │
│   ↑ same endpoint as the question's Check:            │
│     validate without leaving the terminal             │
└────────────────────────────────────────────────────────┘
```

**b) Home com cluster desligado (estado `off` → CTA único):**

```text
┌────────────────────────────────────────────────────────┐
│ CKA ARENA                                    ⏻ Off     │
│                                                        │
│            ⏻  POWER ON & PRACTICE                     │
│   (live boot: ✓ VMs ✓ SSH ⟳ API … step 4/7)           │
│                                                        │
│   [Studio locked · cluster must be Ready]             │
│   [Workspace locked · cluster must be Ready]          │
└────────────────────────────────────────────────────────┘
```

**c) Header global — pill de estado do cluster (`power.js`):**

| Estado | Pill | Ação disponível |
| :--- | :--- | :--- |
| `ready` | `● Ready 3/3` (verde) | Menu: Desligar · Reiniciar · Doctor |
| `off` | `⏻ Off` (cinza) | **Power On** (CTA grande na home) |
| `starting` | `⟳ Starting · step N/7` (âmbar, animado) | Cancel boot |
| `degraded` | `▲ Degraded` (âmbar) | View diagnosis · Restore Baseline |
| `daemon_down` | `⨯ Multipass` (coral) | Fix instructions (restart the node provider daemon) |

---

## 3. Regras de Interação & Mecânica `Check -> Next`

### A. Copy-Pills Automáticos (Zero Erro de Digitação)
- No exame real da CKA, perder 30 segundos por errar uma letra em um nome de namespace ou recurso custa caro.
- Todo token cercado por crases `` `...` `` no enunciado (ex.: `` `prod-checkout` ``, `` `web-api` ``, `` `allow-api-to-db` ``) é renderizado como um **chip clicável (`Copy-Pill`)** com fonte monospace.
- Clicar no chip copia o texto exato (sem crases) para o clipboard e mostra um feedback micro-interativo sutil (`border` verde + tooltip rápido `Copiado`).

### B. O Ciclo Rígido `Check` → `Next`
1. **Estado Inicial da Questão:**
   - Botão **`[✓ Check (⌘↵)]`** ativo em destaque primário.
   - Botão **`[🔒 Next →]`** visivelmente **desabilitado (`disabled`)**, com ícone de cadeado e título explicativo: *"Validate 100% of the criteria in the Check to unlock the next question"*.
2. **Ao clicar em `Check`:**
   - O botão entra em estado de carregamento (`Checking cluster…`) e desabilita duplo-clique.
   - O backend executa todas as asserções determinísticas em paralelo e retorna o array de resultados.
   - O **Check Result Drawer** abre inline acima da barra de rodapé listando cada critério com ícone verde (`PASS`) ou coral (`FAIL`) e o `failure_hint` técnico (apontando o sintoma real do cluster, **sem dar o comando pronto**).
3. **Ao atingir 100% `PASS`:**
   - O timer da questão congela registrando o tempo final (ex.: `Concluída em 04:18 · Dentro da meta!`).
   - O botão **`[🔓 Next →]`** transiciona (`200ms`) para estado ativo em **Verde Esmeralda** (ou torna-se **`[🏆 Finish Session]`** na última questão).
   - O botão **`[View Reference Solution]`** é desbloqueado como toggle recolhido caso o usuário queira comparar sua abordagem imperativa com a solução ideal.
4. **Ao clicar em `Next →`:**
   - Executa automaticamente o `cleanup` da questão atual, aplica o `setup` da questão seguinte (exibindo um overlay leve de 1–3s: *"Preparing scenario Q3 on the cluster…"*) e reinicia o timer para a nova questão.
5. **Válvula de Escape Controlada (Anti-Travamento):**
   - Caso um cenário esteja realmente bloqueante ou o usuário queira abortar, o botão discreto **`Skip / Give up`** abre uma confirmação de 1 passo (*"Mark this question as unsolved and unlock the next one?"*). Somente após confirmação explícita ela muda de estado para `skipped` e libera o avanço + solução.

### C. Check sem Sair do Terminal (Requisito Central de Integração)
1. `⌘↵` e `⌘⇧↵` são interceptados **antes** de chegarem ao xterm: os atalhos funcionam mesmo com o terminal focado; o botão Check (coluna da questão) mostra `Checking… Ns` durante a rodada (deadline de 90s no backend — nunca loading infinito).
2. Após o resultado do Check chegar, o foco **retorna ao terminal** (o usuário lê o drawer da coluna esquerda sem perder o cursor).
3. Copy-Pills, além de copiar, movem o foco para o terminal (fluxo: clicar no pill → ⌘V no terminal).
4. `Reset`/`Skip` confirmados reiniciam o cenário **sem fechar as abas do terminal**; sem sessão ativa, `Reset`/`Skip`/`Check` ficam `disabled`.
5. Abas de nó (`controlplane`, `node01`, `node02`) abrem `ssh cka-<nó>` já autenticado com a chave dedicada; se o bridge ainda não foi provisionado, a aba exibe hint do Cluster Doctor em vez de um prompt de senha preso.

---

## 4. Anatomia do "Scenario Studio" (Gerador de Cenários via LLM)

Acessível pela view **Studio** do segmented control (`⌘2`; também pelo CTA "Generate with AI" do empty state). **A geração publica no banco de questões** — não cria mais uma fila ativa: praticar é um fluxo separado (§5), que sorteia do banco pelas percentuais da prova:

1. **Seletor de Domínios CKA (Multi-Select com Pesos Oficiais):**
   - `[x] Troubleshooting (30%)`
   - `[x] Cluster Architecture, Installation & Config (25%)`
   - `[ ] Services & Networking (20%)`
   - `[ ] Workloads & Scheduling (15%)`
   - `[ ] Storage (10%)`
   - *Sub-chips opcionais por domínio:* ao marcar *Cluster Architecture*, aparecem chips clicáveis (`etcd backup/restore`, `RBAC`, `Helm`, `Kustomize`, `CRDs`). Ao marcar *Services & Networking*, aparecem (`Gateway API`, `NetworkPolicy`, `Ingress`, `CoreDNS`). Se nenhum chip for marcado, a LLM sorteia livremente dentro dos domínios escolhidos.
2. **Seletor de Dificuldade:**
   - `Exam Standard` — Fiel à prova oficial
   - `Killer.sh Hardcore` *(Padrão recomendado)* — Mais difícil que a prova, 3–4 requisitos + armadilhas
   - `Boss Fight` — Caos multi-nó + workload dependente
3. **Tamanho da Bateria & Foco Extra (Prompt Opcional):**
   - Chips rápidos: `1 Scenario` | `3 Scenarios` | `5 Scenarios` | `Full Mock Exam (15)`
   - Campo opcional de 1 linha: *"Extra focus or constraint (optional)"* — ex.: *"I want to practice broken static pods and avoid Helm in this batch"*.
4. **Progresso Transparente do Pipeline (SSE + live card):**
   - **Live job card** sempre visível durante e após a geração: chip de status (`running` pulsando / `done` / `failed`), `Qn/total · stage · elapsed` com o detalhe do passo atual, contadores (`published · quarantined · attempted`), barra de progresso e **uma linha por cenário** com mini-stages `A B C D E` (✓ concluído, ● atual, ✗ reprovado), tentativa (`try N`) e detalhe ao vivo.
   - **Event log** recolhível (últimos 40 eventos com timestamp) para auditoria do que o pipeline estava fazendo.
   - **Heartbeat de 4s** do backend mantém o card vivo mesmo durante chamadas LLM longas, probes e loops de convergência (sanity/rollout); sem heartbeat por >10s o elapsed continua correndo e o detalhe permanece no último passo.
   - **Recuperação em reload/SSE drop:** o backend mantém o estado do job e o card é reconstruído via `GET /api/generate/status` + evento `generation.snapshot` ao conectar — a geração nunca "desaparece" da tela.
   - Cenários reprovados aparecem como `Q1 ✗ quarantined (draft): <motivo>`; após o orçamento de correções a questão vai para `draft` (nunca serve para prática).
   - *Nota de UX:* durante a geração, o cluster é usado **apenas** no namespace efêmero de prova (`cka-arena-prove-<uuid>`, descartado ao final) — nenhum setup de questão real é aplicado nesta fase; o setup acontece na hora de **Praticar** (§5).
5. **Gating por estado do cluster:** com o cluster `off`/`starting`, o Studio permanece bloqueado com pill explicativa e o CTA **"⏻ Power On"**; a geração só é permitida em `ready` (ou `degraded`, com aviso de risco e sugestão de Restaurar Baseline).
6. **Grade de Cobertura do Banco (5 domínios × 3 dificuldades):** rodapé do Studio com contagens por célula (`GET /api/bank/coverage`); células com < 3 questões `published` destacadas em âmbar + CTA contextual "Generate 3× {cell}". Questões `draft`/`retired` não contam.

---

## 5. Practice from Bank & Session End

**a) Modal "Practice"** (CTA `[▶ Practice]` no header; exige cluster `ready`):
1. **Quantidade:** chips `3 · 5 · 15 (mock exam) · custom` — o sorteio segue as **percentuais oficiais da prova** por *largest remainder* (Troubleshooting 30% · Cluster Architecture 25% · Services & Networking 20% · Workloads 15% · Storage 10%).
2. **Filtros opcionais:** domínios e/ou dificuldade (default: todos; pesos renormalizados sobre o subconjunto).
3. **Preview da distribuição antes de iniciar:** *"You will get: 5× Troubleshooting · 4× Cluster Architecture · 3× Services & Networking · 2× Workloads · 1× Storage"* — com badge âmbar quando houver fallback de célula vazia (*"Storage Hardcore: empty — filled with S&N"*) e CTA "Generate more first".
4. `[Start Session]` → sorteio (ordena por `times_used ASC, random()`; sem repetição dentro da sessão) → setup da Q1 aplicado no cluster → tela de questão + terminal (§2a).

**b) Fim de Sessão — resumo + limpeza do cluster** (requisito: cluster zerado e limpo ao final):

```text
┌──────────────────────────────────────────────────────┐
│  SESSION COMPLETE · 11/15 · 68% first-try passes     │
│  Total time 78 min · weakest: Storage (2/5)          │
│ ──────────────────────────────────────────────────── │
│  Clean up the cluster now?                           │
│  [✓ Fast Cleanup (L1 · ~30s)]     ← default          │
│  [⟳ Clean Reset (L2 · ~2 min)]                        │
│   (drift detected → L2 recommended; mock exams       │
│    always run L2 automatically)                      │
```

- **L1 (default):** varredura global de recursos labelados `cka-arena.io/managed: "true"` + restauração de backups de nós pendentes + drift check (~30s) — cluster pronto para a próxima sessão.
- **L2 (Clean Reset):** L1 + restauração do baseline de arquivos dos nós + restart de `containerd`/`kubelet` + espera Ready + drift check (~1–2 min) — addons preservados; snapshots de VM não são suportados no Multipass/macOS. Automático após simulados `mock_exam` e recomendado quando o drift check acusa divergência.
- Especificação dos níveis L0/L1/L2 e política completa: `LLM_PIPELINE_SPEC.md` §6 · `ARCHITECTURE.md` §12.

---

## 6. Sistema Visual — Orbital Control Console (contrato completo em `DESIGN.md`)

Identidade: **console de missão operacional sobre superfícies anodizadas escuras em `oklch()`** (`--canvas` → `--bay` → `--surface` → `--surface-raised`), linhas estruturais `1px` hairline, acento cirúrgico **Ice Cyan** (`oklch(76% 0.145 208)`), conteúdo crítico (Markdown do enunciado, terminais PTY `xterm.js` em `#0A0D13`) sempre fosco e opaco, com `backdrop-filter` reservado exclusivamente a `<dialog>` top-layer (`Command Palette ⌘K` e modais). Contrato completo em [`DESIGN.md`](./DESIGN.md).

- **Estrutura de Shell Único (`54px` Rail + `48px` Topbar):** Rail lateral esquerdo com ícones SVG unificados (`stroke 1.6px`), status de cluster `[popover="auto"]` no rodapé da rail, e Topbar contextual limpa contendo apenas a fila de questões, timer/pacing e CTA da sessão.
- **Tipografia & Hierarquia:** Interface e Markdown `Figtree` (`400–700`, `max-inline-size: 68ch`); terminal, timers, tabelas e YAML `JetBrains Mono` com `tabular-nums`. Escala `rem` fixa com piso ≥ `12px`.
- **Primitivas Web Nativas:** Troca de views com `document.startViewTransition()`, modais em `<dialog>` com `@starting-style` + `transition-behavior: allow-discrete`, menus `+ Shell` e `Cluster Power` em `[popover="auto"]` ancorados via CSS Anchor Positioning com fallback.
- **Sub-abas na Arena & Studio:** Painel da questão dividido em `Task & Check`, `Checklist & Notes` e `Hints & Docs`; coluna direita do Studio dividida em `Pipeline & Coverage` (com Heatmap `5×3` clicável) e `Bank Inspector`.
- **Atalhos de Teclado:**
  - `⌘ + K` → Abre **Command Palette** global (navegação, drills, tabs SSH, comandos)
  - `⌘ + Enter` → Aciona **Check** — global, inclusive com o terminal focado
  - `⌘ + Shift + Enter` → Aciona **Next** quando desbloqueado
  - `⌘ + B` → Alterna **Zen Terminal** (terminal em largura total)
  - `⌘ + F` → Busca no histórico scrollback do terminal
  - `⌘ + L` → Limpa o terminal ativo · `⌘ + 1..5` → Troca de visão (Arena/Readiness/Studio/Settings/Study Codex) · `⌘ + /` → Modal de atalhos · `Esc` → Fecha modal/busca
- Nos atalhos acima, `⌘` vale para o macOS; no Linux/WSL2 o modificador é `Ctrl` (e `Ctrl+Shift` quando o terminal está focado). A lista exibida na UI é a do modal de atalhos (`⌘/`).
