# Plano de Análise Arquitetural e Melhorias Profundas — CKA Arena

> **Data da auditoria:** 2026-11-21 · **Escopo:** Auditoria completa do código (`app/`, `static/`, `scenarios/seed/`, `tests/` — 8.630 linhas de código, 106 testes `pytest` verdes), configuração (`llm_config.json`) e evidências forenses do banco real (`data/cka_arena.db`: 135 questões, 40 jobs de geração, 618 chamadas LLM, 9 sessões, 36 check runs).
> **Objetivo:** Transformar o **CKA Arena** numa plataforma local de treino CKA rápida, confiável e pedagogicamente fiel ao exame real (CNCF 2025/2026 / Killer.sh), atacando na raiz os 3 sintomas críticos relatados — **lentidão na geração**, **baixa qualidade/construção sem sentido das questões** e **alta taxa de quarentena** — além dos débitos estruturais do restante da arquitetura.

---

## Sumário Executivo: Diagnóstico Quantitativo vs. Metas

| Indicador | Real Medido (`data/cka_arena.db` / código) | Causa Raiz Principal | Meta Alvo (Pós-Melhorias) |
| :--- | :--- | :--- | :--- |
| **Taxa de quarentena (LLM)** | **60,2%** (71 `draft` vs. 47 `published` em 118 registros LLM; `boss_fight` atinge **76,9%**: 40 `draft` vs. 12 `published`) | Retries sem histórico `assistant`, digest pós-cleanup vazio, `len_gte` quebrado, erros de schema classificados como `infra`, LIST-mode sem `.items[*]`, gravação de `draft` em falhas intermediárias | **< 10%** em `exam_standard` e `killer_hardcore`; **< 15%** em `boss_fight` |
| **Tempo de geração por lote** | **~29 min (1.734,6s)** no último `exam_standard × 5` (`gen-989c40274b`, publicando apenas 3/5); 16–30 min em lotes recentes | **> 95% do tempo gasto no cluster**, não na LLM: `_probe_lock` serializado, `settle()` bloqueando 45s em pods intencionalmente `Pending`, `ephemeral_probe` em pod novo por check/poll + mismatch de timeout 25s × 60s, `_repair(deep=True)` cego | **20–45s por questão** (~2–3 min por lote de 5 questões) |
| **Distribuição LLM `exam_standard`** | **12** Services & Networking · **1** Troubleshooting · **1** Workloads · **0** Storage · **0** Cluster Architecture | Viés extremo do prompt (`SOLVABLE PATTERN` único em S&N), `setup.commands`/`solution.node_commands` omitidos no contrato JSON e ausência de planejamento curricular | **Cobertura balanceada 5×3** nos 5 domínios CNCF e 35–40 arquétipos do currículo 2025/2026 |
| **Qualidade narrativa (`killer`/`boss`)** | **6/9 (67%)** das questões do Composer caíram no fallback robótico `"Repair N cluster faults (...)"` + 4 clones de NetworkPolicy no caminho autoral | Bug determinístico em `_narrate()` (exige namespaces de unidades `node_scoped` no texto), Composer colando 3–5 falhas desconexas em namespaces separados e vazando a causa raiz no nome do namespace/sintoma | **100% formato killer.sh/CKA**, 0 spoilers, 0 clones, incidentes com cadeia causal real |
| **Latência do `Check` do usuário** | Até **60s** de espera quando o cenário possui Pod intencionalmente `Pending` | `SessionService.check()` chama `run_checks(settle=True)` e `settle()` trata qualquer pod `Pending` como "instável" | **< 3s** (detecção imediata de estado terminal `Unschedulable`/`ImagePullBackOff`/`CrashLoopBackOff`) |
| **Telemetria do banco (`bank_questions`)** | `times_used=0`, `last_used_at=NULL`, `first_try_pass_count=0`, `avg_solve_seconds=NULL`, `sessions.total_weight=0` em **100%** dos registros | `sessions.py` nunca atualiza estatísticas de uso/acerto em `bank_questions` e `bank.draw_exam_sample()` não retorna `weight_pct` | **100% instrumentada** alimentando sorteio anti-repetição e calibração de tempo |

---

## 1. Diagnóstico Forense: Raiz dos 3 Sintomas Reportados

### 1.1 Por que a geração demora 15–30 minutos (o gargalo não está onde parece)

A análise temporal linha a linha de `llm_generations` e `bank_questions` no último job `exam_standard × 5` (`gen-989c40274b`, usando `deepseek-flash` com `thinking` desligado no fast path) prova onde o tempo é gasto:

- As **3 chamadas iniciais paralelas de LLM-B** terminaram em **+5.7s, +6.0s e +6.1s**.
- As **3 chamadas do Revisor (LLM-C)** terminaram em **+0.8s** (`+6.5s`, `+6.7s`, `+7.0s`).
- Entretanto, os 3 primeiros slots só terminaram o Solvability Probe em **+221.9s**, **+331.8s** e **+437.0s** — e o job completo levou **1.734,6s (~28,9 minutos)** para publicar 3 de 5 questões.

Os **6 multiplicadores reais de latência** no código atual são:

1. **`ScenarioEngine.settle()` cego para falhas intencionais (`app/scenario_engine.py:122-139`):**
   `settle()` considera instável qualquer pod com `phase in ("Pending", "Unknown")`. Em qualquer cenário de Scheduling, `nodeSelector`, `Taints/Tolerations`, `ResourceQuota`/`cpu` ou `PVC` pendente, o pod fica `Pending` **por design**. O `_probe_locked` (`app/pipeline.py:1225`) paga **45s inteiros** travado no `settle()` antes mesmo de rodar o sanity check (e na prática do usuário, `SessionService.check()` usa `settle=True` com teto de **60s**).
2. **`self._probe_lock` serializa 100% dos probes (`app/pipeline.py:306,1197`):**
   Embora até 3 Construtores rodem em paralelo (`asyncio.Semaphore(3)` na linha 414), todos ficam enfileirados em um único lock global de probe — mesmo quando criam recursos isolados em namespaces distintos.
3. **Efeito cascata no `ephemeral_probe` (`app/validator.py:33-38,149-180` × `app/pipeline.py:882`):**
   - Cada check HTTP com `ephemeral_probe: true` cria um Pod `curlimages/curl:8.10.1` (`kubectl run`), faz polling de 1.5s até `Succeeded`/`Failed`, busca logs e deleta o pod — repetido em cada rodada de poll do sanity e da verificação da solução.
   - Além disso, há uma **inversão de timeouts**: `_probe_run(..., timeout=60)` (`validator.py:149`) roda dentro de `run_check()`, cujo `TIMEOUTS["pod_exec_exit_zero"]` é **25s** (`validator.py:34`). Se o pull/start/exec do pod efêmero passar de 25s, `asyncio.wait_for` dispara `TimeoutError`, que vira `status="ERROR"`, força **3 tentativas do check (até 75s)**, marca a rodada como `infra_error=True`, e aciona `_probe_retry` (`pipeline.py:882`), que re-executa o probe completo até **3 vezes adicionais** (backoff `3s + 6s + 9s`).
4. **Dupla confirmação integral no probe (`app/pipeline.py:1285`):**
   Após aplicar a solução, `_probe_locked` exige `consecutive_full >= 2` rodadas completas `all_passed`, re-executando todos os checks (inclusive subindo novos pods efêmeros `curl`) mesmo para verificações puramente declarativas da API.
5. **`_repair()` trava em `deep=True` sem diagnóstico vivo (`app/pipeline.py:1396`):**
   Todo reparo força `deep=True` (modo reasoning do modelo, 10× mais lento), não grava registro em `llm_generations` (ponto cego total de latência/custo) e, como veremos na seção 1.3, recebe `live_namespace_state` vazio.
6. **Colisão de namespaces genéricos e `Terminating` (`app/scenario_engine.py:60-89,203` × `app/pipeline.py:1023-1028`):**
   A LLM frequentemente reutiliza nomes fixos (`web`, `shop`, `sched-fix`, `cka-netpol`). Como `cleanup()` usa `kubectl delete namespace ... --wait=false`, a tentativa seguinte (ou dry-run no mesmo namespace) cai em `Terminating` e paga loops de espera de 24–40s até forçar a finalização.

---

### 1.2 Por que as questões vêm com construção pífia e sem sentido

O problema de qualidade decorre de **duas arquiteturas com defeitos distintos**: o **Composer v5** (usado para `killer_hardcore` e `boss_fight`) e o **Construtor LLM autoral** (usado para `exam_standard` e como fallback das tiers duras).

#### A. O fracasso pedagógico do Composer v5 (`app/composer.py` + `app/fault_units.py`)

O Composer foi introduzido para reduzir a quarentena das tiers difíceis, mas sacrificou a coerência técnica e didática das questões:

