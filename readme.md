# Building Tiles Generator

Script para generar **tiles de edificios a partir de datos del Catastro**, procesando la información por municipio, provincia y rango de años.

Los datos catastrales se obtienen mediante la fuente `atom` y se procesan en paralelo utilizando varios workers.

## Uso

```bash
python src/thumbs_par.py \
  --city "<MUNICIPIO>" \
  --max-workers 4 \
  --year-ini 2012 \
  --year-end 2024 \
  --cadastre-source atom \
  --province "<PROVINCIA>"
```

## Parámetros

* `--city`: Municipio que se quiere procesar.
* `--province`: Provincia a la que pertenece el municipio.
* `--max-workers`: Número máximo de workers utilizados para procesar los datos en paralelo.
* `--year-ini`: Año inicial de los datos catastrales a procesar.
* `--year-end`: Año final de los datos catastrales a procesar.
* `--cadastre-source`: Fuente utilizada para obtener los datos del Catastro. Actualmente se utiliza `atom`.

## Ejemplos

### Barcelona

```bash
python src/thumbs_par.py --city "Sitges" --max-workers 4 --year-ini 2012 --year-end 2025 --cadastre-source atom --province "Barcelona"
```

### Tarragona

```bash
python src/thumbs_par.py --city "Reus" --max-workers 4 --year-ini 2012 --year-end 2025 --cadastre-source atom --province "Tarragona"
```

## Procesar un único año

Para generar los tiles correspondientes a un único año, se debe utilizar el mismo valor en `--year-ini` y `--year-end`.

```bash
python src/thumbs_par.py --city "Valldoreix" --max-workers 1 --year-ini 2018 --year-end 2018 --cadastre-source atom --province "Barcelona"
```

## Fuentes de datos locales

El proyecto separa los resultados generados de las fuentes geográficas de entrada por ejemplo:

```text
data_sources/
├── boundaries/
│   ├── divisions-administratives-v2r1-20250730.zip
│   └── valldoreix_boundary.geojson
└── ground_truth/
    └── Valldoreix_polygons.gpkg

outputs/
└── <LOCALIDAD>/<AÑO>/
```

Cada fichero tiene una finalidad diferente:

| Fichero | Contenido | Uso |
| --- | --- | --- |
| `divisions-administratives-v2r1-20250730.zip` | Límites oficiales de los municipios de Cataluña | Permite que `icgc.py` localice un municipio sin consultar por Internet el servicio de divisiones administrativas del ICGC. |
| `valldoreix_boundary.geojson` | Una geometría con el límite específico de Valldoreix | Recorta los edificios de Sant Cugat del Vallès para conservar solamente los que pertenecen a Valldoreix. |
| `Valldoreix_polygons.gpkg` | 8.136 polígonos de edificios con columnas `GT_2007` a `GT_2024` | Permite trabajar directamente con el conjunto *ground truth*, sin descargar los edificios mediante Catastro ATOM. |

### Municipio oficial mediante Catastro ATOM

Para un municipio oficial, Catastro ATOM proporciona los edificios y el ICGC proporciona el límite municipal. Por ejemplo, para Rubí:

```bash
python src/thumbs_par.py --city "Rubí" --year-ini 2025 --year-end 2025 --cadastre-source atom --province "Barcelona" --max-workers 4
```

Los resultados se guardan en `outputs/Rubí/2025`.

### Área submunicipal mediante GeoJSON

Valldoreix forma parte de Sant Cugat del Vallès y no dispone de una descarga catastral municipal independiente. Al utilizar `--city "Valldoreix"`, el programa aplica automáticamente estas opciones:

```text
Municipio de Catastro: Sant Cugat del Vallès
Límite de recorte:    data_sources/boundaries/valldoreix_boundary.geojson
Carpeta de salida:     outputs/Valldoreix/<AÑO>
```

Ejemplo:

```bash
python src/thumbs_par.py --city "Valldoreix" --year-ini 2018 --year-end 2018 --cadastre-source atom --province "Barcelona" --max-workers 4
```

Para procesar otra delimitación local se puede proporcionar cualquier GeoJSON, Shapefile o GeoPackage poligonal con `--aoi-mode file` y `--aoi-file`:

```bash
python src/thumbs_par.py --city "Nombre del área" --cadastre-city "Municipio oficial" --year-ini 2024 --year-end 2024 --cadastre-source atom --province "Barcelona" --aoi-mode file --aoi-file "data_sources/boundaries/limite_local.geojson"
```

### Polígonos etiquetados mediante GeoPackage

La opción `--gt-polygons` utiliza directamente los polígonos del GeoPackage. El programa busca automáticamente el fichero dentro de `data_sources/ground_truth`, por lo que basta con indicar su nombre:

```bash
python src/thumbs_par.py --city "Valldoreix" --year-ini 2024 --year-end 2024 --gt-polygons "Valldoreix_polygons.gpkg" --gt-filter positive --max-workers 1
```

`--gt-filter positive` conserva para cada año solamente los edificios cuyo campo `GT_<AÑO>` sea distinto de cero. Con `--gt-filter all` se procesan todos los polígonos.

### Límites municipales del ZIP

El ZIP administrativo no contiene edificios ni ortofotos. Solamente permite obtener el contorno de un municipio. `icgc.py` está preparado para buscarlo automáticamente en `data_sources/boundaries` y, si no está disponible, recurrir al servicio web del ICGC.

`thumbs_par.py` utiliza `icgc.py`: primero intenta leer este ZIP local y, si no está disponible o no contiene un municipio válido, recurre automáticamente al servicio web del ICGC.
