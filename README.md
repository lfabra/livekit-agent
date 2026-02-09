# 🎭 LiveKit Roleplay Agent

Agente de simulação de vendas por voz usando LiveKit e OpenAI para treinamento de equipes comerciais.

## 📋 Visão Geral

Este projeto implementa um agente de IA que simula clientes em cenários de vendas, permitindo que colaboradores pratiquem suas habilidades de negociação com feedback e avaliação automática.

### Características Principais

- ✅ **Simulação por Voz** - Conversas em tempo real com IA
- ✅ **Transcrição Automática** - Captura de toda a conversa
- ✅ **Avaliação Inteligente** - Feedback baseado em critérios configuráveis
- ✅ **Encerramento Automático** - IA detecta fim natural da conversa
- ✅ **VAD Otimizado** - Detecção de voz ajustada para evitar ruídos
- ✅ **Gravação de Áudio** - Salvamento automático no S3 via LiveKit Egress
- ✅ **BVC Noise Cancellation** - Remove ruídos e vozes secundárias (reuniões)

---

## 📁 Estrutura de Arquivos

```
livekit-agent/
├── agent.py                      # Agente original (STT + LLM + TTS separados)
├── agent_realtime.py             # Agente com OpenAI Realtime API
├── agent_realtime_v5_3.py        # v5.3 - Com gravação de áudio (Egress → S3)
├── agent_realtime_v5_4.py        # v5.4 - Com BVC Noise Cancellation (RECOMENDADO)
├── requirements.txt              # Dependências do agent.py
├── requirements_realtime.txt     # Dependências do agent_realtime.py
├── requirements_realtime_v5_4.txt # Dependências v5.4 (com noise cancellation)
├── .env                          # Variáveis de ambiente
└── README.md                     # Este arquivo
```

---

## 🚀 Versões do Agente

### `agent_realtime_v5_4.py` (v5.4) - **RECOMENDADO** ⭐

Usa a **OpenAI Realtime API** com **BVC (Background Voice Cancellation)** e **gravação de áudio**.

**Novidades da v5.4:**
- 🔇 **BVC Noise Cancellation** - Remove vozes secundárias e ruídos de fundo
- 🎬 **Gravação de Áudio** - Salva automaticamente no S3 via LiveKit Egress
- 🎯 Ideal para ambientes com múltiplas pessoas (reuniões, escritórios)

**Vantagens:**
- ⚡ Menor latência (~300-800ms)
- 🎯 Conversas mais naturais e fluidas
- 🔊 Qualidade de voz superior
- 🛡️ VAD menos sensível a ruídos externos
- 🔇 Isola apenas a voz principal do usuário
- 🎬 Gravações disponíveis para revisão posterior

### `agent_realtime_v5_3.py` (v5.3)

Versão com gravação de áudio, mas **sem** BVC noise cancellation.

**Quando usar:**
- Se não precisar de cancelamento de ruído avançado
- Para ambientes silenciosos

### `agent.py` (Original)

Usa pipeline tradicional: STT → LLM → TTS (componentes separados).

**Quando usar:**
- Se precisar de mais controle sobre cada etapa
- Se tiver problemas com a Realtime API
- Para debug/comparação

---

## 🔇 BVC - Background Voice Cancellation

O BVC (powered by Krisp) é um recurso avançado de cancelamento de ruído que:

| Remove | Mantém |
|--------|--------|
| ❌ Ruídos de fundo (tráfego, ventilador, música) | ✅ Voz principal do microfone |
| ❌ Vozes de outras pessoas na sala/reunião | |
| ❌ TV/Rádio de fundo | |
| ❌ Barulhos de teclado, cliques | |

### Requisitos do BVC

- ⚠️ **Requer LiveKit Cloud** (não funciona em self-hosted)
- ⚠️ **NÃO habilite Krisp no frontend** se usar BVC no agent
- ✅ Modelos rodam **localmente** - áudio não é enviado para Krisp

### Configuração no Agent

```python
from livekit.plugins import noise_cancellation
from livekit.agents import room_io

await session.start(
    room=ctx.room, 
    agent=agent,
    room_options=room_io.RoomOptions(
        audio_input=room_io.AudioInputOptions(
            noise_cancellation=noise_cancellation.BVC(),  # ← Background Voice Cancellation
        ),
    ),
)
```

### Modelos Disponíveis

| Modelo | Uso | Descrição |
|--------|-----|-----------|
| `BVC()` | **Reuniões/Escritório** | Remove vozes + ruídos (RECOMENDADO) |
| `NC()` | Ambientes silenciosos | Remove apenas ruídos, mantém vozes |
| `BVCTelephony()` | Chamadas SIP/Telefonia | Otimizado para telefonia |

---

## 🎬 Gravação de Áudio (Egress → S3)