1. **Questões "Frankenstein" sem nexo causal:**
   `composer.compose()` sorteia 3 (`killer_hardcore`) ou 5 (`boss_fight`) unidades independentes de `fault_units.py` e as concatena no mesmo enunciado, cada uma em seu próprio namespace (`cka-b-*`), quase todas usando um Deployment chamado `web` e um Service chamado `web-svc`.
   - *Exemplo real publicado no banco (`q-60f4e53465ec`, `boss_fight`):* coloca na mesma questão (1) criar uma `HTTPRoute` em `cka-b-gateway-route-sr77`, (2) corrigir `CrashLoopBackOff` de `web` em `cka-b-crashloop-cmd-vv7w`, (3) corrigir `ImagePullBackOff` de `web` em `cka-b-image-pull-osup`, (4) fazer upgrade de um chart Helm em `cka-b-helm-upgrade-24hv` e (5) iniciar o `kubelet` em `node01`. Não há nenhuma arquitetura de aplicação ou relação de causa e efeito — são 5 mini-exercícios desconexos colados juntos.
2. **Vazamento explícito de causa raiz (Spoilers) violando o formato CKA:**
   - Os namespaces gerados contêm o nome da falha no próprio identificador: `cka-b-crashloop-cmd-vv7w`, `cka-k-pod-wrong-clai-6u87`, `cka-b-svc-selector-iisj`, `cka-b-cpu-request-v0a0`.
   - Os textos de `symptom` em `fault_units.py` entregam o diagnóstico pronto ao candidato (ex.: *"because its container command exits immediately"*, *"because its image tag does not exist"*, *"its selector does not match the Pods"*, *"its kubelet service is not running"*), violando diretamente a regra do `LLM_SCENARIO_SPEC.md` §1.2 (*"sintomas observáveis — NUNCA a causa nem a solução"*).
   - Tarefas genéricas (*"Fix the workload..."*, *"Repair the Deployment..."*) sem referenciar o namespace quando múltiplos `web` existem no mesmo enunciado.
3. **Bug determinístico de `_narrate()` (`app/pipeline.py:796-797` × `app/composer.py:100-103`):**
   - `composer.py:101-103` cria uma entrada em `ns_map` para **toda** unidade sorteada — inclusive unidades `node_scoped` sem namespace (`kubelet-down` e `etcd-snapshot`).
   - Em `pipeline.py:796-797`, `_narrate()` valida a resposta do LLM Narrator exigindo:
     ```python
     for ns in meta["namespaces"].values():
         valid = valid and ns in prompt
     ```
   - Como um namespace inventado tipo `cka-b-kubelet-down-xxxx` nunca é citado no enunciado nem existe no setup, **essa validação retorna `False` em 100% das questões `boss_fight` com nó e em ~50% das `killer_hardcore`**. Resultado: a chamada ao LLM Narrator é descartada (e nem logada em `llm_generations`), caindo no fallback mecânico `"Repair 5 cluster faults (Troubleshooting)"` — verificado em **6 de 9 (67%)** questões publicadas pelo Composer.
4. **Bugs estruturais internos em `composer.py` e `fault_units.py`:**
   - `CHECK_LIMIT = {"boss_fight": 11, "killer_hardcore": 6}` (`composer.py:21,51`) é declarado e lido em `select_units()`, mas **nunca aplicado** (o banco possui questões `boss_fight` do Composer com 12 checks e `killer_hardcore` com 7 checks).
   - **Ignora filtros do usuário:** `composer.compose()` e `select_units()` não recebem `domains`, `subtopics` nem `constraints` (`focus_hint`) do pedido — se o usuário pedir apenas `Storage`, o Composer sorteia `Gateway`, `Helm` e `kubelet`.
   - **Colisão de recurso cluster-scoped:** tanto `pv-claimref` (`fault_units.py:287`) quanto `pod-wrong-claim` (`fault_units.py:324`) criam um `PersistentVolume` cluster-scoped com exatamente o mesmo nome `pv-data`! Se sorteados juntos, o segundo sobrescreve o primeiro e o cleanup de um deleta o PV do outro.
   - **Interferência cruzada com `kubelet-down`:** parar `kubelet` em `node01` afeta pods de outras unidades workload do mesmo cenário que o scheduler tenha colocado em `node01`; `_merge_solution` roda `node_commands` por último, mas se o pod não estiver pronto ou o check rodar antes da recuperação do nó, a composição falha.
   - **`etcd-snapshot` inválido para `boss_fight`:** `setup.node_commands` é vazio (`[]`), de modo que o gate `_tier_band_errors` rejeita se cair sem outra unidade com `node_commands` de setup.
   - **`docs_links` sempre `[]`:** `composer.py:175` não preenche links para a documentação oficial permitida na prova.

#### B. Defeitos de qualidade no caminho autoral LLM (`app/pipeline.py:_build_one`)

Quando a geração vai pelo caminho autoral LLM (`exam_standard` e fallback de `killer`/`boss`), surgem 4 problemas estruturais:

1. **Viés extremo por few-shot único (colapso de diversidade):**
   - `BUILDER_SYSTEM` (`pipeline.py:179-186`) tem apenas um `SOLVABLE PATTERN` explícito: Deployment `web` + Service `web-svc` em `Services & Networking`. Resultado observado no banco: das 14 questões `exam_standard` publicadas por LLM, **12 são de `Services & Networking`**, 1 de Troubleshooting, 1 de Workloads, **0 de Storage** e **0 de Cluster Architecture**.
   - `HARD_TIER_ADDENDUM` (`pipeline.py:242-244`) injeta um único exemplar fixo (`sn-networkpolicy-dns.json`). Resultado observado no banco: **4 clones publicados** com o título exato `"Allow Selected Traffic Through Default Deny"` em `killer_hardcore` de `Services & Networking` (além de dezenas de variações de `web` + `web-svc`).
2. **Contrato de schema incompleto no `BUILDER_SYSTEM` (`pipeline.py:126-129`):**
   - O `OUTPUT CONTRACT` mostrado à LLM define `setup` apenas com `namespaces`, `manifests`, `node_commands` — **omitindo `setup.commands`** (necessário para `helm install` ou `kubectl taint`).
   - Define `solution` apenas com `manifests`, `commands` — **omitindo `solution.node_commands`** (impossibilitando que a LLM gere cenários onde a solução roda no nó, como `systemctl start kubelet` ou `etcdctl snapshot save`).
   - Define `cleanup` com o campo legado `kubectl_commands` em vez de `commands`.
3. **Ausência de coordenação entre slots paralelos e histórico do banco:**
   - `"avoid": "duplicate titles or topics from previous slots"` (`pipeline.py:558`) é apenas texto estático — os 3 slots paralelos não recebem os títulos já existentes no banco nem um arquétipo/domínio atribuído para cada slot. Todos os slots convergem para o tema mais fácil (Service selector / CrashLoop `web`).
4. **Validações de qualidade ausentes no Gate D / Revisor C:**
   - Não há verificação anti-spoiler determinística (vários prompts LLM vazam a solução ou termos de causa raiz antes de `Perform the following tasks:`).
   - Não há validação de `docs_links` (o prompt pede URLs de `kubernetes.io/...`, mas nenhuma verificação checa se existem ou têm domínio válido).

---

### 1.3 Por que questões vão para quarentena com tanta frequência (Taxonomia das 71 Drafts)

A inspeção de todas as **71 questões em estado `draft`** no `data/cka_arena.db` revela exatamente onde o pipeline falha:

| Categoria da Falha (evidência em `probe_result_json`) | Composer | LLM Autoral | Total | Causa Raiz Técnica |
| :--- | :---: | :---: | :---: | :--- |
| **`infra_error` no sanity/final check** | 0 | 17 | **17** | `validator.py` classifica bugs Python de params da LLM (`TypeError`, `KeyError`) como `ERROR`; `settle` curto/timeout de 25s em `ephemeral_probe` |
| **Solução rejeitada no apply (`other` / `BadRequest` / `immutable` / `AlreadyExists` / `taint`)** | 2 | 15 | **17** | `solution.manifests` não passa por `--dry-run=server` no Gate D; LLM tenta `kubectl patch` em campos imutáveis de `PVC`/`Pod`; 2 drafts do Composer falharam por JSON patch inválido em `svc-targetport` (corrigido depois, mas sem gate de JSON `-p`) |
| **`kubectl_jsonpath` retorna vazio (`''`/`None`) ou string errada** | 0 | 11 | **11** | LIST mode com `label_selector` sem `.items[*]` no jsonpath; regex rígido em multi-linhas |
| **Lógica inconsistente entre `setup`/`solution`/`checks`** | 1 | 7 | **8** | **Amnésia de retry** (sem mensagem `assistant` nas iterações) + **digest morto no `_repair()`** + erro de lógica não detectado em gate pré-probe |
| **Exceção no probe (setup/SSH/timeout)** | 0 | 7 | **7** | `setup.commands` falhando (ex.: `helm repo add` de repo inexistente, taint ausente, SSH/comando inválido) |
| **Outros checks falham (`no pods match`, `Pending`, `HTTP stdout=''`, `len_gte`, `Helm missing`)** | 0 | 10 | **10** | Bug real em `len_gte` (`split(",")` sobre saída separada por espaço/newline), `setup` sem `helm install`, Service sem ready endpoints |
| **Total** | **3** | **68** | **71** | **60,2% de todas as questões geradas por LLM no histórico** |

