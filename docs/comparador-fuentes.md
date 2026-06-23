# Comparador de fuentes E14

`src/compare_e14_sources.py` es el piloto v2 para comparar PDFs E14 de varias fuentes sin mezclar evidencias en disco.

## Carpetas locales

Mantenga cada fuente separada:

```text
downloads/E14/claveros/
downloads/E14/delegados/
downloads/E14/transmision/
```

Los PDFs faltantes no se tratan como error. La comparacion solo usa mesas que ya tienen dos fuentes analizadas.

## Flujo piloto

Inicializar tablas v2:

```powershell
python .\src\compare_e14_sources.py init-db
```

Registrar fuentes:

```powershell
python .\src\compare_e14_sources.py discover-source --source claveros
python .\src\compare_e14_sources.py discover-source --source delegados
```

Reutilizar OCR historico de Claveros:

```powershell
python .\src\compare_e14_sources.py sync-existing --source claveros
```

Analizar una muestra de Delegados:

```powershell
python .\src\compare_e14_sources.py analyze-source --source delegados --limit 20 --engine digit-model
```

Para recalibrar una muestra ya procesada y guardar recortes de debug:

```powershell
python .\src\compare_e14_sources.py analyze-source --source delegados --limit 1 --engine digit-model --save-debug --force
```

Comparar fuentes ya analizadas:

```powershell
python .\src\compare_e14_sources.py compare --source-a claveros --source-b delegados --limit 100
python .\src\compare_e14_sources.py report
```

Para una pasada mas lenta con diferencia visual por campo:

```powershell
python .\src\compare_e14_sources.py compare --source-a claveros --source-b delegados --limit 100 --visual
```

Cuando `--visual` encuentra valores numericos distintos pero recortes similares, el hallazgo queda como `ocr_uncertain` para revision o recalibracion del OCR. Si ambos valores coinciden, el score visual queda guardado como dato auxiliar, pero no genera hallazgo por si solo.

## Salidas

Los hallazgos quedan en SQLite (`state/e14.sqlite`) y en CSV bajo:

```text
reports/ocr/source_compare/
```

Los CSV generados son locales y no se suben al repositorio.

## Revision visual

El comparador se revisa desde el mismo servicio local del visor OCR:

```powershell
python .\src\review_inconsistencies.py
```

Abra:

```text
http://127.0.0.1:8010/
```

La pantalla principal trabaja por mesa y muestra una, dos o tres fuentes segun existan PDFs descargados. Permite:

- filtrar por alcance de revision: una fuente, Claveros vs Delegados, Claveros vs Transmision o Delegados vs Transmision;
- marcar revisiones separadas por fuente o comparacion;
- reportar fraude o devolver una mesa a pendiente;
- guardar notas de revision;
- filtrar por campo, estado y tipo de hallazgo;
- ordenar por prioridad, mesa, diferencias firmes, OCR dudoso o faltantes;
- descargar CSV de las mesas visibles.

`/comparaciones` redirige a esta pantalla para evitar dos herramientas separadas.
