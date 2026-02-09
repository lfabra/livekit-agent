#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║             🎭 LIVEKIT ROLEPLAY AGENT - REALTIME API VERSION                 ║
╠══════════════════════════════════════════════════════════════════════════════╣
║                                                                              ║
║  VERSÃO COM OPENAI REALTIME API + GRAVAÇÃO DE ÁUDIO + NOISE CANCELLATION:   ║
║  ✅ Speech-to-Speech direto (latência ~300-800ms)                           ║
║  ✅ VAD semântico nativo da OpenAI                                          ║
║  ✅ Transcrições de usuário e IA funcionando                                ║
║  ✅ Auto-encerramento quando IA detecta fim da conversa                     ║
║  ✅ Metadata via room (criado pelo PHP)                                     ║
║  ✅ Avaliação automática ao final                                           ║
║  ✅ Comunicação com frontend via DataChannel                                ║
║  ✅ Gravação de áudio via LiveKit Egress API → S3                           ║
║  ✅ NOVO: BVC - Background Voice Cancellation (Krisp)                       ║
║     └─ Remove ruídos de fundo (tráfego, música, ventilador)                 ║
║     └─ Remove vozes secundárias (outras pessoas na sala/reunião)            ║
║     └─ Isola apenas a voz principal do usuário                              ║
║                                                                              ║
║  AUTOR: Leonardo Fabra Gomez                                                 ║
║  DATA: 2025-01-31                                                            ║
║  VERSÃO: 5.4 REALTIME + EGRESS RECORDING + BVC                              ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

import json
import logging
import os
import asyncio
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

from livekit import rtc, api
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
    room_io,  # NOVO: Para configurar opções de áudio
)
from livekit.plugins import openai
from livekit.plugins import noise_cancellation  # NOVO: Plugin de cancelamento de ruído

# CORREÇÃO: Importar TurnDetection do pacote OpenAI
from openai.types.beta.realtime.session import TurnDetection

load_dotenv()

# ============================================================
# CONFIGURAÇÃO DE LOGGING
# ============================================================
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("roleplay-agent-realtime")

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("openai").setLevel(logging.WARNING)
logging.getLogger("livekit").setLevel(logging.INFO)


# ============================================================
# CONFIGURAÇÃO DE GRAVAÇÃO (S3)
# ============================================================
RECORDING_ENABLED = os.getenv("RECORDING_ENABLED", "true").lower() == "true"
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME", "")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY", "")
RECORDING_PATH_PREFIX = os.getenv("RECORDING_PATH_PREFIX", "roleplays/recordings")


# ============================================================
# CONFIGURAÇÃO DE NOISE CANCELLATION (BVC)
# ============================================================
# BVC = Background Voice Cancellation (powered by Krisp)
# - Remove ruídos de fundo (tráfego, música, ventilador, etc.)
# - Remove vozes secundárias (outras pessoas na sala/reunião)
# - Isola APENAS a voz principal do usuário falando no microfone
#
# IMPORTANTE: 
# - Requer LiveKit Cloud (não funciona em self-hosted)
# - NÃO habilite Krisp no frontend se usar BVC no agent
# - Modelos rodam localmente, áudio não é enviado para Krisp
NOISE_CANCELLATION_ENABLED = os.getenv("NOISE_CANCELLATION_ENABLED", "true").lower() == "true"


# ============================================================
# MAPEAMENTO DE VOZES PARA REALTIME API
# ============================================================
VOICE_MAP_REALTIME = {
    'male': 'ash',
    'female': 'shimmer',
    'neutral': 'alloy',
    'alloy': 'alloy',
    'nova': 'shimmer',
    'echo': 'echo',
    'fable': 'verse',
    'onyx': 'ash',
    'shimmer': 'shimmer',
    'ash': 'ash',
    'ballad': 'ballad',
    'coral': 'coral',
    'sage': 'sage',
    'verse': 'verse',
    'marin': 'marin',
    'cedar': 'cedar',
}


