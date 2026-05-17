# WildInfo — Enciclopedia de Fauna

SPA con **FastAPI** + **SQLite** + frontend estático (**nginx** / Tailwind compilado). Consulta **API Ninjas** y **Unsplash**; guarda favoritos y usuarios en base de datos persistente.

## Tecnologías

| Capa | Stack |
|------|--------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, SQLite, httpx |
| Frontend | HTML, JavaScript, Tailwind CSS (build local) |
| Despliegue | Docker, Docker Compose, nginx |
| Calidad | SonarQube, Lighthouse (manual) |

## Estructura del proyecto

```
WilfInfo2/
├── backend/          # API FastAPI + wildinfo2.db (volumen Docker)
├── frontend/         # index.html, Tailwind, Dockerfile nginx
├── docker-compose.yml
├── .env.example
└── sonar-project.properties
```

## Variables de entorno

Copia `.env.example` → `.env` y completa:

| Variable | Uso |
|----------|-----|
| `NINJA_API_KEY` o `NINJAS_API_KEY` | API Ninjas (animales) |
| `UNSPLASH_ACCESS_KEY` | Imágenes |
| `API_SECRET_KEY` | Protección de escritura (`X-API-KEY`) |
| `ORIGEN_PERMITIDO` | CORS: URL del frontend en producción |

En el navegador (una vez), con el mismo valor que `API_SECRET_KEY`:

```javascript
localStorage.setItem("wildinfo_api_key", "TU_MISMA_CLAVE_DEL_ENV");
```

## Ejecución local con Docker (recomendado)

```powershell
docker compose up -d --build backend frontend
```

- **Frontend:** http://localhost:8080  
- **API (directa):** http://localhost:8000/status  
- **API vía proxy (mismo origen):** http://localhost:8080/api/status  

La base `backend/wildinfo2.db` persiste en disco gracias al volumen de `docker-compose.yml`.

## Ejecución sin Docker (desarrollo)

```powershell
python -m venv animal
.\animal\Scripts\activate
pip install -r requirements.txt
# .env configurado
python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Abre http://localhost:8000/ (backend sirve la SPA).

Con **Live Server** en `frontend/`, deja vacío `wildinfo-api-base` y usa `wildinfo-backend-port` = `8000`.

## Despliegue en Railway (recomendado)

Un **solo servicio** con `backend/Dockerfile`: sirve la SPA en `/` y la API en las mismas rutas (`/animal`, `/favorites`, etc.). HTTPS lo gestiona Railway.

### 1. Preparar el repo

1. Sube el proyecto a **GitHub** (sin `.env`).
2. Asegúrate de que existe `frontend/tailwind.css` (generado con `npm run build:css` en `frontend/` o con el build Docker del frontend local).

### 2. Crear proyecto en Railway

1. Entra en [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**.
2. Elige el repositorio `WilfInfo2`.
3. Railway detecta `railway.toml` (Dockerfile en `backend/Dockerfile`, healthcheck `/status`).

### 3. Variables de entorno (pestaña Variables)

| Variable | Valor |
|----------|--------|
| `NINJA_API_KEY` | tu clave API Ninjas |
| `UNSPLASH_ACCESS_KEY` | tu clave Unsplash |
| `API_SECRET_KEY` | una clave larga que inventes (solo servidor + navegador) |
| `ORIGEN_PERMITIDO` | la URL pública de Railway, ej. `https://wildinfo-production.up.railway.app` |
| `HOST` | `0.0.0.0` |

`PORT` lo asigna Railway automáticamente; no hace falta definirlo.

### 4. Volumen para la base de datos (persistencia)

1. En el servicio → **Volumes** → **Add Volume**.
2. Montaje: **`/app/data`** (solo la base de datos; **no** uses `/app/backend` o borrarás el código Python del contenedor).
3. Variable opcional en Railway: `WILDINFO_DATA_DIR=/app/data`
4. Redeploy del servicio.

Sin volumen, los favoritos se pierden al redeploy.

### 5. Dominio público

1. **Settings** → **Networking** → **Generate Domain**.
2. Copia la URL `https://....up.railway.app`.
3. Actualiza `ORIGEN_PERMITIDO` con esa URL exacta (sin barra final) y redeploy si cambiaste CORS.

### 6. Probar en producción

- Abre `https://TU-DOMINIO.up.railway.app/`
- `https://TU-DOMINIO.up.railway.app/status` → JSON “Servidor Arriba”
- En el navegador (consola F12), una sola vez:

```javascript
localStorage.setItem("wildinfo_api_key", "LA_MISMA_API_SECRET_KEY_DEL_PANEL");
```

- Busca un animal y guarda un favorito.
- Prueba la misma URL desde el móvil (otra red) para la rúbrica.

### 7. Entrega al profesor

Pon la URL HTTPS en el README (sección “URL del sistema”) y en la presentación.

### Local vs Railway

| Entorno | URL típica |
|---------|------------|
| Docker Compose | http://localhost:8080 (nginx + `/api`) |
| Railway | https://xxx.up.railway.app (todo en un servicio) |

## SonarQube

Con SonarQube en marcha (`docker compose up -d sonarqube`):

```powershell
pip install pysonar
pysonar --sonar-host-url=http://localhost:9000 --sonar-token=TU_TOKEN --sonar-project-key=wilfinfo2
```

Revisa en http://localhost:9000 que no queden **vulnerabilidades** abiertas (p. ej. CDN sin SRI, ya corregido con Tailwind local).

## Pruebas funcionales (checklist)

- Buscar animal válido / inválido → mensajes sin romper la UI.
- Guardar favorito con `API_SECRET_KEY` configurada.
- Login / registro / panel admin (rol admin).
- Reiniciar contenedores → los favoritos siguen en `wildinfo2.db`.

Script auxiliar: `backend/scripts/manual_search_test.py`.

## Lighthouse

En Chrome: DevTools → **Lighthouse** → analizar http://localhost:8080 (o URL de producción). Captura pantalla de Performance, Accesibilidad y Buenas prácticas para la presentación.

## URL del sistema

| Entorno | URL |
|---------|-----|
| Local Docker | http://localhost:8080 |
| Railway | *(completar tras Generate Domain)* https://xxx.up.railway.app |

## Presentación sugerida

- Arquitectura: frontend nginx + API FastAPI + SQLite + APIs externas.
- Despliegue: Docker Compose local; cloud con HTTPS y variables en panel.
- Problemas: CORS, seguridad CDN/SRI, persistencia DB.
- Soluciones: proxy `/api`, Tailwind compilado, volumen Docker, `.env` y Sonar.
