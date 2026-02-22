# Guía de Configuración - Agente de Correo Electrónico

## 1. Instalar dependencias

```bash
cd email-agent
pip install -r requirements.txt
```

---

## 2. Configurar Gmail

### Crear proyecto en Google Cloud Console

1. Ve a [Google Cloud Console](https://console.cloud.google.com/)
2. Crea un nuevo proyecto (o usa uno existente)
3. Ve a **APIs y servicios** > **Biblioteca**
4. Busca y habilita **Gmail API**
5. Ve a **APIs y servicios** > **Pantalla de consentimiento de OAuth**
   - Tipo de usuario: **Externo**
   - Llena los datos básicos (nombre de app, email)
   - En "Alcances", agrega: `https://www.googleapis.com/auth/gmail.readonly`
   - En "Usuarios de prueba", agrega tu email de Gmail
6. Ve a **APIs y servicios** > **Credenciales**
   - Clic en **Crear credenciales** > **ID de cliente de OAuth**
   - Tipo de aplicación: **Aplicación de escritorio**
   - Descarga el JSON y guárdalo como `gmail_credentials.json` en la carpeta `email-agent/`

### Resultado esperado
```
email-agent/
└── gmail_credentials.json    <-- Este archivo
```

---

## 3. Configurar Outlook / Hotmail

### Registrar aplicación en Azure AD

1. Ve a [Azure Portal - Registro de aplicaciones](https://portal.azure.com/#blade/Microsoft_AAD_RegisteredApps/ApplicationsListBlade)
2. Clic en **Nuevo registro**
   - Nombre: `Email Agent` (o el que prefieras)
   - Tipos de cuenta compatibles: **Cuentas en cualquier directorio organizativo y cuentas Microsoft personales**
   - URI de redirección: déjalo vacío (usamos device code flow)
3. Una vez creada la app, anota:
   - **Id. de aplicación (cliente)** → Este es tu `OUTLOOK_CLIENT_ID`
4. Ve a **Autenticación**:
   - En "Configuración avanzada", activa **Permitir flujos de clientes públicos** → **Sí**
   - Guarda los cambios
5. Ve a **Permisos de API**:
   - Clic en **Agregar un permiso** > **Microsoft Graph** > **Permisos delegados**
   - Busca y selecciona: `Mail.Read`
   - Clic en **Agregar permisos**

### Resultado
Necesitas el **Client ID** que obtuviste en el paso 3.

---

## 4. Configurar API de OpenAI

1. Ve a [OpenAI Platform](https://platform.openai.com/api-keys)
2. Crea una nueva API key si no tienes una
3. Copia la key

---

## 5. Crear archivo .env

Crea un archivo `.env` en la carpeta `email-agent/` con este contenido:

```env
# OpenAI
OPENAI_API_KEY=sk-tu-api-key-aqui

# Outlook / Hotmail
OUTLOOK_CLIENT_ID=tu-client-id-de-azure-aqui

# Opcional: para cuentas organizativas (por defecto es "consumers" para Hotmail/Outlook personal)
# OUTLOOK_TENANT_ID=consumers
```

---

## 6. Ejecutar

```bash
cd email-agent
python email_agent.py
```

### Primera ejecución
- **Gmail**: Se abrirá una ventana del navegador para autorizar acceso. Después de autorizar, el token se guarda automáticamente.
- **Outlook**: Se mostrará un código en la terminal. Abre el enlace indicado e ingresa el código para autorizar.
- Los tokens se guardan localmente para que no tengas que re-autorizar cada vez.

---

## Notas de seguridad

- Los archivos `gmail_token.json`, `outlook_token_cache.json` y `.env` contienen credenciales sensibles. No los compartas ni los subas a repositorios públicos.
- La aplicación solo tiene permiso de **lectura** de correos. No puede enviar, modificar ni eliminar correos.
- Las respuestas generadas son **borradores** que tú decides si envías manualmente.
