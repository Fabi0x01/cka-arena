# Especificação de Cenários e Contrato LLM (`ScenarioEnvelope`)

A LLM no **CKA Arena** tem um papel estrito: **arquiteta e geradora de cenários de laboratório/exame**. Ela nunca entrega a resposta durante a resolução e sua saída passa por um pipeline rígido de parsing, guardrails de segurança, aplicação real no cluster e sanity check antes de chegar à tela de estudo. A orquestração multi-estágio (**A** Normalizador → **B** Construtor → **C** Revisor → **D** Gates → **E** Prove-out com Solvability Probe), o banco de questões, o sorteio por percentuais da prova e o contrato formal de avaliação (PASS/FAIL/SKIP/ERROR) estão especificados em [`LLM_PIPELINE_SPEC.md`](./LLM_PIPELINE_SPEC.md).

---

## 1. Contrato JSON Estrito (`ScenarioEnvelope v1`)

A LLM deve retornar **exclusivamente um objeto JSON válido** seguindo exatamente este schema (validado via `Pydantic`):

```json
{
  "schema_version": "1.0",
  "id": "scn-netpol-dns-01",
  "title": "Isolamento de Backend preservando resolução DNS",
  "domain": "Services & Networking",
  "subtopics": ["NetworkPolicy", "CoreDNS", "Egress Rules"],
  "difficulty": "killer_hardcore",
  "weight": 8,
  "estimated_minutes": 7,
  "context_command": "kubectl config use-context cka",
  "ssh_target": null,
  "prompt": "A Deployment `web-api` in namespace `prod-checkout` is running only 1 of its 3 desired replicas.\n\nPerform the following tasks:\n1. Create a NetworkPolicy named `allow-api-to-db` in namespace `payments` that allows ingress only from pods labeled `app=frontend` on port `5432`.\n2. Ensure pods labeled `app=api` can still resolve internal DNS names (e.g. `postgres.payments.svc.cluster.local`).\n\nDo not modify the existing Deployments.",
  "copy_tokens": [
    "payments",
    "frontend",
    "api",
    "postgres",
    "allow-api-to-db",
    "5432"
  ],
  "docs_links": [
    {
      "label": "Network Policies",
      "url": "https://kubernetes.io/docs/concepts/services-networking/network-policies/"
    }
  ],
  "setup": {
    "namespaces": ["payments"],
    "manifests": [
      "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: api\n  namespace: payments\n..."
    ],
    "node_commands": []
  },
  "checks": [
    {
      "id": "chk-netpol-exists",
      "description": "NetworkPolicy `allow-api-to-db` existe no namespace `payments`",
      "type": "kubectl_resource_exists",
      "params": {
        "kind": "NetworkPolicy",
        "name": "allow-api-to-db",
        "namespace": "payments"
      },
      "failure_hint": "A NetworkPolicy `allow-api-to-db` não foi encontrada no namespace `payments`."
    },
    {
      "id": "chk-egress-dns",
      "description": "Pods com label `app=api` conseguem resolver `postgres.payments.svc.cluster.local`",
      "type": "pod_exec_exit_zero",
      "params": {
        "namespace": "payments",
        "label_selector": "app=api",
        "command": ["nslookup", "postgres.payments.svc.cluster.local"]
      },
      "failure_hint": "O pod `api` não conseguiu resolver DNS interno. Verifique se a regra de Egress libera UDP/TCP porta 53 para o `kube-system`."
    }
  ],
  "solution": {
    "manifests": [
      "apiVersion: networking.k8s.io/v1\nkind: NetworkPolicy\nmetadata:\n  name: allow-api-to-db\n  namespace: payments\n..."
    ],
    "commands": []
  },
  "cleanup": {
    "namespaces": ["payments"],
    "kubectl_commands": [],
    "node_commands": []
  },
  "reference_solution": "1. Inspect the labels...\n```bash\nkubectl -n payments get pods --show-labels\n```"
}
```

### 1.1 Extensões do Envelope v1.1 (pipeline + banco)

