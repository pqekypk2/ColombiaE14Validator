# Etiquetador y entrenamiento

Este flujo permite crear etiquetas humanas para recortes OCR y entrenar un modelo local de digitos manuscritos.

## Archivos principales

- `src/label_crops.py`: servidor local para etiquetar recortes.
- `src/train_e14_digit_model.py`: entrenamiento del modelo de digitos.
- `reports/ocr/labeling/manifest.csv`: manifiesto generado por `analyze_e14.py crops`.
- `reports/ocr/labeling/labels.csv`: etiquetas guardadas por el etiquetador.
- `reports/ocr/model/digit_cnn.pt`: modelo entrenado.

Todo lo que esta dentro de `reports/` es generado localmente y no se sube a GitHub.

## Generar recortes

Desde el analizador:

```powershell
python .\src\analyze_e14.py crops --limit 200 --include-pages
```

Para enfocar el entrenamiento en casos dificiles:

```powershell
python .\src\analyze_e14.py crops --status inconsistent --limit 200 --include-pages
```

## Etiquetar

Iniciar el etiquetador:

```powershell
python .\src\label_crops.py
```

Por defecto abre una pagina local en:

```text
http://127.0.0.1:8000/
```

Opciones utiles:

```powershell
python .\src\label_crops.py --manifest .\reports\ocr\labeling\manifest.csv --labels .\reports\ocr\labeling\labels.csv
python .\src\label_crops.py --host 0.0.0.0 --port 8000 --no-open
```

## Entrenar

Entrenamiento recomendado en CPU:

```powershell
python -u .\src\train_e14_digit_model.py --epochs 25 --augment-multiplier 5 --device cpu
```

Con CUDA, si PyTorch y la GPU estan disponibles:

```powershell
python -u .\src\train_e14_digit_model.py --epochs 25 --augment-multiplier 5 --device cuda
```

Salidas locales:

- `reports/ocr/model/digit_cnn.pt`
- `reports/ocr/model/metrics.json`
- `reports/ocr/model/validation_predictions.csv`

No se versionan porque son artefactos generados.

## Usar el modelo entrenado

Verificar disponibilidad:

```powershell
python .\src\analyze_e14.py doctor --engine digit-model
```

Analizar con el modelo:

```powershell
python .\src\analyze_e14.py analyze --engine digit-model --workers 2 --limit 100
```

Si hay un proceso `run --watch` activo, reinicielo despues de entrenar para que cargue el nuevo modelo.

## Buenas practicas

- Etiquete primero muestras pequenas y revise resultados antes de entrenar tandas largas.
- Priorice recortes de documentos inconsistentes cuando busque mejorar precision.
- No suba recortes ni etiquetas reales si contienen datos sensibles o material pesado.
- No suba modelos entrenados salvo que haya una decision explicita de publicarlos.
