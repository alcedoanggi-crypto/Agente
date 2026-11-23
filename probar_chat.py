"""
Prueba el agente en tu computadora, sin WhatsApp.
Escribe como si fueras un cliente. Escribe "salir" para terminar
o "reiniciar" para empezar una conversación nueva.
"""

import agente

print("Chat de prueba con el agente (escribe 'salir' para terminar)\n")
ID_PRUEBA = "cliente-de-prueba"

while True:
    try:
        mensaje = input("Tú: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not mensaje:
        continue
    if mensaje.lower() == "salir":
        break
    if mensaje.lower() == "reiniciar":
        agente.olvidar(ID_PRUEBA)
        print("(Conversación reiniciada)\n")
        continue

    respuesta, resumen_asesor = agente.responder(ID_PRUEBA, mensaje)
    print(f"\nAgente: {respuesta}\n")
    if resumen_asesor:
        print(f"   >> Aviso que le llegaría al asesor: {resumen_asesor}\n")
