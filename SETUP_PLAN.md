# SETUP_PLAN — `setup.sh` universal + publicação OSS do CKA Arena

> Plano de adaptação para que qualquer pessoa clone o repositório no GitHub e rode
> `./setup.sh` para ter a plataforma funcionando localmente. Requisitos do dono (verbais, 18/11/2026):
> (1) o script sobe tudo — cluster, banco, addons; (2) detecta distro/S.O.; (3) detecta pré-requisitos
> e, se faltarem, avisa **o que** falta e pede confirmação para instalar; (4) loads dinâmicos e
> coloridos; (5) ao final mostra a URL e o que configurar; (6) **saída 100% em inglês**.
>
> **Revisão 2 (18/11/2026):** requisito novo do dono — **WSL2 também precisa funcionar**.
> Virtualização aninhada dentro do WSL2 (`/dev/kvm`) não é confiável → Multipass **dentro** do
> WSL está descartado; o caminho viável é um **driver de nós alternativo (kind/Docker)**, o que
> exige uma pequena abstração de provider na plataforma (§2.1, D7–D9).

---

## 1. Inventário — o que existe vs. o que falta para OSS

| Necessidade | Estado hoje | Gap para `setup.sh` público |
| :--- | :--- | :--- |
| Rodar o servidor | `uv run cka-arena` (FastAPI, `127.0.0.1:8765`) | nenhum — só garantir `uv sync` |
| Banco | SQLite em `data/cka_arena.db`, **auto-init** no startup (`db.init_db`) | nenhum — o script só publica os seeds (`python -m app.seed`) |
| **Driver de nós** | ❌ Multipass **hardcoded**: `ssh_runner.multipass()` (choke point único), SSH por IP nos checks/node_commands, `power._boot/_stop`, preset de terminal `ssh cka-<node>` | **provider abstraction** (§2.1) para caber WSL2/kind sem mexer no caminho Multipass |
| Host `kubectl` | `cluster.py` chama o binário `kubectl` do host | prereq explícito do setup (faltava na Rev.1 — vale para **todos** os S.O.s) |
| **Provisionar o cluster** | ❌ **não existe no repo**: as VMs foram criadas por `certified-kubernetes-administrator-course/kubeadm-clusters/apple-silicon/deploy-virtual-machines.sh` (**macOS/arm64-only**, BRIDGE, jq+multipass, cloud-init externo) | **gap central**: vendor + generalizar (Linux, x86_64, detecção de bridge por SO) |
| Addons (metrics-server, Gateway API+Envoy, local-path) | ❌ instalados **manualmente**; `doctor.py` só detecta e sugere `bootstrap_plan` | novo `app/addons.py` idempotente chamado pelo setup |
| SSH bridge (chave + `~/.ssh/config` cka-*) | ✅ `ssh_runner.py` instala via `SSH_ASKPASS` com `LAB_PASSWORD` (default `ubuntu`) | nenhum — exige cloud-init com `ssh_pwauth: true` + password ubuntu |
| Kubeconfig dedicado (context `cka`) | ✅ `~/.cka-arena/kubeconfig` com self-heal | export no setup a partir do `admin.conf` do controlplane |
| Config LLM (Studio) | loader: `llm_config.json` do projeto → `CKA_LLM_CONFIG` → env `CKA_LLM_*`; **configurável pela UI (Settings → AI provider)** | nenhum gap — geração é opcional (Practice funciona sem LLM) |
| VMs | nomes fixos `controlplane/node01/node02`, `NODE_ALIAS cka-*`, `BRIDGE_PREFIX 192.168.1.` | prefixo de rede já é detectável — setup detecta a subnet da bridge e exporta `CKA_BRIDGE_PREFIX` |
| Idempotência/restart | `power.py` liga/desliga; `auto_start` no launch | setup não re-provisiona o que já existe (`multipass list` + marcador) |

**Decisão estrutural do plano:** o script de cluster do curso é **vendado** para
`scripts/cluster/` (com crédito) e generalizado; o setup orquestra, mas cada etapa é
um script testável isoladamente.

---

## 2. Arquitetura

