# Contribuir

Gracias por interesarte en ColombiaE14Validator. El objetivo del proyecto es que cualquier persona pueda reproducir el analisis en su propio equipo y aportar a la validacion y transparencia de los resultados.

## Que contribuciones sirven

- Mejoras al OCR y a las reglas de consistencia.
- Correcciones de bugs.
- Mejoras de documentacion y reproducibilidad.
- Pruebas en distintos sistemas operativos.
- Reportes claros de falsos positivos o falsos negativos.
- Ideas para publicar datasets de entrenamiento sin cargar archivos pesados al repositorio principal.

## Que no debe subirse

No incluyas datos generados, documentos oficiales descargados ni archivos pesados en pull requests:

- PDFs E14.
- Imagenes, recortes OCR o capturas.
- CSVs generados.
- Bases SQLite.
- Modelos entrenados o checkpoints.
- Logs.
- Carpetas `downloads/`, `reports/`, `state/`, `logs/` o `data/`.

Si quieres compartir datos de entrenamiento, abre un issue proponiendo el enlace externo o el mecanismo de publicacion. La opcion recomendada es un release separado, Hugging Face, Kaggle u otro almacenamiento de datasets, con licencia y atribucion claras.

## Flujo recomendado

1. Crea un fork del repositorio.
2. Crea una rama descriptiva:

```powershell
git checkout -b fix/descripcion-corta
```

3. Haz cambios pequenos y revisables.
4. Ejecuta una verificacion minima:

```powershell
python -m py_compile .\src\analyze_e14.py .\src\label_crops.py .\src\train_e14_digit_model.py .\src\review_inconsistencies.py
```

5. Revisa que no estes agregando datos locales:

```powershell
git status --short --ignored
```

6. Si el cambio afecta comportamiento publico, actualiza `CHANGELOG.md`.
7. Abre un pull request explicando:
   - Que cambia.
   - Como lo probaste.
   - Que archivos o datos locales usaste, sin subirlos.

## Reportar problemas

Cuando abras un issue, incluye:

- Sistema operativo y version de Python.
- Comando ejecutado.
- Error completo o salida relevante.
- Pasos para reproducir.
- Si aplica, una descripcion del tipo de formulario o inconsistencia, sin adjuntar datos sensibles o archivos pesados.

## Licencia de contribuciones

Al enviar una contribucion aceptas que se publique bajo la licencia Apache-2.0 del proyecto.

## Cuidado con interpretaciones electorales

Este proyecto ayuda a detectar inconsistencias para revision humana. Evita presentar resultados automatizados como prueba final de fraude sin verificacion manual, contexto y evidencia reproducible.