Os **7 bugs concretos de código** que explicam essa taxa de rejeição são:

1. **Bug crítico — Amnésia nos retries de `_build_one` (`app/pipeline.py:612-614, 641-643, 655-657, 697-701`):**
   Quando uma tentativa falha em schema, gates, reviewer ou probe, o loop adiciona `{"role": "user", "content": "Your previous output was invalid: ..."}` à lista `messages`, **mas NUNCA adiciona `{"role": "assistant", "content": text}` antes!** O modelo recebe uma reclamação sobre um JSON que não está no histórico da conversa e precisa gerar tudo às cegas do zero.
2. **Bug crítico — `live_namespace_state` sempre vazio no `_repair()` (`app/pipeline.py:660, 679, 1324-1328, 1380`):**
   O comentário em `pipeline.py:1363` e `LLM_PIPELINE_SPEC.md` promete que `_repair()` recebe o estado vivo dos namespaces (`pods`, `readiness`, `services`, `endpoints`). Porém, `_probe_locked()` executa `await self.engine.cleanup(env)` no bloco `finally` (`linha 1326`) **antes de retornar**. Quando `_build_one()` chama `_repair()` na linha 679 e executa `self.engine.namespace_digest(env.setup.namespaces)` (`linha 1380`), todos os namespaces já foram deletados (`Terminating` ou `NotFound`)! O repair opera cego.
3. **Bug crítico — Erros determinísticos de definição de check viram `infra_error` (`app/validator.py:438-439`):**
   Em `run_check()`, qualquer exceção levantada por `fn(params)` — como `KeyError` (param faltando), `TypeError` (ex.: `expected` incompatível como `chk-iptables-removed` na linha 73 do log de drafts), `ValueError` em `compare()` ou `re.error` em regex malformado — é capturada e transformada em `status = ERROR`. Isso marca `infra_error = True`, queima 3 retries de check + 3 retries de `_probe_retry` (desperdiçando ~2 min) e devolve `"infra"` sem dar chance de reparo ao modelo!
4. **Bug real — `compare(..., "len_gte", ...)` só aceita vírgula (`app/validator.py:66-68`):**
   `kubectl -o jsonpath="{.subsets[*].addresses[*].ip}"` separa múltiplos valores por **espaço** (e `range ... "\n"` por **quebra de linha**), nunca por vírgula. Como `validator.py:67` faz `actual.split(",")`, `"10.40.0.2 10.40.0.3"` vira lista de tamanho `1`, falhando qualquer check com `min >= 2` (evidência real em `q-81441be4fcb1`).
5. **Bug de contrato — `kubectl_jsonpath` em LIST mode (`app/pipeline.py:166-169, 1136-1146`):**
   Ao usar `kind="Pod"` + `label_selector="app=web"` sem `name`, o `kubectl` retorna um `List` com raiz `.items[]`. O prompt não explica que em LIST mode o jsonpath precisa começar em `{.items[*].` ou `{range .items[*]}`; a LLM escreve `{.status.phase}` (que funciona só em objeto único) e recebe string vazia `""` (evidência em `q-f50b83a3fcfc`).
6. **Poluição do banco com drafts intermediários (`app/pipeline.py:663, 670, 856, 867`):**
   O pipeline insere um novo registro `state="draft"` no SQLite **em cada falha intermediária** antes mesmo do loop de repairs/retries terminar. Se uma questão falhar 2 vezes e passar na 3ª, gera 2 drafts mortos + 1 publicada (inflando a tabela para 71 drafts de apenas 40 requests).
7. **Gaps de validação no Gate D (`app/pipeline.py:916-1038`):**
   - `kubectl apply --dry-run=server` roda apenas em `env.setup.manifests` (`linha 1017`), nunca em `env.solution.manifests`.
   - Não valida sintaxe JSON de flags `-p`/`--patch` em `commands` (nem bloqueia patches em campos imutáveis como `PVC.spec.storageClassName`, `PVC.spec.accessModes`, `Pod.spec.volumes`).
   - Não valida a regra documentada em `LLM_PIPELINE_SPEC.md` §5.1 de que `pod_exec_must_fail` precisa de timeout embutido no comando.
   - `_tier_band_errors` (`linha 1187`) só falha se `len(fails) >= 2` e ignora quando `setup.node_commands` está ausente se não cair na condição exata.

---

## 2. Problemas Sistêmicos Além da IA (Auditoria Arquitetural Completa)

A análise de todo o projeto fora do pipeline LLM encontrou **8 débitos arquiteturais críticos/médios** que comprometem o objetivo de ter uma plataforma sólida localmente:

| Área | Evidência no Código / Banco | Impacto Real |
| :--- | :--- | :--- |
| **1. Telemetria de questões completamente desconectada** | `app/sessions.py` nunca atualiza `bank_questions.times_used`, `last_used_at`, `first_try_pass_count` nem `avg_solve_seconds` (todos `0`/`NULL` nas 135 linhas do DB). `bank.draw_exam_sample()` (`app/bank.py:137-139`) não retorna `weight_pct`, fazendo `sessions.total_weight` ser gravado como `0` em todas as 9 sessões. | O sorteio anti-repetição (`ORDER BY times_used`) é nulo; o percentual do simulado (`earned_weight / total_weight`) não funciona; não há detecção de questões quebradas ou mal calibradas em tempo. |
| **2. Zero curadoria / gestão de banco e quarentena** | `app/main.py` expõe apenas `/api/bank/coverage` e `/api/bank/preview`. Não existem endpoints nem UI para listar, filtrar, inspecionar `drafts`, ver `probe_result_json`, re-probar, reparar, aposentar (`retired`) ou excluir questões. | Os 71 `drafts` e os clones duplicados ficam presos no SQLite como "buraco negro"; se uma questão publicada tiver bug no enunciado/check durante a prática, o usuário não tem botão de "Report / Retire". |
| **3. Caminhos de assets quebrados pelo terminal scratch** | `TerminalSession.spawn()` (`app/terminal.py:121,144`) inicia o shell em `~/.cka-arena/scratch/<tab_id>`, mas o seed `scenarios/seed/ca-helm-upgrade.json` instrui usar `scenarios/seed/assets/helm-chart` (caminho relativo à raiz do repo). Nos `check_runs` reais do DB, há 2 falhas consecutivas nesse seed. | O usuário no terminal integrado não encontra o chart Helm nem overlays Kustomize sem navegar manualmente para fora da sandbox do scratch. |
| **4. Modo `mock_exam` e flag `destructive` incompletos** | `app/sessions.py:95` grava `mode = "study"` hardcoded; `sessions.get()` não expõe `ssh_target` nem `destructive`; `static/js/workspace.js:98` hardcoda `ssh cka-node01` e esconde questões `destructive` sem fluxo específico. Além disso, o último relatório de `Check` some ao recarregar a página (F5). | Impossível fazer simulado completo cronometrado (120 min, navegação livre entre questões, Flag for Review, score ≥ 66%), e cenários de `etcd restore` / `kubeadm upgrade` continuam sem fluxo seguro de L2. |
| **5. Botão `Check` ausente na barra do terminal** | `README.md`, `PLAN.md` e `GAP_ANALYSIS.md` prometem um botão `Check` direto na barra de rodapé do terminal. Em `static/index.html:80-94`, o footer do terminal só tem `+ Shell`, `term-workdir`, `Native` e `Clear`. | Menor ergonomia durante o uso exclusivo do painel direito (embora `⌘↵` funcione globalmente). |
| **6. Concorrência sem governança de Cluster Lease** | `app/main.py:43-44` instancia dois `ScenarioEngine()` distintos (`pipeline` e `sessions`). Não há lock/lease impedindo rodar geração com IA ao mesmo tempo que uma sessão de prática ativa, `reset-baseline` ou `power stop`. Também não há endpoint `POST /api/generate/cancel`, deixando 4 `generation_requests` presos como `running` no DB. | Risco real de uma geração alterar nós (`kubelet` stop, taints) ou consumir recursos durante uma sessão de prova do usuário, além de jobs zumbis pós-restart. |
| **7. `teardown.py` acoplado a SSH + gargalo no `MultipassProvider`** | `app/teardown.py` chama `ssh_runner.sudo_run(ip, ...)` diretamente em vez de usar `provider.get().exec(..., sudo=True)`, quebrando L1/L2/drift no driver `kind` (WSL2). `MultipassProvider.exec()` (`app/provider/multipass.py:34`) chama `self.nodes()` (subindo `multipass list` + TCP probes em 3 VMs) a **cada comando SSH**, sem cache TTL nem `ControlMaster`. | `teardown` incompatível com WSL2/kind; overhead evitável de centenas de ms por comando de nó; `reset_clean` só limpa um taint hardcoded (`cka-arena/practice=critical:NoSchedule-`). |
| **8. `llm_client.py` + higiene de projeto** | `save_config()` (`app/llm_client.py:279-288`) descarta `thinking` e `reasoning_effort` do JSON salvo; sem preset para **Ollama** local (apesar de citado no `PLAN.md`) nem input livre de modelo; `httpx.AsyncClient` recriado por requisição; `data/arena.db` (0 bytes) e YAMLs soltos na raiz (`deploy.yaml`, `role.yaml`, `rolebinding.yaml`); tabelas mortas `terminal_sessions`/`command_audit` (0 linhas); teste inativo em `tests/test_composer.py:89` (`if False`); mensagens em PT-BR vazando de `validator.py` para a UI 100% inglês. | Impossível controlar `thinking` ou usar Ollama pela UI; acúmulo de artefatos mortos e inconsistência de idioma nas evidências de erro. |

