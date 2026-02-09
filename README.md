# LiveKit Roleplay Agent

Agente de IA que simula clientes em cenários de roleplay (vendas, suporte, etc.) usando comunicacao por voz em tempo real.

---

## Como funciona

Este agent **NAO e um servidor HTTP**. Ele e um **worker do LiveKit** que se conecta ao LiveKit Cloud e fica "ouvindo" por novas rooms.

A arquitetura e totalmente **desacoplada**:

```
┌─────────────────┐         ┌──────────────────┐         ┌─────────────────┐
│   Browser        │◄──wss──►│   LiveKit Cloud   │◄──wss──►│   agent.py      │
│   (usuario)      │         │ (servidor midia)  │         │   (Amazon AWS)  │
└─────────────────┘         └──────────────────┘         └────────┬────────┘
                                    │                             │
                                    │                             ▼
                                    │                     ┌───────────────┐
                                    │                     │  OpenAI API   │
                                    │                     │  (Realtime)   │
                                    │                     └───────────────┘
                                    ▼
                            ┌──────────────────┐
┌─────────────────┐         │   Egress API     │
│   PHP Backend    │         │   (Gravacao)     │
│   (Zend)         │         └────────┬─────────┘
└────────┬────────┘                  │
         │                           ▼
         ▼                   ┌──────────────────┐
┌─────────────────┐          │    AWS S3        │
│   PostgreSQL     │          │   (Gravacoes)    │
│   (roleplay.*)   │          └──────────────────┘
└─────────────────┘
```

### Fluxo passo a passo

1. O **PHP** (backend) cria uma room no LiveKit Cloud com metadata (prompt, persona, voz, criterios)
2. O **agent.py** (rodando na Amazon) detecta a nova room automaticamente e entra como participante
3. O **browser** do usuario tambem conecta na mesma room via WebSocket
4. Quando o usuario clica "Iniciar Chamada", o frontend envia `start_simulation` via DataChannel
5. O agent inicia a gravacao, fala a saudacao ("Alo?") e comeca a conversa
6. O agent usa a **OpenAI Realtime API** (Speech-to-Speech) para ouvir e responder em tempo real
7. Ao encerrar, o agent para a gravacao (salva no S3) e gera uma avaliacao automatica via GPT-4o

### Ponto importante

O **PHP backend NAO sabe onde o agent esta rodando**. Ele so cria a room no LiveKit Cloud. O agent se registra sozinho como worker e entra nas rooms automaticamente. Por isso:

- Se o agent estiver **desligado**, a ligacao nao funciona (o usuario fica falando sozinho, ninguem "atende")
- Se o agent estiver **ligado** (na Amazon, na sua maquina local, ou em qualquer lugar), ele entra automaticamente
- **NAO existe configuracao no PHP apontando pro agent** — a conexao e feita pelo proprio agent ao LiveKit Cloud

---

## Estrutura de arquivos

```
roleplays-livekit-server/
├── agent.py               # Agente principal (OpenAI Realtime API + BVC + Gravacao)
├── requirements.txt       # Dependencias Python
├── .env                   # Variaveis de ambiente (NAO committar)
├── env.example            # Exemplo de .env
└── README.md              # Este arquivo
```

---

## Funcionalidades

- **Simulacao por voz** — conversas em tempo real com IA via OpenAI Realtime API (~300-800ms de latencia)
- **Transcricao automatica** — captura de toda a conversa em tempo real
- **Avaliacao inteligente** — feedback automatico baseado em criterios configuraveis (GPT-4o)
- **Encerramento automatico** — a IA detecta o fim natural da conversa e encerra
- **Gravacao de audio** — salva automaticamente no AWS S3 via LiveKit Egress
- **BVC Noise Cancellation** — remove ruidos de fundo e vozes secundarias (Krisp)

---

## BVC - Background Voice Cancellation

O BVC (powered by Krisp) e um recurso de cancelamento de ruido que roda **localmente** no agent:

| Remove                                              | Mantem                          |
|-----------------------------------------------------|---------------------------------|
| Ruidos de fundo (trafego, ventilador, musica)       | Voz principal do microfone      |
| Vozes de outras pessoas na sala/reuniao             |                                 |
| TV/Radio de fundo                                   |                                 |
| Barulhos de teclado, cliques                        |                                 |

