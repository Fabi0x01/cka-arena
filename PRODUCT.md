# CKA Arena — Verdade de Produto

> Contexto durável para design e produto. Fonte única de verdade sobre o que a plataforma é; decisões visuais vivem em [`DESIGN.md`](./DESIGN.md).

## O que é

Plataforma local de treino prático para a prova **Certified Kubernetes Administrator (CKA)**, no estilo KodeKloud/Killer.sh, rodando contra um cluster `kubeadm` real (3 VMs Multipass em Apple Silicon, v1.37.2). Três mecanismos se combinam:

1. **Terminal real no browser** (PTY do host em xterm.js) ao lado da questão — resolver e pedir validação sem sair da janela.
2. **Cluster gerenciado pela plataforma** — botão liga/desliga as VMs, boot instrumentado, clean reset (L2) ao fim da sessão, preservando os addons.
3. **Gerador de cenários com IA** — pipeline multi-estágio (Normalizador → Construtor → Revisor → gates → prove-out de solubilidade) que publica questões num banco; a prática sorteia pelas percentuais oficiais da prova.

## Para quem

Um único usuário: o próprio dono da máquina — engenheiro experiente, estudando para a CKA em sessões de alta concentração (30–120 min), com o navegador em tela cheia ou quase no MacBook Pro 16". Não existe segundo usuário, não existe mobile real, não existe demo pública.

## O que a superfície precisa provar

- **Confiança operacional:** o usuário enuncia, resolve no terminal, clica em Check e acredita no veredito — a interface é o painel de controle de um cluster real, não um curso animado.
- **Fluidez sem atrito:** cada segundo de interação é custo de estudo; nada de animação decorativa, carregamento lento ou mudança de contexto entre telas.
- **Estado sempre visível:** cluster (ligado/desligado/degradado), questão (fila, timer, check), sessão (progresso, fim, limpeza).

## Modo de superfície

**Operate** — ferramenta de alta concentração. Escaneabilidade, consistência e expectativas nativas acima de expressão; a marca vive em detalhes precisos.

## Compromissos de marca

- Identidade visual **Liquid Glass** (pinned pelo dono): materiais de vidro translúcido em camadas, sobre um fundo escuro profundo; moderno, fluido, bonito — onde possível.
- Um único padrão de frontend: **todas as visões compartilham o mesmo shell** — nenhuma "página" diferente da outra.
- Acessibilidade **explicitamente fora de escopo** nesta fase (decisão do dono; `prefers-reduced-motion` continua respeitado por custo zero).
- **Idioma do sistema: 100% inglês** (UI, enunciados, hints, soluções, toasts) — a prova CKA é em inglês; a leitura de tarefas no idioma do exame faz parte do treino. Documentação interna do projeto permanece em PT-BR.