# ============================================================
# CONFIGURAÇÃO PADRÃO (FALLBACK)
# ============================================================
DEFAULT_CONFIG = {
    "system_prompt": """Você é um cliente profissional recebendo uma ligação comercial.
Seja educado mas cético. Faça perguntas sobre o produto/serviço.
Responda de forma CURTA e natural em português brasileiro (1-2 frases no máximo).

IMPORTANTE: Quando a conversa chegar a uma conclusão natural (acordo fechado, 
recusa definitiva, ou despedida), você DEVE encerrar a ligação de forma educada 
dizendo algo como "Ok, obrigado pelo contato. Tchau!" e em seguida envie a 
palavra-chave [ENCERRAR_LIGACAO] sozinha em uma nova mensagem.""",
    "greeting": "Alô?",
    "voice": "ash",
    "evaluation_prompt": "Avalie a conversa.",
    "time_limit": 30
}

_sessions: dict = {}


# ============================================================
# CLASSE GERENCIADORA DE GRAVAÇÃO (EGRESS)
# ============================================================

class RecordingManager:
    """Gerencia a gravação de áudio via LiveKit Egress API."""

    def __init__(self, room_name: str, session_id: str = None, customer_id: str = None):
        self.room_name = room_name
        self.session_id = session_id or "unknown"
        self.customer_id = customer_id or "unknown"
        self.egress_id: Optional[str] = None
        self.recording_filepath: Optional[str] = None
        self.is_recording: bool = False
        self._lkapi: Optional[api.LiveKitAPI] = None

    def _is_configured(self) -> bool:
        """Verifica se a gravação está configurada corretamente."""
        if not RECORDING_ENABLED:
            logger.info("🎙️ Gravação desabilitada via RECORDING_ENABLED")
            return False
        if not AWS_BUCKET_NAME or not AWS_ACCESS_KEY_ID or not AWS_SECRET_ACCESS_KEY:
            logger.warning("⚠️ Credenciais AWS não configuradas - gravação desabilitada")
            return False
        return True

    def _generate_filepath(self) -> str:
        """Gera o caminho do arquivo de gravação no S3."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Estrutura: roleplays/recordings/{customer_id}/{session_id}_{timestamp}.mp4
        filename = f"{self.session_id}_{timestamp}.mp4"
        return f"{RECORDING_PATH_PREFIX}/{self.customer_id}/{filename}"

    async def start_recording(self) -> bool:
        """Inicia a gravação de áudio da sala."""
        if not self._is_configured():
            return False

        if self.is_recording:
            logger.warning("⚠️ Gravação já está em andamento")
            return False

        try:
            logger.info(f"🎬 Iniciando gravação para room: {self.room_name}")

            # Gerar filepath único
            self.recording_filepath = self._generate_filepath()
            logger.info(f"   └─ Filepath: s3://{AWS_BUCKET_NAME}/{self.recording_filepath}")

            # Criar cliente da API LiveKit
            self._lkapi = api.LiveKitAPI()

            # Configurar request de gravação
            # audio_only=True para gravar apenas áudio (menor custo e tamanho)
            req = api.RoomCompositeEgressRequest(
                room_name=self.room_name,
                audio_only=True,
                file_outputs=[
                    api.EncodedFileOutput(
                        file_type=api.EncodedFileType.MP4,  # MP4 com codec AAC para áudio
                        filepath=self.recording_filepath,
                        s3=api.S3Upload(
                            bucket=AWS_BUCKET_NAME,
                            region=AWS_REGION,
                            access_key=AWS_ACCESS_KEY_ID,
                            secret=AWS_SECRET_ACCESS_KEY,
                        ),
                    )
                ],
            )

            # Iniciar gravação via Egress
            result = await self._lkapi.egress.start_room_composite_egress(req)
            
            self.egress_id = result.egress_id
            self.is_recording = True

            logger.info(f"✅ Gravação iniciada!")
            logger.info(f"   └─ Egress ID: {self.egress_id}")
            logger.info(f"   └─ Status: {result.status}")

            return True

        except Exception as e:
            logger.error(f"❌ Erro ao iniciar gravação: {e}")
            import traceback
            traceback.print_exc()
            self.is_recording = False
            return False

    async def stop_recording(self) -> dict:
        """Para a gravação e retorna informações do arquivo."""
        result = {
            "success": False,
            "egress_id": self.egress_id,
            "filepath": None,
            "s3_url": None,
            "error": None
        }

        if not self.is_recording or not self.egress_id:
            logger.info("ℹ️ Nenhuma gravação ativa para parar")
            result["error"] = "no_active_recording"
            return result

        try:
            logger.info(f"🛑 Parando gravação: {self.egress_id}")

            if self._lkapi is None:
                self._lkapi = api.LiveKitAPI()

            # Parar o egress
            stop_result = await self._lkapi.egress.stop_egress(
                api.StopEgressRequest(egress_id=self.egress_id)
            )

            self.is_recording = False

            # Montar URL do S3
            s3_url = f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{self.recording_filepath}"

            result["success"] = True
            result["filepath"] = self.recording_filepath
            result["s3_url"] = s3_url

            logger.info(f"✅ Gravação finalizada!")
            logger.info(f"   └─ S3 URL: {s3_url}")
            logger.info(f"   └─ Status: {stop_result.status}")

        except Exception as e:
            logger.error(f"❌ Erro ao parar gravação: {e}")
            result["error"] = str(e)

        finally:
            # Fechar cliente API
            if self._lkapi:
                try:
                    await self._lkapi.aclose()
                except:
                    pass
                self._lkapi = None

        return result

    def get_recording_info(self) -> dict:
        """Retorna informações da gravação atual."""
        return {
            "egress_id": self.egress_id,
            "filepath": self.recording_filepath,
            "is_recording": self.is_recording,
            "room_name": self.room_name,
            "session_id": self.session_id,
        }


# ============================================================
# CLASSE GERENCIADORA DE TRANSCRIÇÃO
# ============================================================

class TranscriptionManager:
    """Gerencia transcrições de forma centralizada."""

    def __init__(self, room: rtc.Room, room_name: str):
        self.room = room
        self.room_name = room_name
        self.history: list = []
        self._last_ai_text: str = ""
        self._last_user_text: str = ""
        self._ai_buffer: str = ""
        self._ai_buffer_timer: Optional[asyncio.Task] = None
        self._greeting_sent: bool = False

    def add_user_message(self, text: str) -> bool:
        """Adiciona mensagem do usuário."""
        if not text or len(text.strip()) < 2:
            return False
        text = text.strip()
        if text == self._last_user_text:
            return False
        self._last_user_text = text
        logger.info(f"👤 USUÁRIO: {text}")
        self.history.append({"role": "user", "content": text})
        self._send_to_frontend("transcription", {"role": "user", "text": text})
        return True

    def add_ai_message(self, text: str) -> bool:
        """Adiciona mensagem da IA com buffer para evitar fragmentação."""
        if not text or len(text.strip()) < 2:
            return False
        text = text.strip()
        
        if "[ENCERRAR_LIGACAO]" in text:
            if self._ai_buffer:
                self._flush_ai_buffer()
            display_text = text.replace("[ENCERRAR_LIGACAO]", "").strip()
            if display_text:
                self._process_ai_message(display_text)
            return True
        
        if text == self._last_ai_text:
            return False
            
        if self._last_ai_text and text in self._last_ai_text:
            return False
            
        if self._last_ai_text and self._last_ai_text in text:
            logger.debug(f"📝 Substituindo fragmento por versão completa")
            self._last_ai_text = text
            if self.history and self.history[-1]["role"] == "assistant":
                self.history[-1]["content"] = text
                self._send_to_frontend("transcription", {"role": "ai", "text": text, "replace": True})
            return False
            
        return self._process_ai_message(text)
    
    def _process_ai_message(self, text: str) -> bool:
        """Processa e adiciona mensagem da IA."""
        if text == self._last_ai_text:
            return False
        self._last_ai_text = text
        logger.info(f"🤖 IA: {text}")
        self.history.append({"role": "assistant", "content": text})
        self._send_to_frontend("transcription", {"role": "ai", "text": text})
        return False
    
    def _flush_ai_buffer(self):
        """Envia o buffer acumulado."""
        if self._ai_buffer:
            self._process_ai_message(self._ai_buffer)
            self._ai_buffer = ""

    def check_for_end_signal(self, text: str) -> bool:
        """Verifica se o texto contém sinal de encerramento."""
        return "[ENCERRAR_LIGACAO]" in text

    def _send_to_frontend(self, msg_type: str, data: dict = None):
        """Envia mensagem para o frontend via DataChannel."""
        try:
            message = {"type": msg_type}
            if data:
                message.update(data)
            payload = json.dumps(message).encode("utf-8")
            asyncio.create_task(
                self.room.local_participant.publish_data(payload, reliable=True)
            )
        except Exception as e:
            logger.error(f"❌ Erro ao enviar para frontend: {e}")

    def send_status(self, status: str):
        self._send_to_frontend(status)

    def send_error(self, message: str):
        self._send_to_frontend("evaluation_error", {"message": message})

    def send_evaluation(self, evaluation: dict, recording_info: dict = None):
        """Envia avaliação com informações da gravação."""
        data = {"data": evaluation}
        if recording_info:
            data["recording"] = recording_info
        self._send_to_frontend("evaluation", data)
    
    def send_auto_end(self, recording_info: dict = None):
        """Notifica o frontend que a IA encerrou a ligação."""
        logger.info("📞 IA solicitou encerramento da ligação")
        data = {"reason": "ai_ended"}
        if recording_info:
            data["recording"] = recording_info
        self._send_to_frontend("auto_end_simulation", data)

    def send_recording_ready(self, recording_info: dict):
        """Envia dados da gravação para o frontend."""
        logger.info(f"📼 Enviando dados de gravação: {recording_info.get('s3_url', 'N/A')}")
        self._send_to_frontend("recording_ready", recording_info)

    def get_history(self) -> list:
        return self.history.copy()


# ============================================================
# FUNÇÕES UTILITÁRIAS
# ============================================================

def map_voice_to_realtime(voice: str) -> str:
    """Mapeia voz do PHP para voz compatível com Realtime API."""
    voice_lower = voice.lower() if voice else 'neutral'
    mapped = VOICE_MAP_REALTIME.get(voice_lower, 'alloy')
    logger.info(f"🎤 Mapeamento de voz: '{voice}' → '{mapped}'")
    return mapped


def parse_metadata(metadata_str: str) -> dict:
    """Parse do metadata JSON enviado pelo PHP."""
    if not metadata_str:
        logger.warning("⚠️ Metadata vazio - usando configuração padrão")
        return DEFAULT_CONFIG.copy()

    try:
        data = json.loads(metadata_str)

        persona = data.get('persona', {})
        persona_name = persona.get('name', 'Cliente') if isinstance(persona, dict) else 'Cliente'
        persona_company = persona.get('company', 'N/A') if isinstance(persona, dict) else 'N/A'

        voice_config = data.get('voice', {})
        voice_raw = voice_config.get('name', 'neutral') if isinstance(voice_config, dict) else 'neutral'
        voice = map_voice_to_realtime(voice_raw)

        prompts = data.get('prompts', {})
        
        system_prompt = prompts.get('system', DEFAULT_CONFIG["system_prompt"])
        end_instruction = """

