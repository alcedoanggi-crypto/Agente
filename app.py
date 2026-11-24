"""
Servidor que conecta WhatsApp (API oficial de Meta) con el agente de Gemini.

WhatsApp envía cada mensaje del cliente a /webhook, el agente responde
y este programa manda la respuesta de vuelta por WhatsApp.
"""

import hashlib
import hmac
import logging
import os
import threading
from collections import OrderedDict
from pathlib import Path

import requests
from dotenv import load_dotenv
from flask import Flask, abort, request

import agente

CARPETA = Path(__file__).resolve().parent
load_dotenv(CARPETA / ".env")

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "").strip()
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
WEBHOOK_VERIFY_TOKEN = os.getenv("WEBHOOK_VERIFY_TOKEN", "").strip()
META_APP_SECRET = os.getenv("META_APP_SECRET", "").strip()
GRAPH_API_VERSION = os.getenv("GRAPH_API_VERSION", "v23.0").strip()
# Número del asesor que recibe los avisos, con código de país y sin "+". Ej: 584121234567
TELEFONO_ASESOR = os.getenv("TELEFONO_ASESOR", "").strip()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("agente-ventas")

if not WHATSAPP_TOKEN:
    log.warning("Falta WHATSAPP_TOKEN en .env")
if not WHATSAPP_PHONE_NUMBER_ID:
    log.warning("Falta WHATSAPP_PHONE_NUMBER_ID en .env")
if not WEBHOOK_VERIFY_TOKEN:
    log.warning("Falta WEBHOOK_VERIFY_TOKEN en .env")

app = Flask(__name__)

# WhatsApp a veces reenvía el mismo mensaje; guardamos los últimos IDs para no responder dos veces.
_mensajes_vistos: OrderedDict[str, None] = OrderedDict()
_candado_vistos = threading.Lock()

DESCRIPCION_TIPOS = {
    "image": "una foto",
    "video": "un video",
    "audio": "una nota de voz",
    "document": "un documento",
    "location": "su ubicación",
    "sticker": "un sticker",
}


def ya_visto(id_mensaje: str) -> bool:
    if not id_mensaje:
        return False
    with _candado_vistos:
        if id_mensaje in _mensajes_vistos:
            return True
        _mensajes_vistos[id_mensaje] = None
        if len(_mensajes_vistos) > 1000:
            _mensajes_vistos.popitem(last=False)
        return False


def enviar_whatsapp(telefono: str, texto: str) -> None:
    if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
        log.error("No se puede enviar mensaje: faltan WHATSAPP_TOKEN o WHATSAPP_PHONE_NUMBER_ID.")
        return

    url = f"https://graph.facebook.com/{GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    datos = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"body": texto[:4000]},
    }
    try:
        r = requests.post(
            url,
            json=datos,
            headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
            timeout=20,
        )
        if r.status_code >= 300:
            log.error("Error enviando a %s: %s %s", telefono, r.status_code, r.text)
        else:
            log.info("Mensaje enviado a %s", telefono)
    except requests.RequestException as e:
        log.error("Error de red enviando a %s: %s", telefono, e)


