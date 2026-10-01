from __future__ import annotations

import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile

import geopandas as gpd
import requests

ATOM_INDEX_URLS = (
    "https://www.catastro.hacienda.gob.es/INSPIRE/buildings/ES.SDGC.BU.atom.xml",
    "https://www.catastro.minhap.es/INSPIRE/buildings/ES.SDGC.BU.atom.xml",
    "https://www.catastro.hacienda.gob.es/INSPIRE/Buildings/ES.SDGC.BU.atom.xml",
)
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}
ARTICLES = ("el", "la", "los", "las", "lo", "l", "els", "les", "o", "a", "os", "as")
REQUEST_HEADERS = {"User-Agent": "BuildingTilesGenerator/1.0"}


def _normalized_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    normalized = without_accents.lower().replace("’", "'")
    normalized = re.sub(r"[^\w\s()/-]", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def canonical_municipality_name(value: str) -> str:
    normalized = _normalized_text(value)
    normalized = re.sub(r"^\d{4,}\s*-\s*", "", normalized)
    normalized = re.sub(r"\bbuildings\b$", "", normalized).strip()

    article_pattern = "|".join(ARTICLES)
    match = re.match(rf"^(.*)\s+\(({article_pattern})\)$", normalized)
    if match is None:
        match = re.match(rf"^(.*)\s+({article_pattern})$", normalized)
    if match:
        core, article = match.groups()
        normalized = f"{article} {core}"

    normalized = re.sub(r"\bl['’]\s*", "l ", normalized)
    return re.sub(r"\s+", " ", normalized.replace("-", " ")).strip()


def _fetch_xml(url: str, session: requests.Session | None = None) -> ET.Element:
    requester = session or requests
    response = requester.get(url, timeout=60, headers=REQUEST_HEADERS)
    response.raise_for_status()
    return ET.fromstring(response.content)


def _open_atom_index(session: requests.Session | None = None) -> ET.Element:
    errors = []
    for url in ATOM_INDEX_URLS:
        try:
            return _fetch_xml(url, session)
        except (requests.RequestException, ET.ParseError) as exc:
            errors.append(f"{url}: {exc}")
    raise RuntimeError("No Catastro ATOM index was available. " + " | ".join(errors))


def _atom_entries(feed: ET.Element) -> list[tuple[str, str]]:
    entries = []
    for entry in feed.findall("atom:entry", ATOM_NAMESPACE):
        title = (
            entry.findtext("atom:title", default="", namespaces=ATOM_NAMESPACE) or ""
        )
        link = entry.find("atom:link", ATOM_NAMESPACE)
        href = link.get("href") if link is not None else None
        if title and href:
            entries.append((title, href))
    return entries


def _province_entries(
    province: str | None,
    session: requests.Session | None,
) -> list[tuple[str, str]]:
    entries = _atom_entries(_open_atom_index(session))
    if province:
        wanted = _normalized_text(province)
        entries = [entry for entry in entries if wanted in _normalized_text(entry[0])]
        if not entries:
            raise ValueError(
                f"Province '{province}' was not found in the Catastro ATOM index."
            )
    return entries


def list_municipalities(
    province: str | None = None,
    session: requests.Session | None = None,
) -> list[str]:
    municipalities = []
    for _, feed_url in _province_entries(province, session):
        municipalities.extend(
            title.strip() for title, _ in _atom_entries(_fetch_xml(feed_url, session))
        )
    return sorted(set(municipalities), key=str.upper)


def download_municipality_buildings(
    municipality: str,
    province: str | None = None,
    session: requests.Session | None = None,
) -> gpd.GeoDataFrame:
    wanted = canonical_municipality_name(municipality)
    requester = session or requests

    for _, feed_url in _province_entries(province, session):
        for title, download_url in _atom_entries(_fetch_xml(feed_url, session)):
            if canonical_municipality_name(title) != wanted:
                continue

            response = requester.get(download_url, timeout=120, headers=REQUEST_HEADERS)
            response.raise_for_status()
            try:
                with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                    gml_files = [
                        name
                        for name in archive.namelist()
                        if name.lower().endswith(".gml")
                    ]
                    if not gml_files:
                        raise ValueError(
                            "The downloaded Catastro ZIP contains no GML file."
                        )
                    with archive.open(gml_files[0]) as gml_file:
                        return gpd.read_file(gml_file)
            except zipfile.BadZipFile as exc:
                raise RuntimeError(
                    f"Catastro returned an invalid ZIP for '{municipality}'."
                ) from exc

    raise ValueError(
        f"Municipality '{municipality}' was not found in Catastro ATOM feeds (province={province or 'ANY'})."
    )