---

## 3. Arquitetura Alvo Proposta (Geração v2 + Plataforma Governada)

Para resolver os três problemas de raiz, o pipeline sai do modelo *"prompt genérico + colagem de fragmentos desconexos"* para uma arquitetura **Blueprint-Guided + Incidentes Causais Coesos + Cluster Lease**:

```mermaid
flowchart TD
    UI["Scenario Studio\n(domínios · dificuldade · qtd · foco)"] --> LEASE{"Cluster Lease\n(livre de sessão/reset?)"}
    LEASE -->|ocupado| REJECT["409 Conflict claro na UI"]
    LEASE -->|livre| A["Estágio A · Normalizador + Slot Planner\n• Lê grade 5×3 e últimos 30 títulos do DB\n• Sorteia arquétipo CNCF distinto por slot\n• Atribui namespace neutro + exemplar few-shot"]

    A --> STRAT{"Estratégia por Tier"}
    STRAT -->|exam_standard / killer_hardcore| B1["Estágio B · Construtor Blueprint-Guided\n(histórico assistant preservado nos retries)"]
    STRAT -->|boss_fight| B2["Estágio B · Causal Incident Engine\n(incidentes multi-camada coesos no mesmo app)"]

    B1 --> D["Estágio D1/D2 · Gates Determinísticos (0 LLM)\n• YAML + JSON -p + imutabilidade + anti-spoiler\n• LIST-mode .items[*] + must_fail timeout + docs_links\n• dry-run=server em setup E solution"]
    B2 --> D

    D -->|erro estrutural| B_FIX["Retry direcionado (fast)"]
    B_FIX --> D
    D -->|ok| C["Estágio C · Revisor Frio (flash)\n• Rubrica semântica + anti-spoiler + exam voice"]
    C -->|patch (≤1x)| B_FIX
    C -->|approve| E

    E["Estágio E · Solvability Probe v2\n• Namespace efêmero cka-prove-<slot> (paralelo ≤2 ns-scoped)\n• Smart Settle event-driven (TerminalFault sai em 2-4s)\n• Warm Probe Pod (cka-arena-system) quando sem NetPol\n• Captura Live Digest (pods/events/logs/svc/pvc) PRÉ-cleanup"]

    E -->|falha infra real| RETRY_INFRA["Retry de infra (sem queimar orçamento)"]
    E -->|falha conteúdo| REPAIR["Repair Cirúrgico (1º fast → 2º deep)\ncom Live Digest real + matriz completa"]
    REPAIR --> D
    E -->|100% PASS| PUB[("bank_questions\nstate: published")]
    REPAIR -->|orçamento esgotado| DRAFT[("bank_questions\nstate: draft + histórico\n(1 registro final por slot)")]
```

### 5 Princípios da Nova Arquitetura

1. **Planejamento Curricular Explícito (Slot Planner antes do Builder):** nunca pedir à LLM para "inventar qualquer questão". Cada slot nasce com domínio, arquétipo do currículo CNCF 2025/2026, pitfalls específicos do tópico, namespace corporativo neutro e lista `avoid_recent` real do banco.
2. **Coesão sobre Colagem (fim do Frankenstein Composer):** questões `killer_hardcore` e `boss_fight` devem representar um único sistema/incidente realista em 1–2 namespaces de negócio, com dependências reais entre as tarefas (ex.: `kubelet` → `PVC/Pod` → `Service` → `NetworkPolicy/HTTPRoute`).
3. **Falhar Rápido e Barato Antes do Cluster:** `Gates D1/D2` (incluindo `dry-run=server` da solução) executam **antes** do `Reviewer C` e do `Probe E`. Erros sintáticos/semânticos nunca chegam a tocar as VMs nem pagam chamada de Reviewer.
4. **Memória Completa + Observabilidade Viva:** retries mantêm a resposta `assistant` no contexto; o `_repair()` recebe `events`, `logs`, `Pod conditions` e `Endpoints` capturados **antes** do `cleanup()`.
5. **Cluster como Recurso Compartilhado Governado:** isolamento por namespace efêmero no probe, Smart Settle orientado a eventos do Pod, Warm Probe Pod compartilhado e `ClusterLease` unificando sessão, geração e reset.

---

## 4. Plano Detalhado de Melhorias em 6 Frentes (P0 → P2)

### Frente 1 (P0) — Correção de Bugs Críticos do Pipeline & Quarentena Imediata
**Objetivo:** Estancar imediatamente os bugs determinísticos que causam quarentena em massa, amnésia de reparo e desperdício de tempo.

- **Mudanças Técnicas:**
  1. **Preservar histórico `assistant` em `app/pipeline.py:_build_one`:**
     Antes de cada `messages.append({"role": "user", ...})` nas linhas 612, 641, 655 e 697, anexar `{"role": "assistant", "content": text}` (compactando apenas rodadas antigas caso ultrapasse o limite de janela, mantendo sempre o último envelope completo).
  2. **Captura de `live_digest` pré-cleanup (`app/pipeline.py:_probe_locked` e `app/scenario_engine.py:namespace_digest`):**
     - Capturar `digest = await self.engine.namespace_digest(env.setup.namespaces)` **dentro de `_probe_locked` antes do `finally: cleanup(env)`** sempre que sanity ou final falharem por conteúdo, devolvendo-o junto ao resultado do probe (ou armazenando no relatório da tentativa).
     - Enriquecer `namespace_digest()` com: `events` recentes de Warning (`kubectl get events -n <ns> --field-selector type=Warning`), `conditions` de Pods `Pending` (`Unschedulable` message), últimos 15 lines de `logs` em `CrashLoopBackOff`, e status de `PersistentVolumeClaim` (`phase`, `storageClassName`).
  3. **Correções imediatas em `app/validator.py`:**
     - **Corrigir `len_gte` (`linha 66-68`):** usar `items = [part for part in re.split(r"[\s,]+", actual) if part.strip()]` para aceitar saídas separadas por espaço, quebra de linha ou vírgula do `kubectl jsonpath`.
     - **Separar `INVALID` de `ERROR` (`linha 438-439`):** criar status/classificação clara para erros causados por parâmetros inválidos do check (`KeyError`, `TypeError`, `ValueError`, `re.error`) — tratar como falha de **conteúdo** (`kind="content"`), nunca como `infra_error`, evitando os 3 retries inúteis de check + 3 retries de probe.
     - **Alinhar timeout de `ephemeral_probe`:** elevar `TIMEOUTS["pod_exec_exit_zero"]` / `pod_exec_must_fail` para `45s` quando `ephemeral_probe` for verdadeiro (ou passar a usar o Warm Probe Pod da Frente 3), garantindo que `asyncio.wait_for` no `run_check` não mate o `_probe_run` antes do timeout interno.
     - **Padronizar mensagens em inglês:** traduzir as strings `reason`/`error` em `validator.py` (atualmente em PT-BR, ex.: `"nenhum pod corresponde ao selector"`, `"arquivo não existe"`) para manter a UI 100% em inglês conforme `PRODUCT.md`.
  4. **Completar contrato e regras no `BUILDER_SYSTEM` (`app/pipeline.py:116-189`):**
     - Incluir `commands` em `setup` e `cleanup`, e `node_commands` em `solution` dentro do `OUTPUT CONTRACT` JSON.
     - Documentar explicitamente a sintaxe obrigatória do LIST mode em `kubectl_jsonpath`: quando `name` for vazio e `label_selector` estiver preenchido, o `jsonpath` **deve** iterar sobre `.items[*]` (ex.: `{.items[*].spec.nodeName}`).
     - Proibir explicitamente `kubectl patch` em campos imutáveis de `PVC` (`storageClassName`, `accessModes`, `selector`) e `Pod` (`spec.volumes`, `spec.containers[*].ports` imutáveis via patch simples) — orientar `solution.commands` com delete + `solution.manifests`.
  5. **Reordenar e endurecer os Gates (`app/pipeline.py:_build_one` e `_gates`):**
     - **Ordem nova:** `Schema (Pydantic)` → `Clamp de banda` → **`Gates D1 (estático) + D2 (dry-run server)`** → **`Reviewer C`** → **`Probe E`**. Não gastar chamadas LLM do Revisor em envelopes que já reprovam nos gates determinísticos.
     - Rodar `kubectl apply --dry-run=server -f -` também em `env.solution.manifests` (não só em `setup.manifests`).
     - Validar sintaxe JSON em payloads `-p`/`--patch` de `setup.commands`, `solution.commands` e `cleanup.commands`.
     - Rejeitar `kubectl patch` direcionado a campos imutáveis conhecidos (`pvc` mudando `storageClassName`/`accessModes`, `pod` mudando `volumes`).
     - Validar que `kubectl_jsonpath` em LIST mode (`not name and selector`) contém `items` no `jsonpath`.
     - Validar que `pod_exec_must_fail` inclui flag/comando de timeout (`--max-time`, `-w`, `-W`, `timeout`).
     - Validar `docs_links` não-vazio com URLs sob domínios permitidos (`kubernetes.io`, `helm.sh`, `gateway-api.sigs.k8s.io`).
     - Gate heurístico **Anti-Spoiler**: verificar se a parte narrativa antes de `Perform the following tasks:` contém padrões literais de diagnóstico/correção proibidos (ex.: `"because its selector"`, `"because the command exits"`, `"missing tag"`, `"patch"`, `"remove the"`) e encaminhar ao Reviewer C a checagem explícita desse critério.
  6. **Eliminar poluição de drafts intermediários & corrigir hotfix do `_narrate()`:**
     - Gravar `bank.publish_question(..., state="draft")` **somente uma vez** ao final de `_build_one` / `_compose_one` quando o slot esgotar todas as tentativas (armazenando um resumo estruturado das últimas falhas no `probe_result_json`).
     - No `_narrate()` (`app/pipeline.py:796-797`), validar apenas os namespaces presentes em `setup.namespaces` (nunca namespaces fictícios de unidades `node_scoped`).

