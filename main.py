from fastapi import FastAPI, UploadFile, File, Form
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import tempfile
import base64
import re
import subprocess
import sys
import google.generativeai as genai
from gtts import gTTS

# ========= CONFIGURE AQUI SUA CHAVE =========
API_KEY = "AQ.Ab8RN6IlIo1YBF_lBQ0W4u73XQqIIT7I7Mbpx6l5-yoUSVqt9g"  # SUBSTITUA PELA NOVA CHAVE
# =============================================

genai.configure(api_key=API_KEY)

app = FastAPI(title="Lenior API - Gemini")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# System prompt para a Lenior
SYSTEM_PROMPT = (
    "Você é Lenior, um assistente pessoal criado para Samuel. "
    "Você é especialista em programação, pode gerar e executar código Python. "
    "Responda sempre em português do Brasil, de forma amigável."
)

# Armazenamento de histórico (em memória)
sessoes = {}

class Mensagem(BaseModel):
    texto: str
    sessao_id: str = None

def extrair_codigo(texto):
    match = re.search(r"```python\n(.*?)```", texto, re.DOTALL)
    return match.group(1) if match else None

def executar_codigo(codigo):
    # Bloqueios simples
    for palavra in ['os.system', 'subprocess', 'eval', 'exec', '__import__']:
        if palavra in codigo:
            return {"erro": f"Comando bloqueado: {palavra}"}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(codigo)
        path = f.name
    try:
        resultado = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=5)
        return {"saida": resultado.stdout, "erro": resultado.stderr}
    except subprocess.TimeoutExpired:
        return {"erro": "Tempo limite excedido"}
    finally:
        os.unlink(path)

def sintetizar_voz(texto):
    try:
        # Tenta usar o modelo TTS do Gemini (se disponível)
        modelo_tts = genai.GenerativeModel("gemini-2.5-flash-tts-preview")
        config = {"speech_config": {"voice": "Kore"}}
        resposta = modelo_tts.generate_content(texto, generation_config=config, response_format={"type": "audio/wav"})
        audio_data = resposta.result
        if isinstance(audio_data, str):
            return base64.b64decode(audio_data)
        return audio_data
    except:
        # Fallback gTTS
        with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
            tts = gTTS(texto, lang='pt-br')
            tts.save(tmp.name)
            with open(tmp.name, 'rb') as f:
                data = f.read()
            os.unlink(tmp.name)
            return data

@app.get("/")
def home():
    return {"mensagem": "Lenior está online!"}

@app.post("/chat/texto")
async def chat_texto(mensagem: Mensagem):
    sessao_id = mensagem.sessao_id or "default"
    if sessao_id not in sessoes:
        model = genai.GenerativeModel("gemini-1.5-flash")
        chat = model.start_chat(history=[
            {"role": "user", "parts": [SYSTEM_PROMPT]},
            {"role": "model", "parts": ["Olá Samuel! Sou Lenior, como posso ajudá-lo?"]}
        ])
        sessoes[sessao_id] = chat
    else:
        chat = sessoes[sessao_id]

    resposta = chat.send_message(mensagem.texto)
    texto_resposta = resposta.text

    # Verifica se há código para executar
    codigo = extrair_codigo(texto_resposta)
    exec_result = None
    if codigo:
        exec_result = executar_codigo(codigo)
        if exec_result.get("saida"):
            texto_resposta += f"\n\n**Saída:**\n{exec_result['saida']}"
        if exec_result.get("erro"):
            texto_resposta += f"\n\n**Erro:**\n{exec_result['erro']}"

    # Gera áudio
    try:
        audio_bytes = sintetizar_voz(texto_resposta)
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
    except:
        audio_base64 = None

    return JSONResponse({
        "sessao_id": sessao_id,
        "texto": texto_resposta,
        "audio": audio_base64,
        "execucao": exec_result
    })

@app.post("/chat/audio")
async def chat_audio(audio: UploadFile = File(...), sessao_id: str = Form(None)):
    # Salva áudio recebido
    with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
        content = await audio.read()
        tmp.write(content)
        path = tmp.name

    # Transcrição com Gemini
    uploaded_file = genai.upload_file(path)
    model_stt = genai.GenerativeModel("gemini-1.5-flash")
    resposta_transcricao = model_stt.generate_content(["Transcreva este áudio", uploaded_file])
    texto_usuario = resposta_transcricao.text
    os.unlink(path)

    # Agora chama o chat de texto com a transcrição
    # Reutilizamos a lógica de chat texto
    sessao_id = sessao_id or "default"
    if sessao_id not in sessoes:
        model = genai.GenerativeModel("gemini-1.5-flash")
        chat = model.start_chat(history=[
            {"role": "user", "parts": [SYSTEM_PROMPT]},
            {"role": "model", "parts": ["Olá Samuel! Sou Lenior, como posso ajudá-lo?"]}
        ])
        sessoes[sessao_id] = chat
    else:
        chat = sessoes[sessao_id]

    resposta = chat.send_message(texto_usuario)
    texto_resposta = resposta.text

    codigo = extrair_codigo(texto_resposta)
    exec_result = None
    if codigo:
        exec_result = executar_codigo(codigo)
        if exec_result.get("saida"):
            texto_resposta += f"\n\n**Saída:**\n{exec_result['saida']}"
        if exec_result.get("erro"):
            texto_resposta += f"\n\n**Erro:**\n{exec_result['erro']}"

    try:
        audio_bytes = sintetizar_voz(texto_resposta)
        audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
    except:
        audio_base64 = None

    return JSONResponse({
        "sessao_id": sessao_id,
        "texto": texto_resposta,
        "audio": audio_base64,
        "execucao": exec_result
    })