```text
setup.sh                      # orquestrador fino (≤200 linhas): parse flags, ordem dos steps, banner final
scripts/
  lib/ui.sh                   # cores/spinner/confirm/banner  (§5 — o "load dinâmico colorido")
  lib/detect.sh               # OS/distro/arch/TTY/gerenciador de pacote
  lib/pkg.sh                  # install por gerenciador (brew/apt/dnf/pacman/snap) + confirm
  lib/state.sh                # marcadores idempotentes em ~/.cka-arena/setup.state
  cluster/up.sh               # VMs Multipass + cloud-init + kubeadm init/join (vendor generalizado)
  cluster/kind-up.sh           # driver WSL/Linux-Docker: kind 3 nós + weave CNI + mapeamento de nomes
  cluster/addons.sh           # → chama `uv run python -m app.addons` (idempotente)
app/addons.py                 # bootstrap dos addons via cluster.py (mesmo caminho do runtime)
.env.example                   # CKA_LAB_PASSWORD, CKA_LLM_CONFIG, CKA_BRIDGE_PREFIX (documentado em inglês)
```

**Flags:** `--yes` (não-interativo/CI), `--check` (dry-run: só audita prereqs e sai),
`--provider multipass|kind` (default: auto por ambiente — WSL2 → kind, §2.1),
`--skip-cluster` (já tenho nós), `--bridge <iface>` (override da detecção; provider multipass),
`--llm-config <path>`, `--with-addons|--no-addons` (default: com), `--step <name>` (re-roda um step).

**Idempotência:** cada step grava chave em `~/.cka-arena/setup.state`
(`cluster_up`, `ssh_bridge`, `kubeconfig`, `addons`, `seeds`); re-rodar pula o que
está feito e re-verifica (não apenas confia no marcador — valida o efeito).

### 2.1 Provider de nós (o que habilita o WSL2)

Hoje Multipass está colado em 4 pontos: `ssh_runner.multipass()` (CLI), exec por SSH
(checks `node_command`/`host_file_contains`, backups L2), `power._boot/_stop` e o preset
de terminal `ssh cka-<node>`. A adequação cria uma seam única:

```text
app/provider/
  base.py        # interface: nodes() -> [{name, ip, state}] · exec(node, cmd, sudo)
                 #            power_on() / power_off() · transport ("ssh"|"docker")
  multipass.py   # comportamento atual, 1:1 (pass-through — zero regressão no macOS)
  kind.py        # WSL2/Linux+Docker: nós = containers kind; exec = docker exec
```

Seleção: `CKA_PROVIDER=multipass|kind` (env) — o setup escolhe o default por ambiente
(WSL2 → kind; macOS/Linux com Multipass → multipass) e grava em `~/.cka-arena/provider`.

**`scripts/cluster/kind-up.sh` (script externo, cria o cluster):**
1. `kind create cluster --name cka --config` — 1 control-plane + 2 workers,
   `networking.disableDefaultCNI: true`;
2. aplica **weave-net** (mesma CNI do driver Multipass → NetworkPolicy/NPC continua
   funcionando nas questões de netpol);
3. exporta kubeconfig para `~/.cka-arena/kubeconfig` (context `cka`);
4. grava **mapeamento de nomes** `~/.cka-arena/nodes.json` — o kind nomeia workers
   `cka-worker/cka-worker2`; a plataforma continua falando `controlplane/node01/node02`
   (lógicos) e o provider traduz (D8);
5. addons pelo mesmo `app/addons.py`.

**Mapeamentos WSL2:** power on/off = `docker start/stop` dos containers de nó (kubelet
retoma dentro do container); `node_commands` e `host_file_contains` = `docker exec`;
preset de terminal de nó = `docker exec -it <nó> bash` (sem SSH, sem chave); L2-clean =
teardown + `kind create` de novo (~90 s — mais simples que restaurar arquivos de nó).

**Por que não Multipass dentro do WSL:** VM aninhada exige `/dev/kvm` exposto pelo
Windows ao WSL2 — indisponível na maioria dos hosts/versões; Docker no WSL2 usa
namespaces/cgroups do kernel compartilhado e funciona **sem** virtualização aninhada
(bônus: `--provider kind` serve também Linux sem Multipass e futuros ambientes de CI).

---

## 3. Detecção de S.O. e pré-requisitos

### 3.1 Matriz de suporte (decisão proposta — P1 explícito, resto avisa e continua)

| S.O. | Suporte | Provisionamento |
| :--- | :--- | :--- |
| macOS (arm64/x86_64) | ✅ P1 (caminho já validado) | Multipass via `brew` — bridge via `netstat -rn -f inet` |
| Ubuntu/Debian (x86_64/arm64) | ✅ P1 | Multipass via `snap` — bridge via `ip route` |
| Fedora/Arch | ⚠️ melhor-esforço (avisa: "tested on macOS/Ubuntu") | multipass via `dnf`/AUR quando disponível |
| WSL2 (Windows 11, systemd ativo) | ✅ via **driver kind** (§2.1) — Docker Engine nativo dentro do WSL, sem Docker Desktop e sem VM aninhada | `kind create` 3 nós + weave |
| WSL2 (Windows 10 / sem systemd) | ⚠️ bloqueia com explicação (WSL ≥ 2.0 / Win11 necessário para cgroup v2 + systemd nos nós kind) | — |