A partir da v5.3, o agent grava automaticamente as conversas e salva no AWS S3.

### Configuração

```bash
# .env
RECORDING_ENABLED=true
AWS_BUCKET_NAME=seu-bucket
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=sua-key
AWS_SECRET_ACCESS_KEY=sua-secret
RECORDING_PATH_PREFIX=roleplays/recordings
```

### Estrutura no S3

```
s3://seu-bucket/
└── roleplays/
    └── recordings/
        └── {customer_id}/
            └── {session_id}_{timestamp}.mp4
```

### Fluxo de Gravação

1. Usuário clica "Iniciar Chamada"
2. Agent recebe comando `start_simulation`
3. Gravação inicia via LiveKit Egress API
4. Saudação é falada
5. Conversa acontece normalmente
6. Simulação encerra (usuário ou IA)
7. Gravação é finalizada e enviada ao S3
8. URL do arquivo é incluída na avaliação

---

## 📦 Instalação

### 1. Criar ambiente virtual (recomendado)

```bash
cd /usr/local/var/www/roleplays/livekit-agent
python3.12 -m venv venv
source venv/bin/activate
```

### 1.1 Para desativar

```bash
deactivate
```

### 2. Instalar dependências

**Para v5.4 (RECOMENDADO):**
```bash
pip install -r requirements.txt
```
### 3. Baixar modelos do BVC (IMPORTANTE!)

```bash
python agent.py download-files
```

### 4. Configurar variáveis de ambiente

Crie um arquivo `.env`:

```bash
# LiveKit
LIVEKIT_URL=wss://seu-projeto.livekit.cloud
LIVEKIT_API_KEY=sua-api-key
LIVEKIT_API_SECRET=seu-api-secret

# OpenAI
OPENAI_API_KEY=sua-openai-key

# Gravação (opcional)
RECORDING_ENABLED=true
AWS_BUCKET_NAME=seu-bucket
AWS_REGION=us-east-1
AWS_ACCESS_KEY_ID=sua-key
AWS_SECRET_ACCESS_KEY=sua-secret
RECORDING_PATH_PREFIX=roleplays/recordings

# Noise Cancellation (opcional, default=true)
NOISE_CANCELLATION_ENABLED=true

# Log
LOG_LEVEL=INFO
```

---

## ▶️ Executando

### Modo Desenvolvimento (com reload automático)

```bash
python agent.py dev
```

### Modo Produção

```bash
python agent.py start
```

### Com PM2 (recomendado para produção)

```bash
# Iniciar
pm2 start agent.py --name livekit-agent --interpreter python

# Ver logs
pm2 logs livekit-agent

# Reiniciar após atualização
pm2 restart livekit-agent

# Status
pm2 status
```

---

## 🔧 Configuração

### Vozes Disponíveis (Realtime API)

| Voz | Descrição |
|-----|-----------|
| `alloy` | Neutra, versátil |
| `ash` | Suave, natural |
| `ballad` | Expressiva |
| `coral` | Amigável |
| `echo` | Neutra masculina |
| `sage` | Calma, profissional |
| `shimmer` | Brilhante, otimista |
| `verse` | Dinâmica |
| `marin` | Nova voz |
| `cedar` | Nova voz |

### Parâmetros VAD

| Parâmetro | Valor | Descrição |
|-----------|-------|-----------|
| `threshold` | 0.7 | Sensibilidade (0.0-1.0, maior = menos sensível) |
| `silence_duration_ms` | 800 | Silêncio antes de processar |
| `prefix_padding_ms` | 400 | Buffer antes da detecção |
| `interrupt_response` | false | Permitir interrupções |

**Configuração v5.4:**
```python
turn_detection=TurnDetection(
    type="server_vad",
    threshold=0.7,              # Menos sensível a ruídos
    prefix_padding_ms=400,      # Buffer de áudio
    silence_duration_ms=800,    # Espera mais silêncio
    create_response=True,
    interrupt_response=False,   # IA não é interrompida
)
```

---

## 📡 Comunicação com Frontend

### Eventos enviados pelo Agent → Frontend

```javascript
// Transcrição em tempo real
{ type: "transcription", role: "user"|"ai", text: "..." }

// Avaliação final (com info da gravação)
{ 
  type: "evaluation", 
  data: { overall_score, strengths, weaknesses, ... },
  recording: { egress_id, filepath, s3_url }  // NOVO v5.3+
}

// Erro na avaliação
{ type: "evaluation_error", message: "..." }

// Encerramento automático pela IA
{ type: "auto_end_simulation", reason: "ai_ended" }

// Status do agent
{ type: "agent_speaking" }
{ type: "agent_listening" }
```

### Comandos Frontend → Agent

```javascript
// Iniciar simulação (também inicia gravação)
{ type: "start_simulation" }

// Encerrar simulação (para gravação e gera avaliação)
{ type: "end_simulation" }
```

