# CKA Arena — Verdade de Produto

> Contexto durável para design e produto. Fonte única de verdade sobre o que a plataforma é; decisões visuais vivem em [`DESIGN.md`](./DESIGN.md).

## O que é

Plataforma local de treino prático para a prova **Certified Kubernetes Administrator (CKA)**, no estilo dos simuladores de prova, rodando contra um laboratório `kubeadm` real (três nós: VMs Multipass no macOS/Linux ou containers kind no WSL2/Linux com Docker). Quatro mecanismos se combinam:

1. **Terminal real no browser** (PTY do host em xterm.js) ao lado da questão — resolver e pedir validação sem sair da janela.
2. **Laboratório gerenciado pela plataforma** — botão liga/desliga, boot instrumentado e clean reset (L2) ao fim da sessão, preservando os addons.
3. **Gerador de cenários com IA** — pipeline multi-estágio (planejamento por arquétipo → Construtor → gates determinísticos → Revisor → prove-out de solubilidade) que publica questões num banco; a prática sorteia pelos pesos oficiais da prova.
4. **Pedagogia orientada por dados** — repetição espaçada por arquétipo, relatório de prontidão Go/No-Go, drills direcionados e Study Codex.

## Para quem

Um único usuário: quem está na frente da máquina — engenheiro experiente, estudando para a CKA em sessões de alta concentração (30–120 min), com o navegador em tela cheia ou quase. Não existe segundo usuário, não existe mobile real, não existe demo pública.

## O que a superfície precisa provar

- **Confiança operacional:** o usuário enuncia, resolve no terminal, clica em Check e acredita no veredito — a interface é o painel de controle de um cluster real, não um curso animado.
- **Fluidez sem atrito:** cada segundo de interação é custo de estudo; nada de animação decorativa, carregamento lento ou mudança de contexto entre telas.
- **Estado sempre visível:** cluster (ligado/desligado/degradado), questão (fila, timer, check), sessão (progresso, fim, limpeza).

## Modo de superfície

**Operate** — ferramenta de alta concentração. Escaneabilidade, consistência e expectativas nativas acima de expressão; a marca vive em detalhes precisos.

## Compromissos de marca

- Identidade visual **Orbital Control Console**: console de missão sobre superfícies anodizadas escuras, hierarquia por degraus de luminância e vidro translúcido reservado às camadas superiores (contrato completo em [`DESIGN.md`](./DESIGN.md)).
- Um único padrão de frontend: **todas as visões compartilham o mesmo shell** — nenhuma "página" diferente da outra.
- Acessibilidade **explicitamente fora de escopo** nesta fase (decisão do mantenedor; `prefers-reduced-motion` continua respeitado por custo zero).
- **Idioma do sistema: 100% inglês** (UI, enunciados, hints, soluções, toasts) — a prova CKA é em inglês; a leitura de tarefas no idioma do exame faz parte do treino. Documentação interna do projeto permanece em PT-BR.