### 3.2 Pré-requisitos auditados (em ordem)

1. `bash ≥ 4` (o próprio script), TTY/`tput` (degrada p/ sem cor — §5)
2. **kubectl** (binário do host — `cluster.py` do app chama `kubectl` diretamente; vale para TODO S.O.)
3. **Multipass** — provider `multipass` (macOS/Ubuntu/Debian; `snap` no Linux)
4. **uv** — instalador oficial `curl ... | sh` (nunca apt/brew velho)
5. **Python ≥ 3.12** (via uv se ausente — uv gerencia o runtime do projeto)
6. `jq` (scripts de cluster) · `ssh`/`ssh-keygen` (openssh-clients; só provider multipass)
7. Recursos: ≥ 16 GB RAM (warn < 8 GB bloqueia; 8–16 warn), ≥ 30 GB disco, virtualização habilitada (Linux: checa `/dev/kvm`)
8. Rede bridge: detecta interface default + subnet → valida ≥ 3 IPs livres (aviso, não bloqueia) — só provider `multipass`

**Branch WSL2 (provider `kind`)** — substitui itens 3/6/7/8:

9. systemd ativo no WSL (`ps -p 1 -o comm=` → `systemd`) e cgroup v2 (`stat -fc %T /sys/fs/cgroup` → `cgroup2fs`) — sem isso, bloqueia com instrução de upgrade (Win11 / WSL ≥ 2.0)
10. **Docker Engine** nativo do WSL (instalável via apt com confirmação — **não** exige Docker Desktop)
11. **kind** (binário único, download do release oficial com confirmação) + `jq`
12. Recursos: mesmos limites de RAM/disco (sem `/dev/kvm` — kind não precisa)

Comportamento exigido pelo dono: **falta algo → lista nomeado** (`[MISSING] multipass — required to run the lab VMs`)
e pede confirmação **por item** (`Install multipass via Homebrew? [y/N]`); `--yes` instala tudo; recusa → aborta
com o comando manual que a pessoa pode rodar depois (o script nunca instala sem consentimento explícito).

---

## 4. Fluxo do `setup.sh` (9 steps, todos em inglês)

```text
CKA ARENA — setup                                  # banner ASCII + versão do repo
[1/9] Detecting environment          macOS 15 · arm64 · provider=multipass
                                     Ubuntu 24.04 · x86_64 · provider=multipass
                                     WSL2 · Win11 · provider=kind            (✓ verde)
[2/9] Checking prerequisites         all found                      (ou lista + confirm)
[3/9] Installing Python deps         uv sync                        (spinner: resolving/installing)
[4/9] Launching nodes                multipass: 3 VMs (barra/VM)    ou kind: 3 containers
[5/9] Bootstrapping Kubernetes       kubeadm+join+weave             ou kind config + weave CNI
[6/9] Wiring access                  multipass: SSH bridge+kubeconfig · kind: kubeconfig+nodes.json
[7/9] Installing addons              metrics-server · Gateway API/Envoy · local-path
[8/9] Seeding question bank          17 published
[9/9] Starting server                http://127.0.0.1:8765  (smoke: /api/health 200)
```

Regras: step longo = spinner com frame + mensagem do sub-passo corrente (não só "wait…");
erro = últimos ~20 linhas do log na tela + caminho completo do log; `Ctrl-C` limpa spinner via `trap`;
cada step pode ser re-rodado isolado (`./setup.sh --step addons`).

### Banner final (exato, em inglês, colorido)

```text
───────────────────────────────────────────────────────────────
 ✔ CKA Arena is ready

 ▸ Open:            http://127.0.0.1:8765
 ▸ Terminal:        real shell on this machine (auto-opened tab "mac")

 Configure (all optional):
 ▸ AI generation  — drop a provider key into  llm_config.json
                    (see llm_config.example.json; Practice works without it)
 ▸ Lab password   — VMs use user "ubuntu" / password "ubuntu"
                    (override with CKA_LAB_PASSWORD before re-running setup)
 ▸ Power          — stop/start the cluster from the header pill; the app
                    auto-starts it on launch

 Logs: ~/.cka-arena/setup.log · data: ./data/ · state: ~/.cka-arena/
───────────────────────────────────────────────────────────────
```

