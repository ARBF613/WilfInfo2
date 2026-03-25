# 🌿 WildInfo: Enciclopedia Digital de Fauna

WildInfo es una **SPA (Single Page Application)** moderna que consulta datos biológicos en tiempo real desde APIs externas y permite a los usuarios **buscar animales** y **coleccionar favoritos** en un catálogo local.

La aplicación se conecta con un backend en **FastAPI** que actúa como puente entre:
- API-Ninjas (datos taxonómicos)
- Unsplash (imágenes)
- SQLite + SQLAlchemy (persistencia de favoritos)

## 🚀 Características Principales

- Integración con **API-Ninjas** para obtener datos taxonómicos.
- Búsqueda visual con imágenes desde **Unsplash**.
- Persistencia local mediante **SQLite** y **SQLAlchemy** para guardar favoritos.
- Interfaz moderna con **Tailwind CSS**.
- **Modo Noche** (Selva) con toggle persistente.
- Barra de **Progreso / Nivel de Explorador** según especies guardadas.
- Animaciones suaves y feedback visual para una mejor experiencia.

## 🛠️ Tecnologías Usadas

- **FastAPI** (backend)
- **Python 3.12**
- **SQLite** (base de datos local)
- **SQLAlchemy** (ORM)
- **Tailwind CSS** (frontend vía CDN)
- **JavaScript** (Fetch API)

## 💻 Instrucciones de Instalación

1. Crear entorno virtual:
   ```powershell
   python -m venv animal
   ```
2. Activar entorno (Windows):
   ```powershell
   .\animal\Scripts\activate
   ```
3. Instalar dependencias:
   ```powershell
   pip install fastapi uvicorn httpx python-dotenv sqlalchemy
   ```
4. Configurar el archivo `.env` en la raíz del proyecto:
   - `NINJAS_API_KEY=TU_API_KEY`
   - `UNSPLASH_ACCESS_KEY=TU_API_KEY`

> Nota: deja los valores correctos en `.env` para que la búsqueda funcione con ambas APIs.

## 🏃 Cómo Ejecutar

Arranca el backend con recarga automática:

```powershell
python -m uvicorn main:app --reload
```

Abre la aplicación en:
- `http://localhost:8000/`