- **`solution` (bloco obrigatório):** manifests YAML e/ou comandos que resolvem o cenário de forma **automatizada** (aplicáveis via `kubectl apply`/`exec` sem humana no loop). É o insumo do **Solvability Probe** (Estágio E): a plataforma aplica o `solution` num clone de prova e exige que 100% dos checks fiquem `PASS` **antes** da questão entrar no banco — elimina questões insolúveis. A prosa didática continua em `reference_solution`.
- **Imutabilidade pós-publicação:** publicado no banco (`bank_questions.state = published`), o envelope não muda mais (`envelope_hash`); correções geram nova versão (`supersedes_question_id`) e a antiga é aposentada.
- **Dedup semântico:** fingerprint de `(domain, subtopics ordenados, título normalizado, hash dos manifests do setup)` — colisão com questão `published` descarta a nova (banco não enche de clones).
- **`destructive` (flag booleana, default `false` — decisão D2):** obrigatória para todo cenário cuja resolução altera estado global do cluster (`etcdctl snapshot restore`, `kubeadm certs renew`/`upgrade`, restart do apiserver). O Gate D rejeita operações destrutivas não declaradas; cenários `destructive: true` só entram em sessões `mock_exam`, a UI exige confirmação ao iniciá-los e oferece **L2 (snapshot restore)** automaticamente antes de liberar o `Next` (o estado não volta ao limpo via L0/L1).

### 1.2 Formato Exato de Prova (`prompt` em inglês — anatomia killer.sh / PSI Bridge)

