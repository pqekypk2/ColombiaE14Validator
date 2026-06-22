# Herramientas OCR E14 Presidenciales

Repositorio local para analizar formularios E14 en PDF, entrenar un modelo de lectura de digitos manuscritos y revisar inconsistencias en una interfaz web local.

Este repositorio esta preparado para publicar solo el codigo y la configuracion necesaria. No incluye datos generados durante el trabajo.

## Componentes

- Analizador OCR: lee PDFs E14 desde disco, extrae campos, valida totales y genera reportes de inconsistencias.
- Etiquetador y entrenamiento: crea recortes OCR, permite etiquetarlos en una pagina local y entrena un modelo de digitos.
- Visualizador de inconsistencias: abre una pagina local para revisar registro por registro, ver el PDF al lado y marcar revisiones o fraude.

La documentacion detallada esta en:

- [Analizador OCR](docs/analizador-ocr.md)
- [Etiquetador y entrenamiento](docs/etiquetador-entrenamiento.md)
- [Visualizador de inconsistencias](docs/visualizador-inconsistencias.md)

## Licencia y contribuciones

Este proyecto se publica bajo la licencia [Apache-2.0](LICENSE). Puede usarlo, copiarlo, modificarlo y redistribuirlo conservando la licencia y la atribucion correspondiente indicada en [NOTICE](NOTICE).

Para contribuir, revise [CONTRIBUTING.md](CONTRIBUTING.md). Los cambios publicos se registran en [CHANGELOG.md](CHANGELOG.md). La version actual esta en [VERSION](VERSION).

## No se sube a GitHub

Por tamano, privacidad y reproducibilidad, estos elementos quedan ignorados por Git:

- PDFs E14 y cualquier descarga local: `downloads/`, `*.pdf`.
- Base SQLite y estado local: `state/`, `*.sqlite`, `*.sqlite-shm`, `*.sqlite-wal`.
- Reportes generados: `reports/`, `*.csv`.
- Imagenes, recortes y debug visual: `*.png`, `*.jpg`, `*.jpeg`, `*.tif`, `*.tiff`, etc.
- Modelos entrenados y checkpoints: `*.pt`, `*.pth`, `*.onnx`, `*.ckpt`.
- Logs y temporales: `logs/`, `*.log`, `*.lock`.
- Datos auxiliares locales: `data/`, `config.json`.

El archivo `config/e14_rois.json` si se conserva porque define las regiones de lectura del formulario y es parte del codigo reproducible.

## Requisitos

- Python 3.11 o superior.
- Windows, Linux o macOS. El flujo se ha usado principalmente en Windows.
- Dependencias de `requirements.txt`.
- PDFs E14 ya disponibles en disco, por defecto en `downloads/E14/`.

Puede descargar un paquete de E14 desde:

```text
https://fff.re/20260622-E14-CL
```

Instalacion:

```powershell
python -m pip install -r requirements.txt
```

## Flujo rapido

1. Coloque los PDFs localmente, por ejemplo en `downloads/E14/`.
2. Inicialice la base local:

```powershell
python .\src\analyze_e14.py init-db
```

3. Descubra PDFs desde disco:

```powershell
python .\src\analyze_e14.py discover --root .\downloads\E14
```

4. Genere recortes de entrenamiento:

```powershell
python .\src\analyze_e14.py crops --limit 200 --include-pages
```

5. Etiquete recortes:

```powershell
python .\src\label_crops.py
```

6. Entrene el modelo:

```powershell
python -u .\src\train_e14_digit_model.py --epochs 25 --augment-multiplier 5 --device cpu
```

7. Analice PDFs y genere reportes:

```powershell
python .\src\analyze_e14.py analyze --engine digit-model --workers 2 --limit 100 --save-debug
python .\src\analyze_e14.py report
```

8. Revise inconsistencias:

```powershell
python .\src\review_inconsistencies.py
```

## Estructura esperada

```text
config/
  e14_rois.json
docs/
  analizador-ocr.md
  etiquetador-entrenamiento.md
  visualizador-inconsistencias.md
src/
  analyze_e14.py
  label_crops.py
  train_e14_digit_model.py
  review_inconsistencies.py
requirements.txt
README.md
```

Carpetas generadas localmente y no versionadas:

```text
downloads/
reports/
state/
logs/
data/
```

## Preparacion antes de publicar

Antes de crear el repositorio remoto, revise que no se incluyan datos:

```powershell
git status --ignored
```

Si se inicializa Git desde cero, agregue solo el codigo y documentacion:

```powershell
git init
git add README.md requirements.txt .gitignore config src docs
git status
```

Revise que no aparezcan PDFs, bases SQLite, imagenes, CSVs, modelos entrenados ni logs en la lista de archivos a subir.