- **Impacto Esperado:** Redução imediata da quarentena de ~60% para ~20–25% antes mesmo da troca do motor de geração; eliminação de ~40% das chamadas perdidas de LLM-C e de retries cegos no repair.
- **Critérios de Aceite:** Testes unitários cobrindo `assistant` no histórico, `len_gte` com espaço/newline, `INVALID` sem retry de infra, `live_digest` capturado pré-cleanup e dry-run em `solution.manifests`; lote de 5 `exam_standard` reduzindo quarentena para ≤ 1/5.

---

### Frente 2 (P0) — Nova Arquitetura de Geração com IA: Blueprint-Guided + Incidentes Coesos
**Objetivo:** Acabar com questões Frankenstein, clones repetidos, viés de domínio (12/14 em S&N) e spoilers no enunciado.

- **Mudanças Técnicas:**
  1. **Catálogo Curricular (`app/curriculum.py` — novo):**
     Modelar ~35–40 arquétipos oficiais do currículo CNCF CKA 2025/2026 distribuídos pelos 5 domínios, cada um com:
     - `id`, `domain`, `subtopics`, `allowed_difficulties`
     - `requires_addons` (`gateway`, `metrics-server`, `local-path`, `helm`, `etcdctl`, `network_policy`)
     - `needs_node_ssh`, `destructive`
     - `example_seed_id` (referência a um seed real validado ou template estrutural para few-shot dinâmico)
     - `pitfalls`: orientações técnicas precisas para evitar falhas de LLM naquele tópico (ex.: *Gateway API `Accepted` vs `Programmed=False` sem LoadBalancer*; *Kustomize `kubectl apply -k`*; *Native Sidecar `initContainers` com `restartPolicy: Always`*; *PVC `WaitForFirstConsumer` só faz bind após Pod schedulable*; *NetworkPolicy com Egress exige `kube-system` UDP/TCP 53*).
  2. **Slot Planner Ciente do Banco (`app/planner.py` — novo, integrado ao Estágio A):**
     - Ao receber `GenerateRequest`, lê a matriz 5×3 atual do banco (`bank.coverage()`) e os últimos 30 títulos/arquétipos publicados.
     - Distribui os `N` slots entre os domínios selecionados priorizando células vazias/deficitárias e sorteia um **arquétipo distinto por slot** (filtrando pelos addons disponíveis retornados pelo `ClusterDoctor` e pelas `constraints` do `focus_hint`).
     - Atribui a cada slot um **namespace neutro de negócio** vindo de um pool realista (`checkout`, `billing`, `orders`, `inventory`, `edge-gw`, `auth-core`, `catalog`, `payments`, `telemetry`, `media`), acrescentando sufixo curto aleatório no probe quando necessário. **Proibido** usar nomes de falha no namespace (`crashloop`, `wrong-claim`, `svc-selector`).
     - Injeta `avoid_recent` com títulos reais do banco + títulos planejados nos slots irmãos.
  3. **Few-Shot Dinâmico por Domínio/Tier no Builder (`app/pipeline.py`):**
     Remover o `SOLVABLE PATTERN` fixo de `web-svc` e o `_HARD_EXAMPLE` único de NetworkPolicy do prompt global. Injetar dinamicamente o exemplar seed mais próximo do `archetype` sorteado para aquele slot (ex.: seed Storage para Storage, seed Helm/RBAC/etcd para Cluster Arch, seed Taint/Resources para Workloads).
  4. **Substituir o Frankenstein Composer (`app/composer.py` / `app/fault_units.py`):**
     - **`exam_standard` e `killer_hardcore`:** passam a ser gerados integralmente via **Blueprint-Guided LLM** (arquétipos de complexidade calibrada: 1–2 requisitos em 1 namespace para `exam_standard`; 3–4 requisitos interligados + ≥ 1 armadilha justa em 1–2 namespaces para `killer_hardcore`).
     - **`boss_fight` via Causal Incident Blueprints:** substituir a colagem aleatória de 5 falhas desconexas por **blueprints de incidentes multi-camada coesos** (6–8 arquiteturas onde todas as falhas pertencem ao mesmo sistema/fluxo):
       - *Exemplo A (Node + Workload + Exposure):* `kubelet` parado/configurado errado em `node01` + Deployment com `nodeAffinity`/taint + Service com `targetPort` errado + verificação HTTP de ponta a ponta.
       - *Exemplo B (Control-Plane/Static Pod + Workloads + Rollout):* manifesto estático/CoreDNS ou probe quebrado + Deployment com resource/command inválido + verificação pós-recuperação.
       - *Exemplo C (Storage + RBAC + Gateway/NetworkPolicy):* `PV` com `claimRef`/StorageClass + app que depende do PVC + `NetworkPolicy`/`HTTPRoute` com prova negativa e positiva.
       - A LLM preenche nomes neutros, manifestos, sintomas sem spoiler e referência didática sobre o blueprint causal, e o Solvability Probe prova que o conserto encadeado resolve 100% dos checks.
     - Refatorar `fault_units.py` (removendo spoilers dos nomes/sintomas, resolvendo a colisão do PV `pv-data` e aplicando `CHECK_LIMIT`) para uso exclusivo em modo fallback offline (quando não houver chave LLM) ou testes unitários.
  5. **Repair em 2 velocidades e observabilidade completa (`app/pipeline.py:_repair`):**
     - 1ª tentativa de `_repair()`: rodar em **modo `fast` (`deep=False`)** — com o `live_digest` completo e a matriz de checks, erros mecânicos são corrigidos em ~4–6s em vez de ~60s.
     - 2ª tentativa de `_repair()` (se a 1ª falhar): acionar **`deep=True`** (reasoning).
     - Registrar todas as chamadas de `_repair()` e `_narrate()` na tabela `llm_generations` (com `stage="R"` e `stage="N"`).

- **Impacto Esperado:** Questões diversas nos 5 domínios, fim das questões Frankenstein e dos clones idênticos, zero spoilers nos enunciados e taxa de publicação > 90%.
- **Critérios de Aceite:** Gerar lote misto (`exam_standard` + `killer_hardcore` + `boss_fight`) cobrindo os 5 domínios sem repetição, sem fallback de título `"Repair N cluster faults"`, sem spoilers no texto de sintomas, e com cobertura de tópicos modernos (Gateway API, Helm, NetworkPolicy DNS 53, Native Sidecar, Storage).