> Decisão (Revisão 3): **o sistema é 100% inglês** — a prova CKA é em inglês e ler tarefas em inglês faz parte do treino. O campo `prompt` segue a anatomia do exame real, espelhando o simulador oficial [killer.sh](https://killer.sh/cka) (incluso na compra da prova) e o delivery PSI Bridge:

```text
Fix Node & Scale Deployment                 ← título curto imperativo (3–6 palavras)
Task weight: 8%                            ← peso simulado da questão
Use context: kubectl config use-context cka← sempre presente (era context_command)

A Deployment `web-api` in namespace `prod-checkout` is running only 1 of its 3
desired replicas.                            ← contexto: 1–2 frases no presente,
                                              sintomas observáveis — NUNCA a causa
                                              nem a solução
Perform the following tasks:
1. Restore the `kubelet` service on `node01` until the node reports `Ready`.
2. Scale `web-api` to `3` replicas in `prod-checkout`.
3. Pin all `web-api` pods to `node01` using `nodeSelector`.

Do not modify any resource outside the mentioned namespaces.   ← restrições
```

**Voz do exame (obrigatória):** imperativo direto (`Create`, `Scale`, `Fix`, `Save`, `Copy`); neutro e sem dicas de solução nem justificativas; todo identificador crítico em `backticks` (vira Copy-Pill); nenhuma menção aos checks; inglês técnico claro; restrições explícitas (`Do not modify/delete ...`, namespace alvo, naming, caminhos de saída em `/opt/...`).

---

## 2. Catálogo de Checks Determinísticos Suportados (`validator.py`)

O usuário nunca é avaliado por uma LLM durante o clique em **Check** — a verificação deve ser **100% determinística, rápida (< 5s no total) e imparcial**, igual ao motor de avaliação da prova real. A semântica formal — status `PASS`/`FAIL`/`SKIP`/`ERROR`, política de retry (FAIL nunca re-executa sozinho; ERROR sim), veredito *all-or-nothing* por questão, evidência por item e settle window — está contratada em `LLM_PIPELINE_SPEC.md` §5.

| `type` | O que verifica | Parâmetros (`params`) | Uso típico na CKA |
| :--- | :--- | :--- | :--- |
| `kubectl_resource_exists` | Existência de qualquer objeto da API K8s (`Deployment`, `NetworkPolicy`, `HTTPRoute`, `PVC`, `Role`, etc.) | `kind`, `name`, `namespace` (opcional) | Confirmar criação e nome exato do recurso. |
| `kubectl_jsonpath` | Compara valor extraído via JSONPath com esperado (`equals`, `contains`, `gte`, `regex`, `len_gte`) | `kind`, `name`, `namespace`, `jsonpath`, `operator`, `expected` | Verificar `replicas`, `image`, `storageClassName`, `tolerations`, `serviceAccountName`, `accessModes`, `type: NodePort`. |
| `pod_status_ready` | Confirma que pelo menos `min_ready` pods correspondentes ao seletor estão `Running` e `Ready=True` | `namespace`, `label_selector`, `min_ready` | Validar que pods saíram de `Pending`/`CrashLoopBackOff`. |
| `node_status_ready` | Confirma que o nó especificado está com condição `Ready=True` | `node_name` (`controlplane`, `node01`, `node02`) | Cenários de Troubleshooting de `kubelet` ou nó em `NotReady`. |
| `kubectl_auth_can_i` | Executa `kubectl auth can-i <verb> <resource> --as=system:serviceaccount:<ns>:<sa>` | `service_account`, `namespace`, `verb`, `resource`, `target_namespace`, `expected_allowed` (`true`/`false`) | Questões de RBAC (`Role`, `ClusterRole`, `RoleBinding`). |
| `pod_exec_exit_zero` | Executa comando dentro de um pod vivo (ou pod efêmero `curlimages/curl` / `busybox`) e valida exit code `0` e opcionalmente `stdout_contains` | `namespace`, `label_selector` (ou `ephemeral_probe: true`), `command`, `stdout_contains` | Testar conectividade real entre pods, Service DNS, `NetworkPolicy` (permitir quem deve passar e **negar quem não deve**), `HTTPRoute`/`Ingress`. |
| `pod_exec_must_fail` | Garante que um comando de conexão falha (timeout/exit != 0) | `namespace`, `label_selector`, `command` | Prova negativa obrigatória em `NetworkPolicy` (confirmar que `frontend` **não** acessa `postgres` diretamente). |
| `node_command_exit_zero` | Executa comando read-only via SSH no nó especificado e verifica exit code `0` / `stdout_contains` | `node`, `command`, `stdout_contains` | Verificar `systemctl is-active kubelet`, arquivos estáticos, ou arquivo de backup `etcd` salvo em `/opt/backup/etcd.db`. |
| `host_file_contains` | Verifica existência de arquivo salvo no host ou nó (ex.: saída de `kubectl get ... > /tmp/result.txt`) | `location` (`host` \| `controlplane` \| `node01` \| `node02`), `path`, `regex_patterns` | Questões clássicas da CKA que pedem para salvar nomes de nós/pods ordenados em um arquivo específico. |
| `helm_release_state` | Verifica via `helm list -n <ns> -o json` o status `deployed`, chart e versão/revisão | `namespace`, `release_name`, `expected_status`, `min_revision` | Questões de Helm (install, upgrade, rollback). |

---

## 3. Guardrails & Loop de Auto-Reparo (`Self-Healing Pipeline`)

LLMs ocasionalmente alucinam APIs obsoletas (ex.: `extensions/v1beta1`), nomes de imagens inexistentes em `arm64`, ou geram um cenário cujo `setup` falha ou cujos `checks` já nascem passando. Para garantir confiabilidade máxima:

### Gates Determinísticos (Estágios D + E.1 do Pipeline A→E)

> O pipeline completo tem 5 estágios — **A** Normalizador · **B** Construtor · **C** Revisor (agentes LLM; B usa modelo principal, A/C usam flash) · **D** Gates de código abaixo (itens 1–3) · **E** Prove-out no cluster (item 4: sanity + **Solvability Probe**: aplica `solution` e exige 100% PASS) — orquestrados **sem framework de agentes** (decisão fundamentada em `LLM_PIPELINE_SPEC.md` §1). O item 5 é o loop de auto-reparo que devolve o erro exato ao Construtor (≤ 2 retries).

1. **Schema & Syntax Gate:**
   - Todos os strings em `setup.manifests` e `solution.manifests` passam por `yaml.safe_load_all()`.
   - Verificação de **imagens compatíveis com `arm64`** (o cluster roda em Apple Silicon M1 Pro!): imagens sugeridas no prompt incluem `nginx:1.27-alpine`, `busybox:1.36`, `redis:7-alpine`, `postgres:16-alpine`, `registry.k8s.io/pause:3.10`, `curlimages/curl:8.10.1`.
2. **Security Blocklist Gate:**
   - Rejeita comandos SSH sem `backup_paths` declarado quando tocarem diretórios de sistema.
   - **Declaração de destrutividade (D2):** operações como `etcdctl snapshot restore`, `kubeadm certs renew/upgrade` ou restart do `kube-apiserver` só passam com `destructive: true` declarado; sem a flag, o envelope é rejeitado com erro explícito.
   - Rejeita comandos perigosos (`rm -rf /`, `kubeadm reset`, alterações fora de `/etc/kubernetes`, `/var/lib/kubelet`, `/opt/cka`, `/tmp`).
3. **Dry-Run Server Gate:**
   - Quando o `kube-apiserver` não é o alvo da quebra, roda `kubectl apply --dry-run=server -f -` nos manifests de `setup` para garantir que a API `v1.37.2` aceita exatamente aqueles campos (`apiVersion`, `spec`).
4. **Apply + Initial Fail Sanity Check:**
   - Aplica o `setup` no cluster.
   - Executa todos os `checks` imediatamente após o `setup`:
     - **Regra de Ouro:** Pelo menos 1 check **DEVE falhar** antes do usuário começar! Se todos os checks já retornarem `PASS` no instante zero, o cenário está mal formulado e é descartado/regenerado automaticamente.
5. **Auto-Reparo com Feedback (Max 2 retries):**
   - Se os estágios 1, 3 ou 4 falharem, o backend faz rollback imediato do cenário parcial e envia o erro exato (`stderr` do `kubectl` ou motivo do Sanity Check) de volta à LLM solicitando apenas a correção do `ScenarioEnvelope`.

---

## 4. Template do System Prompt da LLM

```text
Você é um Arquiteto Sênior de Exames da CNCF (criador de questões estilo Killer.sh e CKA oficial).
Sua missão é gerar cenários práticos inéditos para execução em um cluster Kubernetes kubeadm REAL.

TOPOLOGIA REAL DO CLUSTER DO CANDIDATO:
- Versão Kubernetes: v1.37.2
- Arquitetura dos Nós: Linux Ubuntu 22.04.5 LTS (ARM64 / Apple Silicon) — USE APENAS IMAGENS MULTI-ARCH / ARM64!
- Runtime: containerd://2.2.1
- CNI: Weave Net
- Nós disponíveis:
  1. controlplane (role: control-plane, IP: 192.168.1.123)
  2. node01 (role: worker, IP: 192.168.1.124)
  3. node02 (role: worker, IP: 192.168.1.125)
- Contexto kubectl: cka
- Add-ons instalados dinamicamente: {{INSTALLED_ADDONS}}

REGRAS ESTRITAS DE CONSTRUÇÃO DO CENÁRIO:
1. **All user-facing text in English (exam voice):** `prompt`, check `description`, `failure_hint`, `docs_links` labels and `reference_solution` must be in clear, concise technical English — imperative, neutral, zero solution hints — mirroring the real CKA / killer.sh question voice (anatomy in §1.2). Use Kubernetes resource terms verbatim (`Pod`, `Deployment`, `NetworkPolicy`).
2. Requested difficulty: {{DIFFICULTY}} — follow the measurable band of §5 exactly (requirements, resource kinds, traps, causal chain, checks, time target, weight); the Reviewer stage will reject scenarios outside the band:
   - `exam_standard`: 1–2 requirements, 1 namespace, no deliberate traps, single-step fix (target ≤ 4 min, weight 2–5).
   - `killer_hardcore`: 3–4 requirements, ≥ 1 fair trap (incompatible label selector, NetworkPolicy egress breaking DNS port 53, node taint, pre-existing broken manifest), diagnose-then-repair chain (target ≤ 7 min, weight 6–10).
   - `boss_fight`: multi-layer incident combining node infrastructure failure (kubelet/static pod/systemd via SSH) + dependent workload/network recovery, ≥ 2 traps, causal chain ≥ 3 (target ≤ 12 min, weight 11–16).
3. Todo identificador crítico no enunciado (namespaces, nomes de recursos, portas, labels, caminhos de arquivo) DEVE estar entre crases (`exemplo`) e listado em `copy_tokens`.
4. `setup` deve criar um ambiente realista (ou quebrado propositalmente) garantindo que os `checks` FALHEM antes da intervenção do candidato.
5. Os `checks` devem testar o ESTADO RESULTANTE no cluster ou nó, aceitando qualquer forma válida que o candidato use para resolver (imperativo ou declarativo). Nunca exija que o candidato use um comando específico se o estado da API for equivalente.
6. Todo comando em `setup.node_commands` que modifique arquivos do nó DEVE listar os caminhos originais em `backup_paths` para restauração automática.
7. Nunca use namespaces `kube-system`, `default`, `kube-public` para criar novos workloads de aplicação; use namespaces temáticos dedicados (ex: `cka-alpha`, `payments`, `ingress-lab`) para facilitar limpeza. (Exceção: troubleshooting de CoreDNS ou static pods do control plane).
8. Retorne APENAS JSON válido aderente ao schema `ScenarioEnvelope v1`. Não inclua texto fora do JSON.
9. Operações de `etcd` (`etcdctl snapshot save/restore`, `ETCDCTL_API=3`) devem rodar SEMPRE no nó `controlplane` via `node_commands` com `node: controlplane` — nunca no host do candidato nem em workers. Use o binário `etcdctl` e os certificados do nó (`/etc/kubernetes/pki/etcd/`); o `etcdctl` existente no Mac do candidato não participa dos checks.
10. O bloco `solution` deve resolver o cenário de forma AUTOMATIZADA (manifests YAML e/ou comandos `kubectl` aplicáveis sem intervenção humana) — ele alimenta o Solvability Probe, que aplica a solução num clone de prova e exige 100% dos checks `PASS`. Prosa didática vai apenas em `reference_solution`.
```

---

## 5. Rubrica de Dificuldade Mensurável (níveis realmente distintos)

> Requisito (Revisão 3): a diferença entre níveis **não é subjetiva** — é uma banda de complexidade medida direto do envelope e **enforçada no Estágio C** do pipeline: fora da banda em ≥ 2 eixos ⇒ `verdict: patch` com o delta explícito (ex.: *"`boss_fight` has only 2 requirements and 3 checks — needs 4–6 requirements and ≥ 6 checks"*). O Gate D também rejeita `boss_fight` sem `node_commands`/falha de infra.

| Eixo (medido no envelope) | `exam_standard` | `killer_hardcore` | `boss_fight` |
| :--- | :--- | :--- | :--- |
| Requisitos no `prompt` (bullets) | 1–2 | 3–4 | 4–6 |
| Espécies de recurso (setup + solution) | 0–2 kinds | ≥ 2 kinds | ≥ 3 kinds + infra de nó |
| Escopo | 0–1 namespace | 0–2 namespaces | multi-namespace **ou** falha de nó (kubelet / static pod / systemd) |
| Armadilhas deliberadas (justas) | 0 | ≥ 1 (label mismatch, egress DNS 53, taint, manifesto quebrado pré-existente) | ≥ 2 |
| Profundidade da cadeia causal | 1 (ação → resultado) | 2 (diagnosticar → reparar) | ≥ 3 (restaurar infra → workload dependente → validar) |
| Checks | 2–3 | 4–6 | 6–10, incluindo ≥ 1 prova negativa |
| Meta de tempo | ≤ 4 min | ≤ 7 min | ≤ 12 min |
| Peso simulado (`weight`) | 2–5 | 6–10 | 11–16 |

**Exemplo do que separa os níveis** (mesmo domínio, Services & Networking): `exam_standard` = "Create a Service `svc-a` of type NodePort `30080` for Deployment `frontend`"; `killer_hardcore` = o mesmo Service + NetworkPolicy que isola `backend` permitindo apenas `frontend` na `8080` **sem quebrar egress DNS 53** + salvar o manifesto em `/opt/cka/netpol.yaml`; `boss_fight` = kubelet do `node01` parado (SSH) + `frontend` preso em `ContainerCreating` + Service sem endpoints por label mismatch + NodePort exigido em nó específico via toleration.