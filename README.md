# Building Tiles Generator

Genera imágenes recortadas por edificio y año a partir de geometrías catastrales y ortofotos históricas del ICGC.

Los edificios pueden proceder de Catastro ATOM, de un archivo local o de un GeoPackage de *ground truth*. Los resultados se guardan en `outputs/<LOCALIDAD>/<AÑO>`.

## Instalación

```powershell
conda env create -f environment.yml
conda activate geo
```

Para actualizar el entorno:

```powershell
conda env update -f environment.yml --prune
```

## Uso rápido

Ejecuta el comando desde la raíz del proyecto y con el entorno `geo` activado:

```powershell
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --cadastre-source atom --max-workers 1
```

Para probar el flujo con solo 10 edificios:

```powershell
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --cadastre-source atom --max-workers 1 --limit 10
```

`--max-workers` indica cuántos años se procesan simultáneamente. Los edificios de cada año se solicitan de forma secuencial para no sobrecargar el WMS.

## Recorte y contexto

Por defecto, los píxeles situados fuera del edificio se muestran en blanco. Para conservar la imagen rectangular completa utiliza `--include-context`:

```powershell
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --limit 10 --include-context
```

La caja se calcula directamente con los puntos extremos de la geometría: `minX`, `minY`, `maxX` y `maxY`. Contiene el edificio completo, sin añadir un porcentaje de margen y sin pintar de blanco los píxeles exteriores a su forma. El centro de esa caja se mantiene como centro del recorte.

`--margin` se aplica al modo normal con fondo blanco. Estas opciones solo cambian la imagen PNG; la selección de edificios, su geometría y los índices generados no cambian.

## Geometrías multipartes

Una entidad catastral puede contener varios polígonos separados. Por defecto, cada componente genera su propia imagen y se centra individualmente.

Con `--keep-multipart-buildings`, todas las partes de la entidad se mantienen juntas y se genera una única imagen cuya caja contiene el conjunto completo:

```powershell
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --limit 10 --keep-multipart-buildings
```

Puede combinarse con `--include-context` para conservar todos los píxeles de la caja que rodea al conjunto:

```powershell
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --limit 10 --keep-multipart-buildings --include-context
```

## Logs y depuración

Cada ejecución muestra el progreso en consola y escribe el mismo registro en:

```text
outputs/<LOCALIDAD>/generation.log
```

El modo normal muestra mensajes `INFO`: descarga de datos, área procesada, número de edificios, progreso por año y resumen final. Los errores de edificios individuales también quedan registrados.

Al comenzar, el log resume las opciones efectivas de la ejecución. Por ejemplo:

```text
Run options | source=cadastre:atom | image=context (exact geometry bounds) | multipart=keep together | aoi=muni | resolution=0.25 m/px | years=2025-2025 | workers=1 | limit=10 | verbose=no
```

`image` indica si el PNG conserva el contexto o aplica la máscara blanca. `multipart` indica si los componentes se mantienen juntos o se separan.

Los avisos esperados de Rasterio sobre imágenes WMS sin geotransformación integrada se ocultan por defecto. Para mostrar esos warnings y los mensajes `DEBUG`, añade `--verbose`:

```powershell
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --limit 10 --verbose
```

El modo `--verbose` añade una línea por imagen con:

- `coverage`: proporción de píxeles cubierta por el edificio.
- `raw_min` y `raw_max`: valores mínimo y máximo de la imagen original.
- `raw_std`: desviación estándar de sus píxeles.

Para guardar también las primeras imágenes originales, antes de aplicar la máscara blanca, utiliza `--debug-first N`:

```powershell
python src/main.py --city "Rubí" --province "Barcelona" --year-ini 2025 --year-end 2025 --limit 10 --debug-first 3
```

Estas imágenes se guardan en `outputs/_debug/<LOCALIDAD>/<AÑO>/_raw/`. El archivo de log rota al alcanzar 10 MB y conserva tres copias anteriores.

## Fuentes locales

```text
data_sources/
├── boundaries/
│   ├── divisions-administratives-v2r1-20250730.zip
│   └── valldoreix_boundary.geojson
└── ground_truth/
    └── Valldoreix_polygons.gpkg
```

| Formato | Contenido | Uso |
| --- | --- | --- |
| ZIP administrativo | Límites municipales oficiales de Cataluña | Se consulta antes que el servicio web del ICGC. |
| GeoJSON | Un límite geográfico concreto | Permite procesar áreas submunicipales, como Valldoreix. |
| GeoPackage | Edificios y atributos, como `GT_<AÑO>` | Puede sustituir la descarga de edificios de Catastro. |

### Valldoreix con Catastro

```powershell
python src/main.py --city "Valldoreix" --province "Barcelona" --year-ini 2024 --year-end 2024
```

El programa descarga los edificios de Sant Cugat del Vallès y aplica automáticamente el límite de `valldoreix_boundary.geojson`.

### Valldoreix con ground truth

```powershell
python src/main.py --city "Valldoreix" --year-ini 2024 --year-end 2024 --gt-polygons "Valldoreix_polygons.gpkg" --gt-filter positive --max-workers 1
```

### Límite personalizado

```powershell
python src/main.py --city "Nombre del área" --cadastre-city "Municipio oficial" --province "Barcelona" --year-ini 2024 --year-end 2024 --aoi-mode file --aoi-file "data_sources/boundaries/limite_local.geojson"
```

## Salidas

```text
outputs/<LOCALIDAD>/
├── generation.log
├── building_index.csv
├── building_index.gpkg
└── <AÑO>/
    └── *.png
```

Las fuentes originales permanecen en `data_sources/`; `outputs/` contiene únicamente datos generados.

## Estructura

```text
src/
├── main.py                    # Entrada, argumentos y logging
└── building_tiles/
    ├── config.py              # Configuración y validación
    ├── models.py              # Modelos tipados
    ├── geometry.py            # Reglas geométricas y temporales
    ├── catastro.py            # Cliente Catastro ATOM
    ├── icgc.py                # Límites y ortofotos ICGC
    ├── local_data.py          # Lectura de fuentes locales
    ├── imaging.py             # Máscaras y métricas
    ├── storage.py             # PNG e índices
    └── generator.py           # Coordinación y concurrencia

tests/                         # Pruebas automatizadas
data_sources/                  # Fuentes geográficas locales
outputs/                       # Resultados generados
```

## Formato del código

```powershell
python -m black src tests
```
