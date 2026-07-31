# RyukPowerBi Dashboard

**Plataforma web para visualizar, reconstruir y compartir dashboards de datos — sin instalar Power BI.**

🔗 **Demo en vivo:** [powerbi.ryukplay.dev](https://powerbi.ryukplay.dev/) · Creado por [RyukPlay](https://ryukplay.dev/)

Sube un CSV/Excel y obtén un dashboard automático con KPIs, gráficos y filtros. Sube un **.pbix** y la plataforma lee su modelo de datos, **reconstruye el informe tal como fue diseñado en Power BI** (tarjetas, segmentadores, gráficos) y genera una **URL permanente** para compartirlo — todo desde el navegador.

## ✨ Qué hace

| Modo | Descripción |
|---|---|
| **Subir datos** | CSV/XLSX/XLS → detección automática de 9 tipos de columna (moneda, porcentaje, fecha, booleano, enlace, ID...), panel de revisión, KPIs, gráficos interactivos y filtros. Unifica hojas compatibles con columna de origen. |
| **Conectar Power BI** | Incrusta informes publicados con el enlace o el código `<iframe>`. |
| **Leer .pbix** | Radiografía del informe en el navegador (páginas, visuales, campos, consultas M) + **lectura de los datos del modelo** vía microservicio (el formato XPress9 de Microsoft no es legible en navegador). |
| **Reconstrucción del informe** | Interpreta el `Report/Layout`, cruza las tablas por las **relaciones del modelo**, resuelve **medidas DAX** simples (SUM, DISTINCTCOUNT, COUNTROWS, AVERAGE, CALCULATE) y recrea el dashboard original con segmentadores funcionales. |
| **URLs compartibles** | Cada dashboard/informe se guarda en MongoDB con **huella SHA-256 del archivo**: mismo archivo → misma URL, que se actualiza sin cambiar (deduplicación con upsert). |

## 🏗 Arquitectura

```
┌─────────────────────────┐     HTTPS      ┌──────────────────────────┐
│  Frontend (SPA estática)│ ─────────────► │  Microservicio Python    │
│  GitHub Pages           │                │  (stdlib http.server)    │
│  · HTML/CSS/JS puro     │                │  Render.com              │
│  · Chart.js · SheetJS   │                │  · pbixray (XPress9)     │
│  · JSZip · PapaParse    │                │  · pandas                │
│  · SHA-256 (WebCrypto)  │                └───────────┬──────────────┘
└─────────────────────────┘                            │
        el mismo cliente detecta y usa                 ▼
        un servidor local si está activo    ┌──────────────────────────┐
                                            │  MongoDB Atlas           │
                                            │  dashboards + huellas    │
                                            └──────────────────────────┘
```

**Decisiones de diseño destacables:**

- **API REST sin frameworks**: construida sobre `http.server` de la librería estándar — CORS manual, ruteo propio, JSON, subida de binarios por `Content-Length`. Cero dependencias para servir.
- **Parsing de formatos binarios**: el `.pbix` se abre como ZIP; el Layout viene en JSON UTF-16LE; el `DataMashup` esconde un segundo ZIP (búsqueda de firma `PK\x03\x04` por bytes); los datos del modelo (VertiPaq/XPress9) se descomprimen con `pbixray`.
- **Deduplicación por huella**: SHA-256 del archivo calculado en el cliente (WebCrypto); el servidor hace *upsert* por huella → dashboards únicos con URL estable.
- **Resiliencia**: normalización RFC 3986 automática de credenciales Mongo, TTL y límite de sesiones, tope de tamaño de archivo, degradación elegante (si el servidor no entrega relaciones, el cliente las **infiere por llaves compartidas** entre tablas).
- **Elección de tabla de hechos por relaciones** (lado "muchos"), no por tamaño — evita que una tabla calendario domine el modelo.

## 🔌 API del microservicio

| Método | Ruta | Descripción |
|---|---|---|
| GET | `/salud` | Estado, versión, disponibilidad de pbixray y Mongo |
| POST | `/subir` | Recibe un `.pbix` (binario) → token de sesión, tablas, columnas, relaciones y medidas DAX |
| GET | `/tabla?token&nombre&max` | Filas de una tabla del modelo (JSON, fechas ISO, nulos) |
| POST | `/dashboard` | Guarda un dashboard o informe reconstruido; upsert por `huella` |
| GET | `/dashboard?id` | Recupera un dashboard/informe por id |
| GET | `/dashboard/huella?h` | ¿Existe dashboard para esta huella de archivo? |

## 🚀 Despliegue

**Frontend:** sube `index.html` a GitHub Pages (o cualquier hosting estático).

**Microservicio (Render u otro PaaS):**
```
Build:  pip install -r requirements.txt
Start:  python servidor_pbix.py
```
Variables de entorno: `MONGO_URI` (Atlas), `MONGO_DB`, `MONGO_COLECCION`, `MAX_MB`, `TTL_MIN`. El puerto se toma de `PORT` automáticamente. Fija Python 3.11 con `.python-version` (los wheels de xpress9 no existen para 3.14).

**Uso local (datos privados):** `pip install pbixray pandas "pymongo[srv]"` → `python servidor_pbix.py`. La página detecta el servidor local y lo prioriza: los datos no salen del equipo.

## 🧰 Stack

`Python 3.11` · `http.server (stdlib)` · `pbixray` · `pandas` · `PyMongo` · `MongoDB Atlas` · `JavaScript (vanilla)` · `Chart.js` · `SheetJS` · `PapaParse` · `JSZip` · `WebCrypto` · `Render` · `GitHub Pages`

## 🗺 Roadmap

- Evaluador de DAX ampliado (DIVIDE, medidas anidadas)
- Panel "Mis dashboards" con administración de enlaces
- Exportación del dashboard reconstruido a PDF con diseño

## 👩‍💻 Autora

Desarrollado por **RyukPlay** — desarrolladora backend.
¿Necesitas algo a la medida (integraciones, APIs, automatización de reportes)?
🌐 [ryukplay.dev](https://ryukplay.dev/) · ✉️ ryukdeathnotetv@gmail.com
