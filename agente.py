"""
El "cerebro" del agente: lee el inventario, arma las instrucciones
y le pide a Gemini la respuesta para cada cliente.
"""

import csv
import os
import re
import threading
import time
from pathlib import Path

from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import ServerError

CARPETA = Path(__file__).resolve().parent
load_dotenv(CARPETA / ".env")

ARCHIVO_INVENTARIO = CARPETA / os.getenv("ARCHIVO_INVENTARIO", "inventario.csv")
ARCHIVO_INSTRUCCIONES = CARPETA / "instrucciones_agente.txt"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODELO = os.getenv("GEMINI_MODELO", "gemini-3.8-flash").strip()
GEMINI_MODELO_RESPALDO = os.getenv(
    "GEMINI_MODELO_RESPALDO", "gemini-3.5-flash-lite"
).strip()
GEMINI_API_VERSION = os.getenv("GEMINI_API_VERSION", "").strip()

# Cuántos mensajes recientes recuerda el agente por cliente.
MAX_MENSAJES_MEMORIA = int(os.getenv("MAX_MENSAJES_MEMORIA", "30"))

DATOS_NEGOCIO = {
    "NOMBRE_NEGOCIO": os.getenv("NOMBRE_NEGOCIO", "AutoVentas"),
    "HORARIO": os.getenv("HORARIO", "Lunes a sábado de 8:00 a. m. a 6:00 p. m."),
    "DIRECCION": os.getenv("DIRECCION", "Escriba aquí la dirección del negocio"),
    "MONEDA": os.getenv("MONEDA", "dólares (USD)"),
}

PATRON_ASESOR = re.compile(r"\[PASAR_A_ASESOR:\s*(.*?)\]", re.IGNORECASE | re.DOTALL)

_cliente_gemini = None
_memoria: dict[str, list] = {}
_candado = threading.Lock()


def _gemini() -> genai.Client:
    global _cliente_gemini
    if _cliente_gemini is None:
        if not GEMINI_API_KEY:
            raise RuntimeError(
                f"Falta GEMINI_API_KEY en el archivo {(CARPETA / '.env')}"
            )
        if GEMINI_API_VERSION:
            _cliente_gemini = genai.Client(
                api_key=GEMINI_API_KEY,
                http_options=types.HttpOptions(api_version=GEMINI_API_VERSION),
            )
        else:
            _cliente_gemini = genai.Client(api_key=GEMINI_API_KEY)
    return _cliente_gemini


def cargar_inventario() -> str:
    """Convierte inventario.csv en un texto que Gemini entiende bien.
    Se lee en cada mensaje, así los cambios al archivo se ven al instante."""
    if not ARCHIVO_INVENTARIO.exists():
        return "(No se encontró el archivo inventario.csv por ahora.)"

    with open(ARCHIVO_INVENTARIO, encoding="utf-8-sig", newline="") as f:
        filas = list(csv.DictReader(f))

    if not filas:
        return "(El inventario está vacío por ahora.)"

    lineas = []
    for v in filas:
        km = int(float(v.get("kilometraje") or 0))
        precio = float(v.get("precio") or 0)
        lineas.append(
            f"- [{v.get('codigo', '')}] {v.get('tipo', '')} | "
            f"{v.get('marca', '')} {v.get('modelo', '')} {v.get('anio', '')} | "
            f"{km:,} km | {v.get('transmision', '')} | {v.get('combustible', '')} | "
            f"{v.get('color', '')} | Precio: {precio:,.0f} | "
            f"Estado: {v.get('estado', '')} | {v.get('notas', '')}"
        )
    return "\n".join(lineas)


def armar_instrucciones() -> str:
    if not ARCHIVO_INSTRUCCIONES.exists():
        raise FileNotFoundError(
            f"No se encontró el archivo de instrucciones: {ARCHIVO_INSTRUCCIONES}"
        )
    texto = ARCHIVO_INSTRUCCIONES.read_text(encoding="utf-8")
    datos = {**DATOS_NEGOCIO, "INVENTARIO": cargar_inventario()}
    for clave, valor in datos.items():
        texto = texto.replace("{" + clave + "}", str(valor))
    return texto


def _llamar_modelo(historial: list, instrucciones: str) -> object:
    """Intenta generar contenido con reintentos ante 503 y respaldo de modelo."""
    modelos = [m for m in [GEMINI_MODELO, GEMINI_MODELO_RESPALDO] if m]
    config = types.GenerateContentConfig(
        system_instruction=instrucciones,
        temperature=0.4,
        max_output_tokens=800,
    )
    ultimo_error = None
    for modelo in modelos:
        for intento in range(2):
            try:
                return _gemini().models.generate_content(
                    model=modelo,
                    contents=historial,
                    config=config,
                )
            except ServerError as e:
                ultimo_error = e
                if intento == 0:
                    time.sleep(1.5)
    raise ultimo_error


def responder(id_cliente: str, mensaje: str) -> tuple[str, str | None]:
    """Devuelve (respuesta_para_el_cliente, resumen_para_el_asesor o None)."""
    with _candado:
        historial = list(_memoria.get(id_cliente, []))

    historial.append(types.Content(role="user", parts=[types.Part(text=mensaje)]))
    instrucciones = armar_instrucciones()

    resultado = _llamar_modelo(historial, instrucciones)
    texto = (getattr(resultado, "text", None) or "").strip()
    if not texto:
        texto = "Disculpe, no le entendí bien. ¿Me lo puede repetir, por favor?"

    # Separar el aviso interno para el asesor del mensaje para el cliente.
    resumen_asesor = None
    coincidencia = PATRON_ASESOR.search(texto)
    if coincidencia:
        resumen_asesor = coincidencia.group(1).strip()
        texto = PATRON_ASESOR.sub("", texto).strip()

    historial.append(types.Content(role="model", parts=[types.Part(text=texto)]))
    with _candado:
        _memoria[id_cliente] = historial[-MAX_MENSAJES_MEMORIA:]

    return texto, resumen_asesor


def olvidar(id_cliente: str) -> None:
    with _candado:
        _memoria.pop(id_cliente, None)