---

## 5. UX do terminal — "loads dinâmicos e coloridos" (`lib/ui.sh`)

- **Cores**: paleta ANSI fixa (green ✓ / yellow ! / red ✗ / cyan info / bold títulos);
  `NO_COLOR`, pipe (`[ -t 1 ]` false) e `TERM=dumb` → modo plain com prefixos `[ok]/[warn]/[err]`.
- **Spinner**: frames braille `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` a 80 ms em thread via `&` + `wait $pid` +
  `trap cleanup INT TERM`; suporta mensagem mutável (`spinner_set "joining node02…"`).
- **Progresso de nó**: multipass → barra por VM via `multipass info` (Running/cloud-init);
  kind → barra por container via `docker inspect` (health/running) — nunca sleep cego.
- **Confirm**: `y/N` default seguro; timeout 30 s → N; `--yes` pula.
- Step counter `[n/9]` alinhado; largura 72 colunas (detectada, clamp 60–100).
- Tudo vai também para `~/.cka-arena/setup.log` (sem códigos de cor).

---

## 6. Mudanças no repositório para publicar no GitHub

1. **`llm_client.py`**: configuração apenas local — `llm_config.json` → `CKA_LLM_CONFIG` → env `CKA_LLM_*`,
   com edição pela UI (Settings → AI provider). Criar `llm_config.example.json`.
2. **`.gitignore`**: já cobre `data/`; adicionar `llm_config.json`, `*.db*`, `design/` manter, `.venv`.
3. **README**: novo top section **Quickstart (EN, ~15 linhas)** — prereqs, `./setup.sh`, URL;
   o conteúdo PT-BR atual desce para "Documentation (pt-BR)"; decisión de idioma dos docs
   internos: permanecem PT-BR (decisão histórica do produto), quickstart e script em EN.
4. **LICENSE** MIT + `NOTICE` creditando `certified-kubernetes-administrator-course`
   (origem dos scripts de cluster vendados).
5. **CI (GitHub Actions)**: `shellcheck scripts/`, `bash -n setup.sh`, `uv run pytest`,
   `python -m app.seed validate` (gates sem cluster — probe fica out do CI).
6. **Segredos**: auditoria final `git log -p` antes do push (histórico nasceu local —
   considerar `git init` limpo + squash, sem histórico pessoal).

---

## 7. Decisões assumidas (confirmáveis pelo dono)

| # | Decisão | Alternativa descartada |
| :--- | :--- | :--- |
| D1 | P1 = macOS + Ubuntu/Debian; Fedora/Arch avisados; **WSL2 suportado via kind** (D7) | suportar tudo de graça (custo de QA) |
| D2 | Instalação de prereqs **sempre** com confirmação item-a-item (`--yes` pula) | auto-instalar silencioso |
| D3 | Provider `multipass` continua **BRIDGE** (requisito do runtime: IPs locais p/ SSH) | NAT/port-forward (quebraria ssh bridge) |
| D4 | LLM key é **opcional** no setup (Studio desabilitado sem ela, Practice 100%) | exigir key (travaria onboarding) |
| D5 | Addons dentro do app (`app/addons.py`) reusando `cluster.py` — mesmo caminho do doctor | shell puro (duplicaria kubectl/ssh bridge) |
| D6 | Repo público com docs internos PT-BR + quickstart/script EN | traduzir tudo (escopo explode) |
| D7 | **WSL2 = provider `kind`** (Docker Engine no WSL, weave CNI, sem VM aninhada); `app/provider/` com pass-through 1:1 para Multipass (zero regressão macOS) | Multipass dentro do WSL (`/dev/kvm` não confiável) ou Multipass no Windows (Hyper-V Win Pro + bridge não suportada) |
| D8 | Nomes **lógicos** `controlplane/node01/node02` em toda a plataforma; provider traduz via `~/.cka-arena/nodes.json` | renomear nós kind (não suportado pelo kind) |
| D9 | Transporte de nó por provider: `ssh` (multipass) × `docker exec` (kind, inclusive abas de terminal de nó); L2-clean no kind = recriar cluster (~90 s) | emular SSH no kind (complexidade sem ganho) |

---

## 8. Plano de verificação (aceite)

1. `shellcheck setup.sh scripts/**/*.sh` limpo; `bash -n` ok.
2. `./setup.sh --check` em máquina com tudo → exit 0, lista verde; removendo `multipass`
   do PATH → lista `[MISSING] multipass` e **não** instala sem confirmação.