IMPORTANTE: Quando a conversa chegar a uma conclusão natural (acordo fechado, 
recusa definitiva, despedida do vendedor, ou quando você não tiver mais interesse), 
você DEVE encerrar a ligação de forma educada e natural, dizendo algo como 
"Ok, obrigado pelo contato. Tchau!" ou "Certo, vou pensar. Até mais!".
Após sua despedida, envie EXATAMENTE a palavra-chave [ENCERRAR_LIGACAO] sozinha."""
        
        if "[ENCERRAR_LIGACAO]" not in system_prompt:
            system_prompt += end_instruction

        config = {
            "system_prompt": system_prompt,
            "greeting": prompts.get('greeting', DEFAULT_CONFIG["greeting"]),
            "evaluation_prompt": prompts.get('evaluation', DEFAULT_CONFIG["evaluation_prompt"]),
            "voice": voice,
            "time_limit": data.get('config', {}).get('time_limit', 30),
            "criteria": data.get('criteria', []),
            "persona_name": persona_name,
            "session_id": data.get('session_id', 'unknown'),
            "roleplay_id": data.get('roleplay_id'),
            "customer_id": data.get('customer_id'),
            "user_id": data.get('user_id'),
        }

        logger.info(f"📋 Configuração carregada:")
        logger.info(f"   └─ Persona: {persona_name} @ {persona_company}")
        logger.info(f"   └─ Voz: {voice} (original: {voice_raw})")
        logger.info(f"   └─ Prompt: {len(config['system_prompt'])} chars")
        logger.info(f"   └─ Session ID: {config['session_id']}")

        return config

    except Exception as e:
        logger.error(f"❌ Erro ao processar metadata: {e}")
        return DEFAULT_CONFIG.copy()


async def generate_evaluation(tm: TranscriptionManager, config: dict, recording_info: dict = None):
    """Gera avaliação da conversa usando GPT-4."""
    try:
        history = tm.get_history()

        if len(history) < 2:
            logger.warning(f"⚠️ Conversa muito curta ({len(history)} msgs)")
            tm.send_error("Conversa muito curta para avaliação.")
            return

        logger.info(f"📊 Gerando avaliação para {len(history)} mensagens...")

        conversation_text = ""
        for msg in history:
            role = "PARTICIPANTE" if msg["role"] == "user" else "INTERLOCUTOR"
            conversation_text += f"{role}: {msg['content']}\n"

        eval_prompt = config.get("evaluation_prompt", DEFAULT_CONFIG["evaluation_prompt"])
        eval_prompt = eval_prompt.replace("{{CONVERSATION}}", conversation_text)

        import openai as openai_client
        client = openai_client.AsyncOpenAI()

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": eval_prompt}],
            temperature=0.3,
            max_tokens=2000
        )

        result = response.choices[0].message.content

        json_str = result.strip()
        if json_str.startswith("```"):
            lines = json_str.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            json_str = "\n".join(lines)

        evaluation = json.loads(json_str)

        logger.info(f"✅ Avaliação concluída: Score = {evaluation.get('overall_score', 'N/A')}")
        
        # Enviar avaliação COM informações da gravação
        tm.send_evaluation(evaluation, recording_info)

    except Exception as e:
        logger.error(f"❌ Erro na avaliação: {e}")
        import traceback
        traceback.print_exc()
        tm.send_error(str(e))


# ============================================================
# FUNÇÃO PRINCIPAL - ENTRYPOINT
# ============================================================

async def entrypoint(ctx: JobContext):
    """Ponto de entrada do Agent LiveKit com Realtime API + Gravação + BVC."""
    room_name = ctx.room.name
    logger.info(f"{'='*60}")
    logger.info(f"🚀 ROLEPLAY AGENT v5.4 REALTIME + RECORDING + BVC - Room: {room_name}")
    logger.info(f"{'='*60}")

    # ========================================
    # 1. CONECTAR IMEDIATAMENTE
    # ========================================
    logger.info("🔌 Conectando na room...")
    await ctx.connect()
    logger.info("✅ Conectado!")

    # ========================================
    # 2. CARREGAR CONFIGURAÇÃO
    # ========================================
    config = DEFAULT_CONFIG.copy()

    if ctx.room.metadata:
        config = parse_metadata(ctx.room.metadata)
    else:
        logger.info("🔍 Aguardando metadata do participante...")
        for i in range(10):
            for p in ctx.room.remote_participants.values():
                if p.metadata:
                    config = parse_metadata(p.metadata)
                    break
            else:
                await asyncio.sleep(1)
                continue
            break
        else:
            logger.warning("⚠️ Usando configuração padrão")

    # ========================================
    # 3. INICIALIZAR COMPONENTES
    # ========================================
    tm = TranscriptionManager(ctx.room, room_name)
    
    # Inicializar gerenciador de gravação
    rm = RecordingManager(
        room_name=room_name,
        session_id=config.get("session_id", "unknown"),
        customer_id=str(config.get("customer_id", "unknown"))
    )
    
    _sessions[room_name] = {
        "config": config, 
        "tm": tm,
        "rm": rm,  # Recording Manager
        "started": False,
        "ending": False
    }

    voice = config.get("voice", "ash")
    
    # ========================================
    # 4. CRIAR MODELO REALTIME
    # ========================================
    logger.info(f"🎙️ Inicializando OpenAI Realtime API com voz: {voice}")
    
    realtime_model = openai.realtime.RealtimeModel(
        voice=voice,
        temperature=0.8,
        modalities=["text", "audio"],
        turn_detection=TurnDetection(
            type="server_vad",
            threshold=0.7,           # Maior = precisa de áudio mais alto para ativar
            prefix_padding_ms=400,   # Áudio antes da fala detectada
            silence_duration_ms=800, # Duração do silêncio para detectar fim da fala
            create_response=True,
            interrupt_response=False,
        ),
    )

    # ========================================
    # 5. CRIAR SESSÃO DO AGENT
    # ========================================
    session = AgentSession(
        llm=realtime_model,
    )

    # ========================================
    # 6. REGISTRAR CALLBACKS
    # ========================================
    
    _using_speech_committed = False

    @session.on("user_input_transcribed")
    def on_user_transcribed(event):
        """Captura transcrição do usuário."""
        if hasattr(event, 'transcript') and event.transcript:
            tm.add_user_message(event.transcript)

    @session.on("agent_speech_committed")
    def on_agent_speech(event):
        """Captura fala da IA quando commitada."""
        nonlocal _using_speech_committed
        _using_speech_committed = True
        
        if hasattr(event, 'content') and event.content:
            text = event.content
            if tm.check_for_end_signal(text):
                if not _sessions[room_name]["ending"]:
                    _sessions[room_name]["ending"] = True
                    tm.add_ai_message(text)
                    tm.send_auto_end()
                    asyncio.create_task(handle_auto_end(tm, config, rm))
            else:
                tm.add_ai_message(text)

    @session.on("conversation_item_added")
    def on_item_added(event):
        """Captura mensagens da conversa (fallback)."""
        item = getattr(event, 'item', None)
        if item is None:
            return
            
        role = getattr(item, 'role', None)
        if role:
            role = str(role).lower()
        
        if role == 'user':
            content = getattr(item, 'content', None)
            text = _extract_text_from_content(content)
            if text:
                tm.add_user_message(text)
            return
        
        if role == 'assistant' and not _using_speech_committed:
            content = getattr(item, 'content', None)
            text = _extract_text_from_content(content)
            if text:
                if tm.check_for_end_signal(text):
                    if not _sessions[room_name]["ending"]:
                        _sessions[room_name]["ending"] = True
                        tm.add_ai_message(text)
                        tm.send_auto_end()
                        asyncio.create_task(handle_auto_end(tm, config, rm))
                else:
                    tm.add_ai_message(text)

    @session.on("agent_started_speaking")
    def on_started():
        tm.send_status("agent_speaking")

    @session.on("agent_stopped_speaking")
    def on_stopped():
        tm.send_status("agent_listening")

    # ========================================
    # 7. HANDLER DE COMANDOS DO FRONTEND
    # ========================================

    @ctx.room.on("data_received")
    def on_data_received(data: rtc.DataPacket):
        try:
            payload = data.data if hasattr(data, 'data') else data
            if isinstance(payload, bytes):
                payload = payload.decode("utf-8")

            message = json.loads(payload)
            msg_type = message.get("type", "")

            if msg_type == "start_simulation":
                if _sessions[room_name]["started"]:
                    return
                _sessions[room_name]["started"] = True
                _sessions[room_name]["ending"] = False
                logger.info("▶️ SIMULAÇÃO INICIADA")
                
                # 🎬 INICIAR GRAVAÇÃO
                asyncio.create_task(start_recording_and_greet(session, rm, config, tm))

            elif msg_type == "end_simulation":
                if _sessions[room_name]["ending"]:
                    return
                _sessions[room_name]["ending"] = True
                logger.info("🏁 SIMULAÇÃO ENCERRADA (pelo usuário)")
                
                # 🛑 PARAR GRAVAÇÃO E AVALIAR
                asyncio.create_task(stop_recording_and_evaluate(tm, config, rm))

        except Exception as e:
            logger.error(f"❌ Erro ao processar comando: {e}")

    # ========================================
    # 8. INICIAR SESSÃO COM BVC (Noise Cancellation)
    # ========================================
    agent = Agent(instructions=config.get("system_prompt", ""))
    
    # ╔════════════════════════════════════════════════════════════════════════╗
    # ║  🔇 CONFIGURAÇÃO DE NOISE CANCELLATION (BVC - Background Voice Cancel) ║
    # ╠════════════════════════════════════════════════════════════════════════╣
    # ║  BVC() - Remove ruídos E vozes secundárias (ideal para reuniões)       ║
    # ║  NC()  - Remove apenas ruídos de fundo (não remove outras vozes)       ║
    # ║  BVCTelephony() - Otimizado para chamadas SIP/telefonia                ║
    # ╚════════════════════════════════════════════════════════════════════════╝
    
    if NOISE_CANCELLATION_ENABLED:
        logger.info("🔇 Noise Cancellation: HABILITADO (BVC - Background Voice Cancellation)")
        logger.info("   └─ Remove: ruídos de fundo + vozes secundárias")
        logger.info("   └─ Isola: apenas a voz principal do microfone")
        
        await session.start(
            room=ctx.room, 
            agent=agent,
            room_options=room_io.RoomOptions(
                audio_input=room_io.AudioInputOptions(
                    # BVC = Background Voice Cancellation
                    # Remove TANTO ruídos de fundo QUANTO vozes de outras pessoas
                    # Perfeito para cenários de reunião onde só a voz principal deve ser capturada
                    noise_cancellation=noise_cancellation.BVC(),
                ),
            ),
        )
    else:
        logger.info("🔇 Noise Cancellation: DESABILITADO")
        await session.start(room=ctx.room, agent=agent)

    logger.info("✅ PRONTO - Aguardando comando 'start_simulation'")
    logger.info(f"   └─ Modo: OpenAI Realtime API (Speech-to-Speech)")
    logger.info(f"   └─ Voz: {voice}")
    logger.info(f"   └─ Gravação: {'HABILITADA' if RECORDING_ENABLED else 'DESABILITADA'}")
    logger.info(f"   └─ Noise Cancel: {'BVC (vozes+ruídos)' if NOISE_CANCELLATION_ENABLED else 'DESABILITADO'}")
    logger.info(f"   └─ Latência esperada: ~300-800ms")
    logger.info(f"{'='*60}")


async def start_recording_and_greet(session: AgentSession, rm: RecordingManager, config: dict, tm: TranscriptionManager):
    """Inicia gravação e depois fala a saudação."""
    # Primeiro iniciar a gravação
    recording_started = await rm.start_recording()
    if recording_started:
        logger.info("✅ Gravação iniciada com sucesso")
    else:
        logger.warning("⚠️ Gravação não iniciada (continuando sem gravação)")
    
    # Depois falar a saudação
    greeting = config.get("greeting", "Alô?")
    await speak_greeting(session, greeting, tm)


async def speak_greeting(session: AgentSession, greeting: str, tm: TranscriptionManager):
    """Fala a saudação inicial usando generate_reply."""
    logger.info(f"📞 Saudação: '{greeting}'")
    tm._greeting_sent = True
    
    try:
        await session.generate_reply(
            instructions=f"Você está atendendo uma ligação. Diga EXATAMENTE: \"{greeting}\" - Não adicione nada antes ou depois."
        )
    except Exception as e:
        logger.warning(f"⚠️ Erro na saudação: {e}")


async def stop_recording_and_evaluate(tm: TranscriptionManager, config: dict, rm: RecordingManager):
    """Para a gravação e gera avaliação."""
    # Parar gravação primeiro
    recording_result = await rm.stop_recording()

    # Montar info da gravação para enviar junto com avaliação
    recording_info = None
    if recording_result["success"]:
        recording_info = {
            "egress_id": recording_result["egress_id"],
            "filepath": recording_result["filepath"],
            "s3_url": recording_result["s3_url"],
        }
        logger.info(f"✅ Gravação disponível: {recording_result['s3_url']}")

        # Enviar dados de gravação para o frontend imediatamente
        tm._send_to_frontend("recording_ready", recording_info)

    # Gerar avaliação (descomentado e passando recording_info)
    await generate_evaluation(tm, config, recording_info)


async def handle_auto_end(tm: TranscriptionManager, config: dict, rm: RecordingManager):
    """Lida com encerramento automático pela IA."""
    logger.info("🤖 IA encerrou a conversa automaticamente")
    await asyncio.sleep(1.5)
    await stop_recording_and_evaluate(tm, config, rm)


def _extract_text_from_content(content) -> Optional[str]:
    """Extrai texto de diferentes formatos de conteúdo."""
    if content is None:
        return None
        
    if isinstance(content, str):
        return content.strip() if content.strip() else None
        
    if isinstance(content, list) and len(content) > 0:
        texts = []
        for c in content:
            if isinstance(c, str):
                texts.append(c)
            elif hasattr(c, 'text') and c.text:
                texts.append(c.text)
        if texts:
            return " ".join(texts).strip()
    
    return None


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════════════════════╗
║             🎭 LIVEKIT ROLEPLAY AGENT - REALTIME API + BVC                   ║
╠══════════════════════════════════════════════════════════════════════════════╣
║  OpenAI Realtime API: Speech-to-Speech direto                                ║
║  LiveKit Egress: Gravação de áudio → S3                                      ║
║  🔇 BVC (Background Voice Cancellation):                                     ║
║     └─ Remove ruídos de fundo (tráfego, música, ventilador)                  ║
║     └─ Remove vozes secundárias (outras pessoas na reunião)                  ║
║     └─ Isola apenas a voz principal do usuário                               ║
║  Latência esperada: ~300-800ms (vs ~1.5-2.5s do pipeline tradicional)        ║
╚══════════════════════════════════════════════════════════════════════════════╝
    """)

    required = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "OPENAI_API_KEY"]
    missing = [v for v in required if not os.getenv(v)]

    if missing:
        print(f"❌ Variáveis de ambiente faltando: {', '.join(missing)}")
        exit(1)

    print(f"✅ LIVEKIT_URL: {os.getenv('LIVEKIT_URL')}")
    print(f"✅ LOG_LEVEL: {LOG_LEVEL}")
    print(f"✅ Modo: OpenAI Realtime API")
    
    # Status da gravação
    if RECORDING_ENABLED:
        if AWS_BUCKET_NAME and AWS_ACCESS_KEY_ID:
            print(f"✅ Gravação: HABILITADA")
            print(f"   └─ Bucket: {AWS_BUCKET_NAME}")
            print(f"   └─ Region: {AWS_REGION}")
            print(f"   └─ Path: {RECORDING_PATH_PREFIX}/")
        else:
            print(f"⚠️ Gravação: DESABILITADA (credenciais AWS faltando)")
    else:
        print(f"ℹ️ Gravação: DESABILITADA")
    
    # Status do Noise Cancellation
    if NOISE_CANCELLATION_ENABLED:
        print(f"✅ Noise Cancellation: BVC (Background Voice Cancellation)")
        print(f"   └─ Remove ruídos de fundo")
        print(f"   └─ Remove vozes secundárias")
        print(f"   └─ Isola voz principal")
    else:
        print(f"ℹ️ Noise Cancellation: DESABILITADO")
    
    print()

    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
