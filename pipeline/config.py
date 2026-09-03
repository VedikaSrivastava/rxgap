"""Frozen analysis contract for RxGap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Overture Maps release pinned for reproducibility.
OVERTURE_RELEASE = "2026-08-19.0"
OVERTURE_S3 = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
OVERTURE_AZURE = (
    f"https://overturemapswestus2.blob.core.windows.net/release/{OVERTURE_RELEASE}"
)

# For this analysis, RxGap defines its Greater Boston study area as these
# 22 complete municipalities. Demand and closable pharmacies live only here.
# A 3 km routing envelope beyond the municipal union (see geography.py) is
# used for network extract and context pharmacies — not for demand.
STUDY_AREA_LABEL = "Greater Boston"
STUDY_MUNICIPALITIES = (
    "Boston",
    "Cambridge",
    "Somerville",
    "Brookline",
    "Newton",
    "Watertown",
    "Belmont",
    "Arlington",
    "Medford",
    "Malden",
    "Everett",
    "Chelsea",
    "Revere",
    "Winthrop",
    "Lynn",
    "Quincy",
    "Milton",
    "Braintree",
    "Dedham",
    "Needham",
    "Waltham",
    "Weymouth",
)
STUDY_CITIES = STUDY_MUNICIPALITIES
STUDY_MUNICIPALITY_NAMES = frozenset(name.lower() for name in STUDY_MUNICIPALITIES)
BUFFER_KM = 3.0

# Board/NPPES "city" strings for license fetch / geocode backfill only.
# Study membership (inStudyArea / simulatable) is polygon covers() — never aliases.
LICENSE_CITY_ALIASES = (
    *STUDY_MUNICIPALITIES,
    "Westwood",
    "Wellesley",
    "Lexington",
    "Winchester",
    "Melrose",
    "Saugus",
    "Nahant",
    "Hull",
    "Hingham",
    "Randolph",
    "Canton",
    "Dorchester",
    "Roxbury",
    "Jamaica Plain",
    "Brighton",
    "Allston",
    "Charlestown",
    "Hyde Park",
    "Mattapan",
    "Roslindale",
    "West Roxbury",
    "East Boston",
    "South Boston",
    "Mission Hill",
    "Roxbury Crossing",
    "Chestnut Hill",
    "Boston College",
    "Harvard Square",
    "West Newton",
    "Newton Center",
    "Newton Highlands",
    "Newtonville",
    "Wollaston",
)

# Walking speeds are documented planning values. UX primary control is Max Walk;
# speed is an Assumptions disclosure. Default is Standard (3 mph).
#
# Slower: 2.0 mph — MUTCD slower-walker design speed.
# Standard: 3.0 mph — common FHWA / pedestrian-planning walking speed.
# Faster: 4.0 mph — brisk adult walk.
PACES = {
    "slow": {
        "id": "slow",
        "label": "Slower",
        "mph": 2.0,
        "mps": 0.89408,
        "source": "MUTCD slower-walker (2.0 mph)",
    },
    "average": {
        "id": "average",
        "label": "Standard",
        "mph": 3.0,
        "mps": 1.34112,
        "source": "FHWA pedestrian planning speed (3.0 mph)",
    },
    "brisk": {
        "id": "brisk",
        "label": "Faster",
        "mph": 4.0,
        "mps": 1.78816,
        "source": "Brisk walk (4.0 mph)",
    },
}
DEFAULT_PACE = "average"
ACCESS_THRESHOLD_MINUTES = 15
H3_RESOLUTION = 9

MA_LICENSE_API = "https://healthprofessionlicensing-api.mass.gov/api-public"
MA_PHARMACY_BOARD = "BOARD_OF_REGISTRATION_IN_PHARMACY"
MA_RETAIL_EXPORT_PREFIX = "Retail_Pharmacy_License_Export_"
MA_ACTIVE_LICENSE_STATUSES = frozenset(
    {"Current", "Probation", "Non-Disciplinary Condition"}
)
RETAIL_TAXONOMY = "3336C0003X"
EXCLUDE_TAXONOMIES = {
    "3336M0002X",
    "3336L0003X",
    "3336N0007X",
    "3336I0012X",
    "332B00000X",
}

KNOWN_CLOSED_STOREFRONTS = (
    {"street": "90 river", "city": "mattapan"},
    {"street": "1329 hyde park", "city": None},
    {"street": "2275 washington", "city": "roxbury"},
    {"street": "416 warren", "city": "roxbury"},
)

WALKABLE_CLASSES = {
    "footway",
    "path",
    "pedestrian",
    "steps",
    "living_street",
    "residential",
    "unclassified",
    "service",
    "tertiary",
    "secondary",
    "primary",
    "track",
    "cycleway",
    "bridleway",
    "alley",
}

REQUIRED_BRIDGES = ("Harvard", "Longfellow", "BU")

GRAPH_SEEDS = {
    "boston_city_hall": (42.3604, -71.0578),
    "harvard_square": (42.3736, -71.1189),
    "central_square": (42.3651, -71.1036),
    "kendall": (42.3626, -71.0843),
    "nubian": (42.3296, -71.0845),
    "longfellow_boston": (42.36093, -71.07086),
    "longfellow_cambridge": (42.36178, -71.07973),
    "harvard_bridge_boston": (42.3515, -71.0897),
    "harvard_bridge_cambridge": (42.3572, -71.0929),
    "bu_boston": (42.3516, -71.1109),
    "bu_cambridge": (42.3535, -71.1174),
    "brookline_border": (42.3420, -71.1210),
    "somerville_border": (42.3870, -71.1000),
    "newton_border": (42.3370, -71.1500),
}

GRAPH_ROUTES = (
    ("boston_to_harvard_square_m", "boston_city_hall", "harvard_square"),
    ("longfellow_cross_m", "longfellow_boston", "longfellow_cambridge"),
    ("harvard_bridge_cross_m", "harvard_bridge_boston", "harvard_bridge_cambridge"),
    ("bu_bridge_cross_m", "bu_boston", "bu_cambridge"),
    ("boston_to_brookline_border_m", "boston_city_hall", "brookline_border"),
    ("cambridge_to_somerville_border_m", "harvard_square", "somerville_border"),
    ("boston_to_newton_border_m", "boston_city_hall", "newton_border"),
)

WALK_CHECKS = (
    ("boston_city_hall", "CVS"),
    ("harvard_square", "CVS"),
    ("central_square", "pharmacy"),
    ("nubian", "pharmacy"),
    ("kendall", "pharmacy"),
)

ACS_YEAR = 2023
ACS_DATASET = "acs/acs5"
ACS_NO_VEHICLE = {
    "total_occupied": "B25044_E001",
    "total_occupied_moe": "B25044_M001",
    "owner_no_vehicle": "B25044_E003",
    "owner_no_vehicle_moe": "B25044_M003",
    "renter_no_vehicle": "B25044_E010",
    "renter_no_vehicle_moe": "B25044_M010",
}

ROOT = Path(__file__).resolve().parents[1]
DATA_RAW = ROOT / "data" / "raw"
DATA_PROCESSED = ROOT / "data" / "processed"
DATA_REPORTS = ROOT / "data" / "reports"
WEB_DATA = ROOT / "web" / "public" / "data"

CITIES_GEOJSON = DATA_PROCESSED / "cities.geojson"
ANALYSIS_ENVELOPE_GEOJSON = DATA_PROCESSED / "analysis_envelope.geojson"
ANALYSIS_BBOX_PATH = DATA_PROCESSED / "analysis_bbox.json"
GEOGRAPHY_REPORT = DATA_REPORTS / "geography.json"


@dataclass(frozen=True)
class Pace:
    id: str
    label: str
    mph: float
    mps: float
    source: str


def pace(name: str = DEFAULT_PACE) -> Pace:
    row = PACES[name]
    return Pace(**row)


def ensure_dirs() -> None:
    for path in (DATA_RAW, DATA_PROCESSED, DATA_REPORTS, WEB_DATA):
        path.mkdir(parents=True, exist_ok=True)