---

## 🔍 Troubleshooting

### VAD muito sensível (capta ruídos externos)

1. **Ative o BVC** (v5.4) - resolve a maioria dos casos
2. Ou aumente o `threshold` e `silence_duration_ms`:
```python
threshold=0.8,              # Ainda menos sensível
silence_duration_ms=1000,   # Espera mais silêncio
```

### IA não fala a saudação inicial

Verifique se a função `generate_reply()` está sendo usada (não `say()`):
```python
await session.generate_reply(
    instructions=f"Você está atendendo uma ligação. Diga EXATAMENTE: \"{greeting}\""
)
```

### Erro "ServerVadOptions not found"

Use `TurnDetection` do pacote OpenAI:
```python
from openai.types.beta.realtime.session import TurnDetection
```

### BVC não funciona

1. Verifique se está usando **LiveKit Cloud** (não self-hosted)
2. Execute `python agent_realtime_v5_4.py download-files` para baixar os modelos
3. Verifique se `NOISE_CANCELLATION_ENABLED=true` no `.env`

### Gravação não funciona

1. Verifique as credenciais AWS no `.env`
2. Verifique se o bucket existe e tem permissões corretas
3. Verifique se `RECORDING_ENABLED=true`
4. Olhe os logs para mensagens de erro

### Transcrições duplicadas

O agente v5.4 já tem proteção contra duplicação nos callbacks. Verifique se está usando a versão mais recente.

---

## 📊 Logs

O agente usa emojis para facilitar a leitura dos logs:

| Emoji | Significado |
|-------|-------------|
| 🚀 | Inicialização |
| ✅ | Sucesso |
| 📞 | Saudação |
| 👤 | Fala do usuário |
| 🤖 | Fala da IA |
| 🏁 | Encerramento |
| 📊 | Avaliação |
| 🎬 | Gravação iniciada |
| 🛑 | Gravação parada |
| 🔇 | Noise Cancellation |
| ⚠️ | Aviso |
| ❌ | Erro |

---

## 📝 Histórico de Versões

### v5.4 (Atual) ⭐
- 🔇 **BVC Noise Cancellation** - Remove vozes secundárias e ruídos
- Ideal para ambientes com múltiplas pessoas
- Mantém todas as features da v5.3

### v5.3
- 🎬 **Gravação de Áudio** via LiveKit Egress → AWS S3
- URL da gravação incluída na avaliação
- Estrutura organizada por customer/session

### v5.2
- VAD menos sensível (`threshold=0.7`, `interrupt_response=false`)
- Correção da saudação inicial
- Deduplicação de mensagens melhorada

### v5.1
- Correção do `TurnDetection` (API atualizada)
- Migração de `ServerVadOptions` para `TurnDetection`

### v5.0
- Implementação inicial com OpenAI Realtime API
- Encerramento automático pela IA
- Transcrição em tempo real

---

## 🏗️ Arquitetura

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   Frontend      │────▶│    LiveKit      │────▶│   Agent v5.4    │
│   (Browser)     │◀────│    Cloud        │◀────│   (Python)      │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        │                       │                       ▼
        │                       │               ┌─────────────────┐
        │                       │               │   OpenAI API    │
        │                       │               │   (Realtime)    │
        │                       │               └─────────────────┘
        │                       │                       
        │                       ▼                       
        │               ┌─────────────────┐            
        │               │   Egress API    │────────────┐
        │               │   (Gravação)    │            │
        │               └─────────────────┘            │
        │                                              ▼
        ▼                                      ┌─────────────────┐
┌─────────────────┐                            │    AWS S3       │
│   PHP Backend   │                            │   (Gravações)   │
│   (Zend)        │                            └─────────────────┘
└─────────────────┘
        │
        ▼
┌─────────────────┐
│   PostgreSQL    │
│   (roleplay.*)  │
└─────────────────┘
```

### Fluxo de Áudio com BVC

```
[Usuário fala no microfone]
           │
           ▼
[WebRTC do Navegador]     ← Echo cancellation, gain control
           │
           ▼
[LiveKit Cloud]
           │
           ▼
[🔇 BVC no Agent]         ← Remove vozes secundárias + ruídos fortes
           │
           ▼
[OpenAI Realtime API]     ← Processa apenas a voz isolada
           │
           ▼
[Resposta da IA]
```

---

## 🤝 Integração com Copiloto

Este agente faz parte do módulo **Roleplays** da plataforma Copiloto, integrando-se com:

- **Backend PHP** (Zend Framework 1.12)
- **PostgreSQL** (schema `roleplay`)
- **Frontend** (Bootstrap 5 + LiveKit Client SDK)
- **AWS S3** (armazenamento de gravações)

---

## 📄 Licença

Projeto proprietário - Copiloto © 2025
