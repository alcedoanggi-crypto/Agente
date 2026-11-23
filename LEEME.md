# Agente de ventas de vehículos por WhatsApp (con Gemini)

Este agente atiende a tus clientes por WhatsApp las 24 horas: muestra los vehículos y sus precios, recibe ofertas de carros para vender o dar como parte de pago, y te avisa por WhatsApp cuando un cliente está listo para cerrar.

## Qué hay en la carpeta

| Archivo | Para qué sirve | ¿Lo editas? |
|---|---|---|
| `inventario.csv` | Tu lista de vehículos y precios. Se abre con Excel. | **Sí, siempre que cambie el inventario** |
| `instrucciones_agente.txt` | La personalidad y las reglas del agente. | Sí, si quieres cambiar cómo habla |
| `.env.example` | Plantilla para tus claves y datos del negocio. | Cópialo como `.env` y llénalo |
| `agente.py` | El "cerebro": conecta con Gemini. | No |
| `app.py` | Conecta WhatsApp con el agente. | No |
| `probar_chat.py` | Para probar el agente sin WhatsApp. | No |

---

## Paso 1: Consigue tu clave de Gemini (gratis para empezar)

1. Entra en https://aistudio.google.com/apikey con tu cuenta de Google.
2. Pulsa **Create API key** (Crear clave de API).
3. Copia la clave. La pegarás en el archivo `.env`.

## Paso 2: Prueba el agente en tu computadora

Necesitas tener instalado Python 3.10 o más reciente (https://www.python.org/downloads/).

1. Abre una terminal en esta carpeta.
2. Instala las librerías:
   ```
   pip install -r requirements.txt
   ```
3. Copia `.env.example` con el nombre `.env` y pega tu `GEMINI_API_KEY`. Llena también el nombre, horario y dirección de tu negocio.
4. Ejecuta:
   ```
   python probar_chat.py
   ```
5. Escríbele como si fueras un cliente: "Buenas tardes, ¿qué vehículos tienen?".

Si te gusta cómo responde, sigue con WhatsApp. Si no, ajusta `instrucciones_agente.txt` y prueba otra vez.

## Paso 3: Prepara WhatsApp Business (API oficial de Meta)

1. Entra en https://developers.facebook.com y crea una app de tipo **Empresa (Business)**.
2. Agrega el producto **WhatsApp**.
3. En **WhatsApp > Configuración de la API** copia:
   - el **Token de acceso** → `WHATSAPP_TOKEN`
   - el **Identificador del número de teléfono** → `WHATSAPP_PHONE_NUMBER_ID`
4. Meta te da un número de prueba. Cuando todo funcione, agrega tu número real del negocio.
   - El número que uses con la API **no puede estar a la vez en la app normal de WhatsApp** en el celular.
5. El token de prueba vence en 24 horas. Para uno permanente: **Configuración del negocio > Usuarios del sistema**, crea un usuario del sistema y genera un token con los permisos `whatsapp_business_messaging` y `whatsapp_business_management`.

## Paso 4: Publica el agente en internet

WhatsApp necesita una dirección web para enviarle los mensajes. Las opciones más fáciles son **Render** (https://render.com) o **Railway** (https://railway.app):

1. Sube esta carpeta a un repositorio de GitHub (**sin** el archivo `.env`).
2. En Render, crea un **Web Service** desde ese repositorio.
   - Comando de instalación: `pip install -r requirements.txt`
   - Comando de inicio: `gunicorn app:app --workers 1 --threads 8 --bind 0.0.0.0:$PORT`
3. En **Environment**, agrega una por una las variables de tu `.env`.
4. Al terminar te dará una dirección como `https://mi-agente.onrender.com`. Ábrela y debe decir "El agente de ventas está funcionando ✅".

> Usa `--workers 1`: el agente recuerda las conversaciones en la memoria de ese único proceso.
> El plan gratuito de Render se "duerme" si no recibe visitas, y el primer mensaje tarda unos segundos. Para un negocio real conviene el plan pagado más básico.

## Paso 5: Conecta el webhook

1. En Meta, ve a **WhatsApp > Configuración** y, en **Webhook**, pulsa **Editar**.
2. **URL de devolución de llamada:** `https://mi-agente.onrender.com/webhook`
3. **Token de verificación:** la misma palabra que pusiste en `WEBHOOK_VERIFY_TOKEN`.
4. Pulsa **Verificar y guardar**.
5. En **Campos del webhook**, suscríbete a **messages**.

¡Listo! Escríbele al número desde otro WhatsApp y el agente responderá.

---

## Cómo funciona el aviso al asesor

Cuando un cliente quiere agendar una prueba de manejo, negociar, cerrar la compra o vender su carro, el agente le dice que un asesor lo contactará. Al mismo tiempo le llega a `TELEFONO_ASESOR` un mensaje así:

```
🔔 Cliente para atender
Nombre: Carlos
Teléfono: +584141234567
Qué quiere: Quiere probar la Toyota RAV4 2020 el sábado a las 10 a. m.
Escríbale aquí: https://wa.me/584141234567
```

**Importante:** WhatsApp solo deja que el sistema le escriba a un número si esa persona le escribió en las últimas 24 horas. Para que el asesor reciba siempre los avisos, el asesor debe escribirle "hola" al número del agente una vez al día, o puedes crear una plantilla de mensaje aprobada por Meta.

## Para actualizar el inventario

Abre `inventario.csv` con Excel y guárdalo como **CSV UTF-8**.
- En la columna `estado` usa: `Disponible`, `Reservado` o `Vendido`. Solo se ofrecen los disponibles.
- En `precio` y `kilometraje` escribe solo números, sin puntos, comas ni símbolos.

Si el agente está en Render, sube el archivo actualizado a GitHub y Render se actualiza solo.

## Costos aproximados

- **Gemini:** tiene un nivel gratuito para pruebas. Con uso real, un modelo Flash suele costar centavos por cada cien conversaciones.
- **WhatsApp:** responder a un cliente que te escribió primero es gratis dentro de las 24 horas. Los mensajes que inicia el negocio con plantillas sí tienen costo según el país.
- **Servidor:** Render y Railway tienen planes desde unos 5 a 7 dólares al mes.

Revisa los precios actuales en la página de cada servicio, porque cambian con frecuencia.

## Problemas comunes

- **El webhook no se verifica:** revisa que la palabra en Meta sea exactamente igual a `WEBHOOK_VERIFY_TOKEN` y que la dirección termine en `/webhook`.
- **El agente no responde:** mira los registros (Logs) en Render. Si dice error 401, el token de WhatsApp venció.
- **Error con el modelo de Gemini:** cambia `GEMINI_MODELO` por otro modelo de la lista de https://ai.google.dev/gemini-api/docs/models.
- **El agente olvidó la conversación:** las conversaciones se borran si el servidor se reinicia. Es normal en esta versión.
