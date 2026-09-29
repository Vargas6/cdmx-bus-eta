# CDMX Bus ETA

Proyecto integrador de Ciencia de Datos: análisis de transporte público de la Ciudad de México a partir de fuentes oficiales (GTFS estático SEMOVI/ADIP y API GTFS de Metrobús). El alcance de cualquier estimación de llegada (ETA) se define **después** de inspeccionar los datos reales; no se asumen variables ni se inventan predicciones.

## Estado

Estructura inicial del repositorio. Pendiente: incorporar el ZIP GTFS estático, inspeccionar tablas disponibles y probar autenticación contra la API de Metrobús.

## Estructura

| Ruta | Uso |
| --- | --- |
| `api/` | Backend FastAPI (aún no implementado) |
| `data/raw/` | Entradas oficiales sin procesar (no versionadas) |
| `data/processed/` | Salidas del pipeline (no versionadas) |
| `data-pipeline/` | Ingesta y limpieza con Python/Pandas |
| `notebooks/` | EDA y exploración |
| `web/` | Frontend React (aún no implementado) |
| `docs/` | Notas de metodología y defensa |

## Datos

- GTFS estático oficial (ZIP local; colocar en `data/raw/` sin subirlo a Git).
- API GTFS de Metrobús (acceso autorizado; credenciales solo en variables de entorno).

No se usan conjuntos de Kaggle ni fuentes no oficiales.

## Secretos

Copiar `.env.example` a `.env` y completar valores. `.env` está en `.gitignore`. Las credenciales no deben aparecer en código, README ni historial de Git.

## Requisitos previstos

Python (Pandas), FastAPI, React, GitHub, despliegue del frontend en Vercel. OpenAI se usará como capa explicativa sobre resultados ya calculados, no como fuente de ETA.