**Requisitos:**
- Requer **LiveKit Cloud** (nao funciona em self-hosted)
- NAO habilite Krisp no frontend se usar BVC no agent
- Modelos rodam localmente, audio nao e enviado para servidores Krisp

---

## Configuracao

### Variaveis de ambiente (.env)

```env
# LiveKit Cloud
LIVEKIT_URL=wss://seu-projeto.livekit.cloud
LIVEKIT_API_KEY=sua-api-key
LIVEKIT_API_SECRET=seu-api-secret

# OpenAI
OPENAI_API_KEY=sua-openai-key

# Gravacao de audio (opcional)
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

### Vozes disponiveis (Realtime API)

| Voz       | Descricao            |
|-----------|----------------------|
| `alloy`   | Neutra, versatil     |
| `ash`     | Suave, natural       |
| `ballad`  | Expressiva           |
| `coral`   | Amigavel             |
| `echo`    | Neutra masculina     |
| `sage`    | Calma, profissional  |
| `shimmer` | Brilhante, otimista  |
| `verse`   | Dinamica             |
| `marin`   | Nova voz             |
| `cedar`   | Nova voz             |

### Parametros VAD (Voice Activity Detection)

| Parametro              | Valor | Descricao                                 |
|------------------------|-------|-------------------------------------------|
| `threshold`            | 0.7   | Sensibilidade (0.0-1.0, maior = menos sensivel) |
| `silence_duration_ms`  | 800   | Silencio antes de processar               |
| `prefix_padding_ms`    | 400   | Buffer antes da deteccao                  |
| `interrupt_response`   | false | Permitir interrupcoes                     |

---

## Comunicacao Agent <-> Frontend

### Agent envia para o Frontend (via DataChannel)

```json
// Transcricao em tempo real
{ "type": "transcription", "role": "user|ai", "text": "..." }

// Avaliacao final (com info da gravacao)
{ "type": "evaluation", "data": { "overall_score": 8, "..." }, "recording": { "s3_url": "..." } }

// Erro na avaliacao
{ "type": "evaluation_error", "message": "..." }

// Encerramento automatico pela IA
{ "type": "auto_end_simulation", "reason": "ai_ended" }

// Status do agent
{ "type": "agent_speaking" }
{ "type": "agent_listening" }

// Gravacao pronta
{ "type": "recording_ready", "s3_url": "...", "egress_id": "...", "filepath": "..." }
```

### Frontend envia para o Agent (via DataChannel)

```json
// Iniciar simulacao (tambem inicia gravacao)
{ "type": "start_simulation" }

// Encerrar simulacao (para gravacao e gera avaliacao)
{ "type": "end_simulation" }
```

---

## Deploy em producao (AWS Lightsail / Ubuntu)

### Requisitos do servidor

- 2 vCPU
- 4 GB RAM (8 GB recomendado)
- Ubuntu 22.04 LTS
- O agent NAO expoe portas publicas (conexao e outbound via WebSocket)

### 1. Preparar o sistema

```bash
sudo apt update && sudo apt -y upgrade
sudo apt -y install git curl unzip build-essential
```

Swap (opcional, recomendado para 4GB RAM):

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 2. Instalar Python 3.12

```bash
sudo apt -y install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa -y
sudo apt update
sudo apt -y install python3.12 python3.12-venv python3.12-dev
```

### 3. Clonar o projeto

```bash
sudo mkdir -p /opt/roleplays
sudo chown -R $USER:$USER /opt/roleplays
cd /opt/roleplays
git clone git@github.com:lfabra/livekit-agent.git
cd livekit-agent
```

### 4. Criar ambiente virtual e instalar dependencias

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. Baixar modelos do BVC (OBRIGATORIO na primeira vez)

```bash
source venv/bin/activate
python agent.py download-files
```

Esse comando baixa os modelos de machine learning do Krisp para o cancelamento de ruido. So precisa rodar **uma vez** (ou quando atualizar a versao do plugin `livekit-plugins-noise-cancellation`).

### 6. Configurar .env

```bash
cp env.example .env
nano .env
# Preencher com as credenciais reais
chmod 600 .env
```

### 7. Testar manualmente

```bash
source venv/bin/activate
python agent.py dev
```

Se aparecer "PRONTO - Aguardando comando 'start_simulation'", esta funcionando.

### 8. Criar servico systemd (producao)

```bash
sudo nano /etc/systemd/system/livekit-agent.service
```

Conteudo:

```ini
[Unit]
Description=LiveKit Roleplays Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/roleplays/livekit-agent
EnvironmentFile=/opt/roleplays/livekit-agent/.env
ExecStart=/opt/roleplays/livekit-agent/venv/bin/python agent.py start
Restart=always
RestartSec=3
User=ubuntu
Group=ubuntu
StandardOutput=journal
StandardError=journal
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