def firma_valida(cuerpo: bytes, firma: str) -> bool:
    """Comprueba que el mensaje viene de verdad de Meta (si configuraste META_APP_SECRET)."""
    if not META_APP_SECRET:
        return True
    esperada = "sha256=" + hmac.new(
        META_APP_SECRET.encode("utf-8"), cuerpo, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(esperada, firma or "")


def atender(mensaje: dict, nombre: str) -> None:
    telefono = mensaje["from"]
    tipo = mensaje.get("type")

    if tipo == "text":
        texto = (mensaje.get("text") or {}).get("body", "")
    elif tipo == "interactive":
        inter = mensaje.get("interactive", {})
        texto = (inter.get("button_reply") or inter.get("list_reply") or {}).get("title", "")
    elif tipo == "image" and (mensaje.get("image") or {}).get("caption"):
        texto = f"[El cliente envió una foto con este texto: {mensaje['image']['caption']}]"
    else:
        texto = f"[El cliente envió {DESCRIPCION_TIPOS.get(tipo, 'un archivo')}]"

    if nombre:
        texto = f"(Nombre del cliente en WhatsApp: {nombre})\n{texto}"

    try:
        respuesta, resumen_asesor = agente.responder(telefono, texto)
    except Exception:
        log.exception("Error con Gemini")
        respuesta, resumen_asesor = (
            "Disculpe, tuve un problema técnico. Un asesor le escribirá en breve.",
            "El agente tuvo un error técnico al responder.",
        )

    enviar_whatsapp(telefono, respuesta)

    if resumen_asesor and TELEFONO_ASESOR:
        aviso = (
            "🔔 Cliente para atender\n"
            f"Nombre: {nombre or 'Sin nombre'}\n"
            f"Teléfono: +{telefono}\n"
            f"Qué quiere: {resumen_asesor}\n"
            f"Escríbale aquí: https://wa.me/{telefono}"
        )
        enviar_whatsapp(TELEFONO_ASESOR, aviso)
        log.info("Cliente %s pasado al asesor: %s", telefono, resumen_asesor)


@app.get("/webhook")
def verificar_webhook():
    """Meta llama aquí una sola vez para confirmar que el webhook es tuyo."""
    if (
        request.args.get("hub.mode") == "subscribe"
        and WEBHOOK_VERIFY_TOKEN
        and request.args.get("hub.verify_token") == WEBHOOK_VERIFY_TOKEN
    ):
        return request.args.get("hub.challenge", ""), 200
    abort(403)


@app.post("/webhook")
def recibir_mensaje():
    if not firma_valida(request.get_data(), request.headers.get("X-Hub-Signature-256", "")):
        log.warning("Mensaje rechazado: la firma no coincide. Revisa META_APP_SECRET (o déjalo vacío).")
        abort(403)

    datos = request.get_json(silent=True) or {}
    for entrada in datos.get("entry", []):
        for cambio in entrada.get("changes", []):
            valor = cambio.get("value", {})
            contactos = {
                c.get("wa_id"): c.get("profile", {}).get("name", "")
                for c in valor.get("contacts", [])
            }
            for estado in valor.get("statuses", []):
                if estado.get("errors"):
                    log.error("WhatsApp no pudo entregar a %s: %s", estado.get("recipient_id"), estado.get("errors"))
            for mensaje in valor.get("messages", []):
                log.info("Mensaje recibido de %s (tipo %s)", mensaje.get("from"), mensaje.get("type"))
                if ya_visto(mensaje.get("id", "")):
                    continue
                nombre = contactos.get(mensaje.get("from"), "")
                threading.Thread(target=atender, args=(mensaje, nombre), daemon=True).start()

    return "ok", 200


@app.get("/diagnostico")
def diagnostico():
    """Revisa la configuración. Ábrelo así: /diagnostico?clave=TU_WEBHOOK_VERIFY_TOKEN"""
    if not WEBHOOK_VERIFY_TOKEN or request.args.get("clave") != WEBHOOK_VERIFY_TOKEN:
        abort(403)
    r = []

    def item(ok, texto):
        r.append(("✅ " if ok else "❌ ") + texto)

    item(bool(WHATSAPP_TOKEN), "WHATSAPP_TOKEN cargado")
    id_ok = WHATSAPP_PHONE_NUMBER_ID.isdigit()
    item(id_ok, "WHATSAPP_PHONE_NUMBER_ID es un número" + ("" if id_ok else
         f" (ahora dice '{WHATSAPP_PHONE_NUMBER_ID}': copia el 'Identificador del número de teléfono' de Meta)"))
    tel_ok = TELEFONO_ASESOR.isdigit() and TELEFONO_ASESOR != "584121234567"
    item(tel_ok, "TELEFONO_ASESOR configurado" + ("" if tel_ok else " (sigue el número de ejemplo o está vacío)"))
    item(True, "META_APP_SECRET " + ("configurado: debe ser la 'Clave secreta de la app' exacta" if META_APP_SECRET else "vacío (válido)"))

    if WHATSAPP_TOKEN and id_ok:
        try:
            g = requests.get(
                f"https://graph.facebook.com/{GRAPH_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}",
                params={"fields": "display_phone_number,verified_name"},
                headers={"Authorization": f"Bearer {WHATSAPP_TOKEN}"},
                timeout=15,
            )
            if g.ok:
                d = g.json()
                item(True, f"Meta acepta el token. Número del agente: {d.get('display_phone_number')} ({d.get('verified_name')})")
            else:
                msg = g.json().get("error", {}).get("message", g.text)
                item(False, f"Meta rechazó el token o el ID: {msg}")
        except requests.RequestException as e:
            item(False, f"No se pudo conectar con Meta: {e}")

    try:
        agente.cargar_inventario()
        agente._gemini().models.generate_content(model=agente.GEMINI_MODELO, contents="Responde solo: ok")
        item(True, f"Gemini responde con el modelo {agente.GEMINI_MODELO}")
    except Exception as e:
        item(False, f"Gemini falló: {e}")

    return "<br>".join(r), 200


@app.get("/")
def inicio():
    return "El agente de ventas está funcionando ✅", 200


if __name__ == "__main__":
    puerto = int(os.getenv("PORT", "8000"))
    log.info("Iniciando servidor en puerto %s...", puerto)
    app.run(host="0.0.0.0", port=puerto)
