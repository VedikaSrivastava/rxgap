"""Frozen analysis contract for RxGap."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from shapely.geometry import box

# Overture Maps release pinned for reproducibility.
OVERTURE_RELEASE = "2026-08-19.0"
OVERTURE_S3 = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
OVERTURE_AZURE = (
    f"https://overturemapswestus2.blob.core.windows.net/release/{OVERTURE_RELEASE}"
)

# Product copy. Demand and simulatable pharmacies use every MA city/town that
# intersects BBOX — the same window pharmacies are already plotted in — because
# the Census Boston/Cambridge line is not how people actually move.
STUDY_AREA_LABEL = "Greater Boston"
STUDY_CITIES = ("Boston", "Cambridge")  # fallback if a demand report is missing
BUFFER_KM = 3.0

# Analysis window: Boston + Cambridge plus ~3 km. Demand, pharmacies, and the
# walk graph all use this box. Exact municipal clipping uses county subdivisions.
BBOX = {
    "xmin": -71.227,
    "ymin": 42.201,
    "xmax": -70.886,
    "ymax": 42.431,
}

# Board/NPPES "city" strings treated as local. Includes Boston neighborhoods
# (often listed instead of Boston) and abutting municipalities in BBOX.
LICENSE_CITY_ALIASES = (
    "Boston",
    "Cambridge",
    "Brookline",
    "Somerville",
    "Newton",
    "Watertown",
    "Chelsea",
    "Everett",
    "Medford",
    "Arlington",
    "Belmont",
    "Revere",
    "Winthrop",
    "Malden",
    "Quincy",
    "Milton",
    "Dedham",
    "Needham",
    "Waltham",
    "Westwood",
    "Wellesley",
    "Lexington",
    "Winchester",
    "Melrose",
    "Saugus",
    "Lynn",
    "Nahant",
    "Hull",
    "Hingham",
    "Weymouth",
    "Braintree",
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
STUDY_PLACE_NAMES = frozenset(name.lower() for name in LICENSE_CITY_ALIASES)

# Walking speeds are documented planning values, not a claim about who lives
# in no-vehicle households. Default is Average.
#
# Slow: 2.0 mph — MUTCD slower-walker design speed.
# Average: 3.0 mph — common FHWA / pedestrian-planning walking speed.
# Brisk: 4.0 mph — brisk adult walk.
PACES = {
    "slow": {"id": "slow", "label": "Slow", "mph": 2.0, "mps": 0.89408, "source": "MUTCD slower-walker (2.0 mph)"},
    "average": {"id": "average", "label": "Average", "mph": 3.0, "mps": 1.34112, "source": "FHWA pedestrian planning speed (3.0 mph)"},
    "brisk": {"id": "brisk", "label": "Brisk", "mph": 4.0, "mps": 1.78816, "source": "Brisk walk (4.0 mph)"},
}
DEFAULT_PACE = "average"
ACCESS_THRESHOLD_MINUTES = 15
H3_RESOLUTION = 9

# Currently licensed location comes from the MA Board retail roster.
# NPPES taxonomy is type evidence, not operating status.
MA_LICENSE_API = "https://healthprofessionlicensing-api.mass.gov/api-public"
MA_PHARMACY_BOARD = "BOARD_OF_REGISTRATION_IN_PHARMACY"
MA_RETAIL_EXPORT_PREFIX = "Retail_Pharmacy_License_Export_"
MA_ACTIVE_LICENSE_STATUSES = frozenset(
    {"Current", "Probation", "Non-Disciplinary Condition"}
)
RETAIL_TAXONOMY = "3336C0003X"
EXCLUDE_TAXONOMIES = {
    "3336M0002X",  # Mail Order Pharmacy
    "3336L0003X",  # Long Term Care Pharmacy
    "3336N0007X",  # Nuclear Pharmacy
    "3336I0012X",  # Institutional Pharmacy
    "332B00000X",  # DME only, used when it is the only taxonomy
}

# Storefronts that must never appear as active. Pipeline fails if they do.
KNOWN_CLOSED_STOREFRONTS = (
    {"street": "90 river", "city": "mattapan"},
    {"street": "1329 hyde park", "city": None},
    {"street": "2275 washington", "city": "roxbury"},
    {"street": "416 warren", "city": "roxbury"},
)

# Overture road classes a pedestrian can typically use. Motorways are excluded.
# Trunks are excluded unless the name is a bridge/overpass — Longfellow and the
# BU Bridge are tagged trunk, and dropping them forced a detour.
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

# Named crossings that must survive in the pedestrian graph.
REQUIRED_BRIDGES = ("Harvard", "Longfellow", "BU")

# Landmark / bridge-end seeds. Bridge points sit on sidewalks at each end,
# not mid-channel, so continuity checks measure the crossing rather than a
# detour from a poorly placed pin.
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

# Landmark → nearest matching licensed pharmacy, used as walking-distance checks.
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


def bbox_polygon():
    return box(BBOX["xmin"], BBOX["ymin"], BBOX["xmax"], BBOX["ymax"])


def ensure_dirs() -> None:
    for path in (DATA_RAW, DATA_PROCESSED, DATA_REPORTS, WEB_DATA):
        path.mkdir(parents=True, exist_ok=True)
