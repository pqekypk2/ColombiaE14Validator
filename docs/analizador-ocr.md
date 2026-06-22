# Analizador OCR

`src/analyze_e14.py` procesa PDFs E14 ya presentes en disco, extrae campos numericos, valida reglas de consistencia y genera reportes CSV para revision.

## Entradas locales

- PDFs E14 en `downloads/E14/` o en la ruta indicada con `--root`.
- Configuracion de regiones OCR en `config/e14_rois.json`.
- Modelo entrenado opcional en `reports/ocr/model/digit_cnn.pt`.

Estas entradas son locales. Los PDFs, la base SQLite y los reportes no se suben al repositorio.

## Base local

El analizador usa SQLite como estado de trabajo en `state/e14.sqlite`. Esa base se crea localmente y esta ignorada por Git.

Inicializar:

```powershell
python .\src\analyze_e14.py init-db
```

Registrar PDFs desde disco:

```powershell
python .\src\analyze_e14.py discover --root .\downloads\E14
```

Si necesita detectar cambios exactos de archivo:

```powershell
python .\src\analyze_e14.py discover --root .\downloads\E14 --hash-files
```

## Verificacion de entorno

Para usar el modelo local:

```powershell
python .\src\analyze_e14.py doctor --engine digit-model
```

Tesseract existe como opcion experimental, pero el flujo recomendado es `digit-model`.

## Analisis

Analizar una muestra:

```powershell
python .\src\analyze_e14.py analyze --engine digit-model --workers 2 --limit 100
```

Guardar imagenes de depuracion:

```powershell
python .\src\analyze_e14.py analyze --engine digit-model --workers 2 --limit 100 --save-debug
```

Ejecutar en modo continuo:

```powershell
python .\src\analyze_e14.py run --engine digit-model --workers 2 --watch --discover-every 30
```

Filtrar por departamento:

```powershell
python .\src\analyze_e14.py analyze --engine digit-model --department-code 01 --workers 2
```

## Reportes generados

Generar CSVs de salida:

```powershell
python .\src\analyze_e14.py report
```

Salidas principales en `reports/ocr/`:

- `resumen.csv`
- `campos.csv`
- `inconsistencias.csv`
- `pendientes.csv`
- `fallidos.csv`

Estas salidas son artefactos generados y estan ignoradas por Git.

## Recortes para entrenamiento

Generar recortes de campos OCR:

```powershell
python .\src\analyze_e14.py crops --limit 200 --include-pages
```

Generar recortes desde documentos inconsistentes:

```powershell
python .\src\analyze_e14.py crops --status inconsistent --limit 200 --include-pages
```

Los recortes e imagenes de depuracion quedan en `reports/ocr/` y no se versionan.

## Reprocesamiento

Reencolar documentos inconsistentes:

```powershell
python .\src\analyze_e14.py requeue --status inconsistent --limit 500 --reset-attempts
```

Borrar resultados OCR locales:

```powershell
python .\src\analyze_e14.py reset-analysis --yes
```

## Reglas de consistencia

El analizador valida, entre otros casos:

- Suma de candidatos, blancos, nulos y no marcados contra suma total.
- Total urna contra E-11.
- Campos faltantes.
- Votos incinerados no cero.
- Baja confianza del modelo.
- Conteo de firmas de jurados menor a 2.
- Valores de votos por encima del umbral `max_reasonable_votes` definido en `config/e14_rois.json`.
