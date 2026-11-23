# Prontidão para Implementação — Veredito da Auditoria Final

> Auditoria de coerência ponta a ponta da documentação (10 arquivos, 3 revisões) antes da autorização de implementação. Data: 2026-11-17.

---

## Veredito: ✅ PRONTO COM CONDIÇÕES

A especificação cobre **todas as 5 fases do roadmap** com contratos verificáveis (schema, endpoints, machine states, rubricas, design system). Nada bloqueia o início da **Fase 1**. **4 decisões** do dono são recomendadas antes de codificar as fases 3–5 (nenhuma bloqueia Fase 1–2).

### Correções aplicadas por esta auditoria (gaps mecânicos fechados)

| Achado | Correção |
| :--- | :--- |
| Labels de gerenciamento inconsistentes (`cka-arena/scenario-id` × `cka-arena.io/managed`) | Política única em `ARCHITECTURE.md` §4.3: `cka-arena.io/managed="true"` (sweep L1) + `cka-arena.io/scenario="<id>"` (cleanup L0) + `cka-arena.io/probe="true"` (sondas, TTL 120s) |
| API sem referência consolidada; `/api/generate` sem contrato; `{tab}`×`{tab_id}` | Nova `ARCHITECTURE.md` §13 — tabela completa de 13 endpoints + regras transversais (`202 {job_id}`, envelope de erro, endpoints de sessão check/next/skip/reset) |
| Sobreposição `llm_generator.py` × `pipeline.py` na árvore | Fundidos: `pipeline.py` absorve o prompt builder e o loop de auto-reparo |
| Varredura de consistência | Zero restos de revisões antigas (dual-window, pt-BR de UI, `scenarios` table, `prompt_pt_br`); fences, JSON do envelope, SVG e links internos validados |

---

## Matriz de Cobertura por Fase (o que já está especificado, e onde)

| Fase | Contrato de saída | Especificação | Lacunas |
| :--- | :--- | :--- | :--- |
| **1. Fundação + Power Manager + Doctor + SSH Bridge** | `pyproject`, setup_ssh_bridge (expect + kubeconfig dedicado), máquina de estados, boot 7 passos, baseline de arquivos dos nós | `ARCHITECTURE.md` §3, §9, §13 · `PLAN.md` Fase 1 | nenhuma |
| **2. ScenarioEngine + Teardown** | setup/check/cleanup, 10 check types, contrato PASS/FAIL/SKIP/ERROR, L0/L1/L2 | `LLM_SCENARIO_SPEC.md` §2 · `LLM_PIPELINE_SPEC.md` §5–§6 · `ARCHITECTURE.md` §12 | nenhuma |
| **3. Pipeline A→E + Banco** | envelope v1.1 (inglês, formato killer.sh, `solution`), estágios A–E, prove-out + Solvability Probe, rubrica de dificuldade §5, `draw_exam_sample` | `LLM_SCENARIO_SPEC.md` §1, §1.2, §4, §5 · `LLM_PIPELINE_SPEC.md` §1–§4 · `ARCHITECTURE.md` §11 | nenhuma **para o design**; exige decisão D1 (provider default) e D2 (cenários destrutivos) |
| **4. UI Integrada + Liquid Glass** | shell único, tokens, 3 materiais de vidro, componentes, motion, piso de performance, wireframes EN | `DESIGN.md` (com CSS pronto) · `UX_UI_SPEC.md` §1–§6 · `design/mockup-workspace.svg` | nenhuma |
| **5. Seeds + Telemetria** | 15 seeds publicados via gates A–E, grade de cobertura, dashboard | `PLAN.md` Fase 5 · `ARCHITECTURE.md` §7, §11 | esforço de autoria (não design); ver D4 |

---

## Decisões do Dono (D1–D4) — **TODAS FECHADAS em 17/11/2026** ✅