---

### Frente 3 (P0/P1) — Aceleração Radical do Prove-Out & Motor de Validação v2
**Objetivo:** Reduzir o tempo de validação de minutos para segundos — tanto no Solvability Probe da geração quanto no clique do botão `Check` durante o estudo.

- **Mudanças Técnicas:**
  1. **Smart Settle orientado a estado terminal (`app/scenario_engine.py:settle`):**
     - Em vez de checar apenas `phase in ("Pending", "Unknown")`, inspecionar `status.conditions` e `status.containerStatuses` / `initContainerStatuses` de cada pod e classificá-lo em:
       - `Ready`: `phase == "Running"` e todos containers `ready=True`.
       - `TerminalFault`: `PodScheduled=False` com `reason == "Unschedulable"` (Scheduling/Taint/CPU/PVC Pending), ou `waiting.reason` em `("ImagePullBackOff", "ErrImagePull", "CrashLoopBackOff", "CreateContainerConfigError", "InvalidImageName", "CreateContainerConfigError")`, ou `terminated.reason == "OOMKilled"`, ou `phase == "Failed"`.
       - `Transitioning`: `ContainerCreating`, `PodInitializing` ou pod recém-criado sem motivo de falha ainda.
     - **Regra de retorno rápido:** quando todos os pods estiverem em `Ready` ou `TerminalFault` (0 pods em `Transitioning`), `settle()` **retorna imediatamente** (tipicamente em **2–4s**, em vez de esperar 45s no sanity ou 60s no `Check` do usuário!).
     - No sanity check pós-setup do probe, manter apenas uma janela curta de confirmação (ex.: 10s se um container ainda estiver baixando imagem ou iniciando pela primeira vez).
  2. **Warm Probe Pod compartilhado (`app/validator.py`):**
     - Criar/manter sob demanda 1 pod leve `cka-probe-runner` (imagem `curlimages/curl:8.10.1` ou `nicolaka/netshoot` / `busybox` com comando `sleep infinity`) em um namespace dedicado `cka-arena-system` (fora dos namespaces de cenário).
     - Quando um check usa `ephemeral_probe: true` e o cenário **não** possui `NetworkPolicy` no namespace alvo (ou o check explicitamente marca `probe_scope: "external"`), executar `kubectl exec` direto no Warm Probe Pod (< 300ms por chamada em vez de 10–25s criando/deletando pod a cada poll).
     - Quando o cenário envolve `NetworkPolicy` restritiva por namespace de origem ou exige execução dentro do namespace da questão, manter um único pod probe reutilizável no namespace durante a execução de `run_all` (ou fallback para `_probe_run` com timeout alinhado de 45s e cleanup garantido mesmo em `asyncio.CancelledError`).
  3. **Namespaces efêmeros + Paralelismo controlado de Probes (`app/pipeline.py`):**
     - Durante o Estágio E, para cenários namespace-scoped, reescrever temporariamente em memória o nome de cada namespace do envelope para `cka-prove-<slot>-<4hex>` antes de aplicar no cluster (sem alterar o envelope que será salvo no banco). Isso elimina 100% das colisões entre slots e esperas por `Terminating`.
     - Substituir o `self._probe_lock` único por um **semáforo de probes namespace-scoped (`Semaphore(2)`) + lock exclusivo apenas para cenários cluster/node-scoped** (`node_commands`, `destructive`, `pv`, `clusterrole`, `taint`, `GatewayClass`).
     - Na verificação pós-solução do probe, eliminar o duplo full-pass (`consecutive_full >= 2`) para checks puramente declarativos (`kubectl_resource_exists`, `kubectl_jsonpath` sobre spec, `kubectl_auth_can_i`, `helm_release_state`), mantendo a reconfirmação apenas para checks de runtime/rede (`pod_exec_*`, `pod_status_ready`, `node_status_ready`).
  4. **Novos Check Types Semânticos (`app/validator.py` + `app/models.py`):**
     Reduzir erros frágeis de `jsonpath` e regex da LLM adicionando 3 check types de alto nível (e novos operadores em `kubectl_jsonpath`):
     - `service_endpoints_ready`: `{namespace, service_name, min_ready_addresses}` — consulta `EndpointSlice` (`discovery.k8s.io/v1` com label `kubernetes.io/service-name`) com fallback para `Endpoints`, evitando bugs de `len_gte` e `jsonpath` em IPs.
     - `deployment_rollout_ready`: `{namespace, name, min_ready_replicas, expected_image?}` — valida geração observada, `readyReplicas` e imagem.
     - `pvc_bound`: `{namespace, name, storage_class?, min_storage?}` — valida `phase == Bound` e propriedades de storage.
     - Novos operadores em `kubectl_jsonpath`: `empty`, `not_empty`, `equals_int`, `not_contains`, `all_match` (verifica se todos os itens de LIST mode satisfazem um valor esperado sem precisar escrever regex `^node01( node01)*$`).
     - Documentar suporte a `kubectl apply -k` (Kustomize) no contrato de `commands.py` e no prompt.

- **Impacto Esperado:** Probe médio cai de ~150–300s para ~15–35s; lote de 5 questões cai de ~29 min para ~2–3 min; `Check` na prática responde em < 3s mesmo em cenários com pods `Pending`.
- **Critérios de Aceite:** Benchmark ao vivo no cluster `cka` validando `settle()` < 4s em `wl-resources-too-high` e `wl-taint-toleration`; execução de check HTTP via Warm Probe < 500ms; testes unitários dos 3 novos check types e novos operadores.

---

### Frente 4 (P1) — Gestão do Banco de Questões, Quarentena & Telemetria Real
**Objetivo:** Transformar `bank_questions` em um acervo curado, rastreável e livre de repetições ou lixo histórico.

- **Mudanças Técnicas:**
  1. **Instrumentar telemetria real (`app/bank.py`, `app/sessions.py`):**
     - Incluir `weight_pct` no `SELECT` de `bank.draw_exam_sample()` (`app/bank.py:137-139`) para que `sessions.create()` grave `total_weight` real (não `0`).
     - Ao ativar um `session_item` (`_activate`), incrementar `times_used = times_used + 1` e atualizar `last_used_at` em `bank_questions`.
     - Ao passar no check (`sessions.check()`), atualizar `avg_solve_seconds` (média móvel ou recalculada via `session_items`) e incrementar `first_try_pass_count` quando `attempts == 1`.
     - Melhorar o dedup semântico (`app/bank.py:envelope_hash`): além do hash exato, adicionar coluna `archetype_id` e dedup por `(archetype_id, title_normalized)` ou similaridade estrutural para evitar múltiplos clones com títulos levemente parafraseados.
  2. **Endpoints de Curadoria & Quarentena (`app/main.py`, `app/bank.py`):**
     - `GET /api/bank/questions`: filtros por `state` (`published|draft|retired`), `domain`, `difficulty`, `source`, busca textual, paginação e métricas (`times_used`, `avg_solve_seconds`).
     - `GET /api/bank/questions/{id}`: retorna o `ScenarioEnvelope` completo, `probe_result_json` e `generator_meta_json`.
     - `POST /api/bank/questions/{id}/reprobe`: roda Gates + Solvability Probe em um `draft` ou `published`; se passar, promove para `published`.
     - `POST /api/bank/questions/{id}/repair`: executa o repair cirúrgico em um `draft` e publica se passar no probe.
     - `POST /api/bank/questions/{id}/retire`: marca a questão como `retired` com `retired_reason` (usado pelo botão "Report issue" durante o estudo).
     - `DELETE /api/bank/questions/{id}`: remove `draft` descartado (protegido contra exclusão de questões já referenciadas por `session_items`).
  3. **UI de Curadoria no Studio & "Report Issue" no Workspace (`static/js/studio.js`, `static/js/workspace.js`):**
     - Adicionar no Studio uma aba/seção **Bank & Quarantine** listando o total de questões por estado, permitindo abrir qualquer `draft` para ver o erro exato do probe e clicar em `Re-probe`, `AI Repair`, `Retire` ou `Delete`.
     - Adicionar no Exam Workspace um botão discreto **Report / Retire** ao lado de `Skip`: se uma questão parecer ambígua ou quebrada em runtime, o usuário a aposenta na hora com motivo e desbloqueia a sequência.
  4. **Saneamento do banco atual (`python -m app.bank prune` ou script CLI):**
     Fornecer comando idempotente para arquivar/limpar os 71 drafts antigos, aposentar os clones duplicados (`Allow Selected Traffic Through Default Deny` ×4) e aposentar os cenários Frankenstein do Composer v5 — mantendo os 17 seeds validados e as questões LLM sadias.