### 9. Ativar o servico

```bash
sudo systemctl daemon-reload
sudo systemctl enable livekit-agent
sudo systemctl start livekit-agent
```

---

## Comandos do dia a dia

### Gerenciar o servico

```bash
# Ver status (se esta rodando)
sudo systemctl status livekit-agent

# Desligar
sudo systemctl stop livekit-agent

# Ligar
sudo systemctl start livekit-agent

# Reiniciar (desliga e liga)
sudo systemctl restart livekit-agent
```

**Nota:** com `Restart=always` no systemd, se o processo crashar ele reinicia sozinho. Mas se voce der `stop` manual, ele respeita e fica parado.

### Ver logs

```bash
# Logs em tempo real
sudo journalctl -u livekit-agent -f

# Ultimas 100 linhas
sudo journalctl -u livekit-agent -n 100

# Logs de hoje
sudo journalctl -u livekit-agent --since today
```

### Atualizar o codigo

```bash
cd /opt/roleplays/livekit-agent
git pull
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart livekit-agent
```

---

## Troubleshooting

### A ligacao nao funciona (usuario fala sozinho)

O agent esta desligado. Verifique:

```bash
sudo systemctl status livekit-agent
```

Se estiver `inactive`, ligue com `sudo systemctl start livekit-agent`.

### VAD muito sensivel (capta ruidos)

1. Ative o BVC no `.env`: `NOISE_CANCELLATION_ENABLED=true`
2. Ou ajuste os parametros no `agent.py`: aumente `threshold` e `silence_duration_ms`

### IA nao fala a saudacao inicial

Verifique nos logs se o agent esta recebendo o comando `start_simulation`:

```bash
sudo journalctl -u livekit-agent -f
```

### BVC nao funciona

1. Verifique se esta usando **LiveKit Cloud** (nao funciona em self-hosted)
2. Execute `python agent.py download-files` para baixar os modelos
3. Verifique se `NOISE_CANCELLATION_ENABLED=true` no `.env`

### Gravacao nao funciona

1. Verifique as credenciais AWS no `.env`
2. Verifique se o bucket existe e tem permissoes corretas
3. Verifique se `RECORDING_ENABLED=true`

---

## Gravacao de audio (Egress -> S3)

O agent grava automaticamente as conversas e salva no AWS S3.

### Estrutura no S3

```
s3://seu-bucket/
└── roleplays/
    └── recordings/
        └── {customer_id}/
            └── {session_id}_{timestamp}.mp4
```

### Fluxo

1. Usuario clica "Iniciar Chamada"
2. Agent recebe `start_simulation` via DataChannel
3. Gravacao inicia via LiveKit Egress API
4. Saudacao e falada
5. Conversa acontece normalmente
6. Simulacao encerra (usuario ou IA)
7. Gravacao e finalizada e enviada ao S3
8. URL do arquivo e incluida na avaliacao

---

## Logs (emojis)

| Emoji | Significado          |
|-------|----------------------|
| 🚀    | Inicializacao        |
| ✅    | Sucesso              |
| 📞    | Saudacao             |
| 👤    | Fala do usuario      |
| 🤖    | Fala da IA           |
| 🏁    | Encerramento         |
| 📊    | Avaliacao            |
| 🎬    | Gravacao iniciada    |
| 🛑    | Gravacao parada      |
| 🔇    | Noise Cancellation   |
| ⚠️    | Aviso                |
| ❌    | Erro                 |