### D1 — Provider LLM principal e origem da chave ✅ **DECIDIDO**
Catálogo suportado: GLM Coding Plan (Z.AI), OpenCode Go, DeepSeek, Anthropic, OpenAI-compatible/Ollama.
**Decisão:** GLM Coding Plan (`glm-5.3` principal / `glm-5.3-flash` para Normalizador+Revisor) com **DeepSeek como fallback** — mesmo padrão multi-provider já validado localmente. A configuração é feita **pela UI (Settings → AI provider)** e persistida em `llm_config.json` local (git-ignored); a chave nunca entra no repositório.

### D2 — Política de cenários destrutivos ✅ **DECIDIDO (recomendação aceita)**
O currículo CKA inclui tarefas que alteram o estado global do cluster (ex.: `etcdctl snapshot restore` + reinício do apiserver). Durante a prática, isso deixa o cluster em estado não-limpo para a questão seguinte.
**Decisão:** envelope ganha flag `destructive: true` (Gate D obriga a declarar — já propagado ao `LLM_SCENARIO_SPEC.md` §1.1/§3); questões destrutivas só entram em sessões `mock_exam`; ao concluí-las, a UI oferece L2 (clean reset) automaticamente antes do `Next`; os 15 seeds iniciais incluem apenas `etcd snapshot save` (não-restore), com variantes restore entrando depois via LLM e marcação `destructive`.

### D3 — Defaults das flags de comportamento ✅ **DECIDIDO (recomendação aceita)** *(aplicáveis já na Fase 1)*
| Flag | Recomendação | Racional |
| :--- | :--- | :--- |
| `auto_start_on_launch` | **ON** | requisito original: "cluster inicializado junto com a aplicação" |
| `auto_publish` (banco) | **ON** | questões que passaram nos gates A–E já são confiáveis; `draft` continua existindo para reprovadas |
| `command_audit` | **OFF** | privacidade por default; ligar quando quiser telemetria de abordagem |
| `CKA_ARENA_TOKEN` | indefinido | local-only; definir só se expor na rede da casa |

### D4 — Ordem interna da Fase 5 ✅ **DECIDIDO (recomendação aceita)**
**Decisão:** **3 seeds exemplares** (Troubleshooting, Cluster Architecture, Services & Networking) entram no fim da **Fase 2** — validam o engine (setup→check→cleanup) antes de existir LLM; os **12 restantes** seguem na Fase 5, publicados pelos mesmos gates A–E (já refletido no `PLAN.md` Fases 2/5).

---

## Checklist de Autorização

- [x] D1 confirmada (provider + origem da chave) — GLM + DeepSeek fallback
- [x] D2 confirmada (política destrutiva) — flag `destructive` + L2 antes do `Next`
- [x] D3 confirmada — defaults aceitos (`auto_start_on_launch` ON · `auto_publish` ON · `command_audit` OFF · sem token)
- [x] D4 confirmada — 3 seeds na Fase 2, 12 na Fase 5
- [x] **Projeto autorizado a implementar** — todas as decisões fechadas; iniciar pela Fase 1

## Riscos conhecidos e aceitos (não requerem decisão agora)

1. **DHCP pode mudar os IPs Bridged** — mitigação já especificada (self-heal de kubeconfig + regen do ssh-config a cada boot, `ARCHITECTURE.md` §9.3).
2. **Refração `feDisplacementMap` é Chrome-only** — progressive enhancement; o visual não depende dela (`DESIGN.md` §4).
3. **Snapshots de VM não são suportados no backend Multipass/macOS** (verificado ao vivo: `The snapshots feature is not implemented on this backend`) — o L2 foi redefinido como **clean reset** (baseline de arquivos + restart de agentes), validado com `drift=false` e addons preservados.
4. **Custo de geração LLM** — Normalizador/Revisor em modelo flash e 1 chamada por cenário no Construtor; reprovadas ≤ 2 retries (`LLM_PIPELINE_SPEC.md` §2).