3. **Run real macOS (destrutivo-controlado)**: `multipass delete --purge` das 3 VMs →
   `./setup.sh` → banner final → `curl /api/health` 200 → practice de 1 questão PASS.
4. **Idempotência**: segunda execução → todos os steps `already done ✓` em < 10 s.
5. **Ubuntu 24.04 VM** (manual na primeira leva): mesmo roteiro 3–4.
6. **WSL2 (Win11 + systemd)**: `./setup.sh` com provider kind → banner final →
   practice com 1 questão de **NetworkPolicy** (prova que a weave/NPC funciona no kind)
   + aba de terminal de nó via `docker exec` + L2-clean (recriação) executa até o fim.
7. **Regressão provider no macOS**: refator `app/provider/` é pass-through — suíte
   completa (64+ testes) verde + fluxo power/terminal/check idêntico ao de hoje
   (evidência: run 3 na mesma máquina).
8. `NO_COLOR=1 ./setup.sh --check` e `./setup.sh --check | cat` → saída plain legível.
9. Suíte existente 64 testes continua verde (addons.py e provider/kind ganham os deles).

## 9. Ordem de implementação (quando aprovado)

- **Fase A** — `lib/ui.sh` + `lib/detect.sh` + `setup.sh --check` (feedback imediato, sem risco)
- **Fase B1** — refator `app/provider/` com **multipass pass-through 1:1** (seam primeiro,
  sem mudar comportamento; suíte verde = zero regressão antes de existir o kind)
- **Fase B2** — `provider/kind.py` + `scripts/cluster/kind-up.sh` (weave + nodes.json);
  validado no WSL2 antes de virar default daquele ambiente
- **Fase C** — vendor + generalização `scripts/cluster/up.sh` (multipass Linux) + `app/addons.py`
  + steps 6–9 + banner final
- **Fase D** — OSS: README/LICENSE/CI/limpeza de defaults pessoais + verificação completa (§8)


---

## 10. Status de implementação (18/11/2026) — evidências

| Fase | Entregue | Verificação |
| :--- | :--- | :--- |
| A — Shell libs | `scripts/lib/{ui,detect,pkg,state}.sh` + `setup.sh` (flags, 9 steps, `--check`, `--step`, spinner/cores/trap) | `./setup.sh --check` exit 0 nesta máquina; `PATH=/usr/bin:/bin ./setup.sh --check` lista `[MISSING] kubectl` e exit 1 **sem instalar**; `shellcheck -S warning` limpo; `bash -n` em tudo |
| B1 — Provider seam | `app/provider/{base,multipass,kind}.py`; engine/pipeline/validator/doctor/power/terminal roteados via `provider.get()` (nenhum `ssh_runner` direto nos checks) | 76 testes verdes (12 novos: `tests/test_provider.py` + `tests/test_commands.py`); `provider.get().nodes()` real → 3 VMs Running com IPs da bridge |
| B2 — WSL/kind | `scripts/cluster/kind-up.sh` (3 nós, weave→Calico fallback, kubeconfig `cka`, `nodes.json`); `KindProvider` (docker exec, power start/stop, terminal `docker exec -it`) | `CKA_PROVIDER=kind` → `power.detect()` degrada graciosamente sem Docker (sem crash); mapeamento/testes unitários do provider |
| C — Cluster/addons | `scripts/cluster/up.sh` (Multipass generalizado: bridge por S.O., cloud-init kubeadm, join, weave); `app/setup_wire.py`; `app/addons.py` idempotente | `python -m app.setup_wire` real: 3 nós ready, `~/.ssh/config` atualizado; `python -m app.addons` real: metrics-server/gateway/envoy/local-path "already present"; `./setup.sh --step addons` no-op idempotente |
| D — OSS | README Quickstart EN (tabela de S.O. incl. WSL2), `LICENSE` MIT, `NOTICE`, `llm_config.example.json`, **AI provider configurável no frontend (Settings → AI provider: presets, modelos por dropdown, chave mascarada, test de conexão)**, `/api/health`, CI (pytest + shellcheck), `seed validate --gates-only` | 76 testes; `seed validate --gates-only` 17/17 GATES OK; `./setup.sh --step server` detecta servidor vivo; `/api/health` → `{"ok":true}` |

**Pendências conhecidas (fora desta entrega):** primeiro run real do `kind-up.sh` em Windows 11/WSL2 e do `up.sh` em Ubuntu limpo (as máquinas de teste atuais são macOS com Multipass já provisionado — os caminhos foram validados por unidade/idempotência, não por provisionamento do zero nessas duas plataformas).