- **Impacto Esperado:** Fim da repetição cega de questões nas sessões, visibilidade total do porquê algo foi para quarentena e ciclo completo de cura/aposentadoria sem editar SQLite na mão.
- **Critérios de Aceite:** Sessões gravando `total_weight > 0` e atualizando `times_used`/`first_try_pass_count`/`avg_solve_seconds`; fluxo completo na UI de inspecionar um `draft`, reparar/re-probar e promover ou deletar.

---

### Frente 5 (P1/P2) — Experiência de Prática, Assets no Scratch & Modo `mock_exam`
**Objetivo:** Completar a fidelidade ao exame CKA real (PSI/Killer.sh) e corrigir atritos práticos do workspace e terminal.

- **Mudanças Técnicas:**
  1. **Modo `mock_exam` completo (`app/sessions.py`, `static/js/studio.js`, `static/js/workspace.js`, `static/js/app.js`):**
     - No modal **Practice**, permitir escolher entre **Study Mode** (feedback imediato Check → Next bloqueado, comportamento atual) e **Mock Exam (120 min)** (simulado realista estilo PSI/Killer.sh).
     - Em `mock_exam`:
       - Timer global regressivo de 120 minutos visível no header.
       - Navegação livre entre as questões pela fila (`Q1..Q15`), botão **Flag for Review (`🚩`)** e persistência de estado por questão (questões são aplicadas/limpas sob demanda ou mantidas isoladas por namespace).
       - Liberação de questões com `destructive: true` (com aviso explícito antes de ativar e acionamento automático de L2 ao finalizar).
       - Relatório final com nota ponderada oficial (`earned_weight / total_weight`), linha de corte CKA (`66%` PASS/FAIL) e detalhamento por domínio.
  2. **Disponibilidade de Assets no Terminal Scratch (`app/config.py`, `app/terminal.py`, `scenarios/seed/ca-helm-upgrade.json`):**
     - No startup/setup da app, sincronizar `scenarios/seed/assets/` para `~/.cka-arena/assets/` (Helm charts, overlays Kustomize).
     - Em `TerminalSession.spawn()` (`app/terminal.py:120-124`), criar symlink `assets -> ~/.cka-arena/assets` dentro de cada scratch dir `~/.cka-arena/scratch/<tab_id>/` e exportar `CKA_ASSETS=~/.cka-arena/assets`.
     - Atualizar `ca-helm-upgrade.json` e o prompt do Construtor para referenciar `./assets/...` (funcionando tanto na raiz do repo no Probe quanto dentro de qualquer aba do terminal no browser).
  3. **Polimento de UX no Workspace e Studio (`static/index.html`, `static/js/`):**
     - Expor `ssh_target` e `destructive` em `SessionService.get()`. Renderizar a pill de SSH no Workspace apenas quando `ssh_target` não for nulo (ou apontar dinamicamente para `ssh cka-<ssh_target>` em vez do `ssh cka-node01` fixo em `workspace.js:98`).
     - Incluir os resultados do último `check_run` da questão ativa no payload de `GET /api/sessions/{id}`, para que um F5 no browser não apague o drawer de diagnóstico.
     - Adicionar botão **Cancel** (`POST /api/generate/cancel`) no Live Job Card do Studio usando `asyncio.Task.cancel()` com cleanup limpo do probe ativo.
     - No startup (`lifespan` de `app/main.py`), marcar eventuais `generation_requests` deixados em `status='running'` de processos encerrados abruptamente como `status='aborted'`.
     - Adicionar botão **Check ⌘↵** na barra de rodapé do terminal (`static/index.html:80-94`), alinhando a UI implementada ao especificado em `README.md`/`PLAN.md`.

- **Impacto Esperado:** Experiência de simulado idêntica à prova oficial, zero falhas por caminho relativo em questões de Helm/Kustomize e controle total de jobs na UI.
- **Critérios de Aceite:** Sessão `mock_exam` completa calculando score ponderado (`earned_weight/total_weight`); `helm upgrade` de `ca-helm-upgrade.json` executável copiando direto do terminal scratch sem `cd`; cancelamento de job limpando namespace efêmero de prova.

---

### Frente 6 (P2) — Infraestrutura, Concorrência, LLM Ops & Higiene de Código
**Objetivo:** Garantir estabilidade operacional sob múltiplos usos, compatibilidade cross-provider (Multipass e `kind`), suporte a modelos locais e código limpo.

- **Mudanças Técnicas:**
  1. **Governança de Cluster (`ClusterLease`) & Engine Único (`app/main.py`):**
     - Compartilhar **uma única instância** de `ScenarioEngine` entre `SessionService`, `GenerationPipeline` e `Teardown`.
     - Introduzir um coordenador `ClusterLease` impedindo conflitos destrutivos: `reset-baseline` e `power stop/restart` retornam `409 Conflict` se houver geração rodando; geração com `node_commands` ou `destructive=True` é bloqueada enquanto houver sessão prática ativa (enquanto geração puramente namespace-scoped pode usar `cka-prove-*` isolado ou avisar).
  2. **Performance de SSH e `MultipassProvider` (`app/provider/multipass.py`, `app/ssh_runner.py`):**
     - Adicionar cache com TTL curto (ex.: 20s) no resultado de `MultipassProvider.nodes()`, invalidado imediatamente em caso de erro SSH ou ação de `ClusterPowerManager`.
     - Habilitar OpenSSH `ControlMaster=auto`, `ControlPath=~/.cka-arena/ssh-mux-%r@%h:%p`, `ControlPersist=120s` em `_ssh_base()` (`app/ssh_runner.py:104-113`), reduzindo latência de comandos repetidos nos nós de ~130ms para ~15ms.
  3. **Teardown agnóstico ao Provider & Baseline de Taints (`app/teardown.py`):**
     - Migrar `cleanup_session()`, `reset_clean()` e `drift()` de `ssh_runner.sudo_run(ip, ...)` para `provider.get().exec(name, ..., sudo=True)`, tornando o L1/L2/drift 100% funcionais também no provider `kind` (WSL2).
     - Capturar a lista baseline de taints e labels dos nós no `ClusterDoctor`, removendo em `reset_clean()` quaisquer taints/labels divergentes adicionados durante cenários (não apenas `cka-arena/practice=critical:NoSchedule-`).
  4. **LLM Client v2 & Observabilidade (`app/llm_client.py`, `app/db.py`, `static/js/settings.js`):**
     - Persistir `thinking` e `reasoning_effort` em `save_config()` e expor seletor na UI em **Settings → AI provider**.
     - Adicionar preset **`ollama`** (`http://127.0.0.1:11434/v1`, protocolo `openai`, sem obrigatoriedade de API key real — aceitando placeholder `"ollama"`) e permitir digitação de `model` customizado na UI além dos presets do dropdown.
     - Reaproveitar um único `httpx.AsyncClient` persistente por instância (fechado no shutdown do `lifespan`).
     - Estender `llm_generations` com colunas `job_id`, `duration_ms`, `prompt_tokens`, `completion_tokens`, `reasoning_tokens` e expor no Studio métricas de saúde da geração (taxa de publicação 7d, tempo médio por questão e top motivos de falha).
  5. **Higiene de repositório e suíte de testes:**
     - Remover `data/arena.db` (0 bytes, órfão) e verificar/mover YAMLs soltos na raiz (`deploy.yaml`, `role.yaml`, `rolebinding.yaml`) para `scenarios/examples/` ou remover se forem testes manuais antigos.
     - Resolver as tabelas mortas `terminal_sessions` e `command_audit` (0 linhas): implementar auditoria opt-in (G9) ou removê-las do schema até priorizá-las.
     - Corrigir o teste defeituoso `tests/test_composer.py:89` (`if False`) e adicionar testes de regressão cobrindo todos os novos gates, `Smart Settle`, `len_gte`, `INVALID` vs `ERROR`, histórico `assistant`, digest pré-cleanup e `ClusterLease`.

- **Impacto Esperado:** Zero race conditions no cluster, SSH ~8× mais rápido, paridade total Multipass/kind no teardown, suporte a Ollama offline e visibilidade de custos/latência da LLM.
- **Critérios de Aceite:** Suíte `pytest` expandida 100% verde; latência SSH medida em `doctor.health()` < 25ms após aquecimento de socket; L1/L2 testado contra mock de `KindProvider`.

---

## 5. Roadmap de Execução em 4 Ondas

| Onda | Frentes | Duração Est. | Entregáveis Principais | Critério de Aceite Mensurável |
| :--- | :--- | :---: | :--- | :--- |
| **Onda 1 — Estabilização Cirúrgica (P0)** | Frente 1 + Smart Settle + Warm Probe + `len_gte`/`INVALID` | **2–3 dias** | Histórico `assistant` nos retries; digest pré-cleanup; `len_gte` + `INVALID` + timeout probe; `BUILDER_SYSTEM` completo; reordenação D1/D2 → C → E; `--dry-run=server` em `solution.manifests`; gate JSON `-p` / campos imutáveis / anti-spoiler; `Smart Settle` + `Warm Probe` | Lote de 5 `exam_standard` conclui em **< 3 min** com **≥ 90% publicação**; `Check` com pod `Pending` responde em **< 3s**; 0 falsos `infra_error` por params inválidos |
| **Onda 2 — Motor de Geração v2 (P0)** | Frente 2 + Isolamento Efêmero + Novos Checks | **4–5 dias** | `app/curriculum.py` (35–40 arquétipos CNCF 2025/2026); `app/planner.py` (cobertura 5×3 + namespaces neutros + `avoid_recent`); few-shot dinâmico; Causal Incident Blueprints substituindo o Frankenstein Composer; probes paralelos em `cka-prove-*`; 3 novos check types + operadores | Lote de 5 `exam_standard` + 3 `killer_hardcore` + 2 `boss_fight` cobrindo **5/5 domínios**, **≥ 90% publicação**, **0 spoilers**, **0 clones**, **0 Frankenstein desconexos**, média **< 45s/questão** |
| **Onda 3 — Banco, Curadoria & Simulado Real (P1)** | Frente 4 + Frente 5 | **3–4 dias** | Telemetria `times_used`/`total_weight`/`avg_solve_seconds`; API + UI de Bank & Quarantine Inspector; botão `Report / Retire`; saneamento das 71 drafts e clones atuais; Modo `mock_exam` (120 min, flag, score ponderado); symlink de assets no scratch; botão `Check` no terminal e `Cancel` no Studio | Simulado de 15 questões (`mock_exam`) funcional ponta a ponta com score ponderado; `ca-helm-upgrade` resolvível direto do terminal scratch; quarentena inspecionável/reparável na UI |
| **Onda 4 — Resiliência, SSH/Kind & LLM Ops (P2)** | Frente 6 | **2–3 dias** | `ClusterLease` + `ScenarioEngine` único; cache TTL de nós + SSH `ControlMaster`; `teardown.py` via `provider.exec`; baseline de taints/labels; `thinking`/Ollama/modelo customizado na UI; `llm_generations` com tokens e duração; limpeza de repo e testes | `pytest` expandida 100% verde; SSH em < 25ms; L1/L2 verde em `KindProvider` e `MultipassProvider`; 0 `generation_requests` zumbis pós-restart |

---

## 6. Riscos, Trade-offs e Decisões Arquiteturais

1. **Orquestração própria vs. LangGraph/LangChain (decisão mantida):**
   Os problemas atuais **não** se devem à falta de um framework de agentes, e sim aos bugs de fluxo (omissão do histórico `assistant`, digest pós-cleanup, ausência de Slot Planner e `settle()` cego). Manter a máquina de estados própria em `async Python` continua sendo a escolha mais rápida, enxuta e fácil de depurar. *Gatilho de revisita:* apenas se no futuro quisermos dar um shell interativo `kubectl` para um agente autor iterar autonomamente em cenários de control plane altamente exploratórios.
2. **Trade-off: Warm Probe Pod × `NetworkPolicy`:**
   Um pod compartilhado no namespace `cka-arena-system` pode receber tráfego ou ser bloqueado de forma diferente de um pod no namespace do cenário quando há `NetworkPolicy` filtrando por `podSelector` ou `namespaceSelector`. **Regra de segurança obrigatória:** o validador só usa o Warm Probe Pod quando o cenário **não** declara nem aplica `NetworkPolicy` no namespace alvo (ou quando o check explicitamente define `probe_scope: "external"`). Cenários com `NetworkPolicy` continuam usando pod dentro do namespace (`label_selector` do `client`/`intruder` ou pod efêmero no próprio namespace).
3. **Trade-off: Probes paralelos × Estado compartilhado do cluster:**
   Rodar probes em paralelo acelera muito lotes grandes, mas cenários com `node_commands`, `PersistentVolume` cluster-scoped, `taints`, `ClusterRole`/`ClusterRoleBinding`, `GatewayClass` ou `destructive: true` alteram estado global do cluster. **Regra de isolamento:** apenas cenários puramente namespace-scoped rodam sob semáforo concorrente (máx. 2 simultâneos, com reescrita temporária de namespaces para `cka-prove-<slot>-<hex>`); todos os demais adquirem automaticamente o lock exclusivo do cluster.
4. **Trade-off: Custo/Latência × Modelo por Tier e Estágio:**
   Com `deepseek-flash` (fast), chamadas de geração duram ~5s vs. 45–90s com reasoning ativo. **Política recomendada:**
   - Normalizador (A), Revisor (C), 1º pass de `exam_standard` (B) e 1º repair (R1): modelo **fast (`thinking off` / effort `low`)**.
   - 1º pass de `killer_hardcore` / `boss_fight` (B): modelo **principal (`model`)** em modo rápido ou effort baixo, usando o exemplar few-shot e blueprint causal.
   - 2º repair (R2) e retries após falha complexa de probe em tiers duras: acionar **`deep=True`** seletivamente.
   - Suporte a **Ollama** local como opção offline gratuita na UI, ciente de que modelos 7B–14B locais terão menor taxa de aprovação de 1ª tentativa em `killer_hardcore`/`boss_fight` do que modelos frontier via API.


---

## 7. Status & Evidências Pós-Implementação

Todas as 4 ondas (6 frentes) foram implementadas e verificadas contra a suíte automatizada, banco SQLite, provedor LLM (`deepseek` / `deepseek-flash`) e cluster Multipass Kubernetes ao vivo (`controlplane`, `node01`, `node02`).

### Comparativo Antes vs. Depois (Observado)

| Métrica | Antes | Depois (Medido) | Evidência / Comando |
| :--- | :--- | :--- | :--- |
| **Suíte de Testes** | `106 passed` (com `test_composer.py` neutralizado por `if False`) | **`124 passed, 0 failed, 0 skipped`** em `45.58s` + **`node --check` OK** nos 8 arquivos `static/js/*.js` | `.venv/bin/pytest -q` (`test_planner.py`, `test_smart_settle_and_api.py`, `test_composer.py`) |
| **Validação das Seeds (Cluster Real)** | `settle()` cego + `ca-helm-upgrade` acoplado ao path do host + 2 seeds com spoilers no sintoma | **`17/17 PROBE OK`** em **`2m 00.65s`** (`cka-probe-runner` 1/1 Running em `node02`) | `.venv/bin/python -m app.seed validate` (pós-correção anti-spoiler em `ts-crashloop-fix.json` e `ts-image-pull.json`) |
| **Quarentena / Publicação LLM** | **60,2%** de quarentena histórica (`71` drafts vs `47` publicadas) | **`7/7` publicadas (`100%`), `0` quarentenas (`0%`)** no benchmark ao vivo | Pipeline v2 nos 3 tiers (`exam_standard` 3/3, `killer_hardcore` 2/2, `boss_fight` 2/2) |
| **Velocidade de Geração (`exam_standard`)** | `~29 min` (`1.734,6s`) para 5 questões | **`34,3s` para 3 questões** (`~11,4s`/questão) com probes em paralelo em namespaces efêmeros | Benchmark `GenerationPipeline` (`q-580070cb3005`, `q-637e1e6d8a5e`, `q-68967483835d`) |
| **Qualidade & Diversidade (`killer` / `boss`)** | 67% fallbacks `"Repair N cluster faults..."` · 12/14 em S&N · múltiplos Frankenstein `:` | **`killer_hardcore` 2/2 em `314,3s`** + **`boss_fight` 2/2 em `354,1s`** com incidentes causais coesos em stack única, namespaces neutros (`billing`, `reviews`, `reporting`, `ingest`, `notifications`, `gateway-edge`), `0` spoilers e `docs_links` reais | Inspeção direta de `q-9d61d6afe97d`, `q-f7cb242f5261`, `q-be9cf367b3ec`, `q-4ee23d479628` |
| **Saneamento do Banco SQLite** | `64` publicadas · `71` drafts · jobs `running` órfãos | **`5` jobs interrompidos recuperados**; `prune --apply` removeu **`71` drafts** e arquivou **`9` Composer `:` + `4` duplicadas** → banco final: **`58` publicadas, `0` drafts, `13` retired** | `.venv/bin/python -m app.bank prune --apply` + pós-benchmark |
| **Infra SSH, Terminal & Drift** | SSH sem multiplexação · terminal scratch quebrava `./assets` · `teardown.py` acoplado a SSH | `doctor.health()`: **`0,68s` / `0,64s`** (`ssh_ms`: **`12,4–13,4ms`** via `ControlMaster`) · symlink `./assets` + `CKA_ASSETS` ok no scratch · `Teardown.drift()` == **`False`** (`0` diffs nos 3 nós) | Checagem direta em `app/terminal.py`, `app/doctor.py`, `app/teardown.py` e `KindProvider` mock |
