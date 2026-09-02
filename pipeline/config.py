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

# Demand is clipped to these municipalities. Pharmacies and the walk graph
# extend 3 km beyond so border neighborhoods are not artificially stranded.
STUDY_CITIES = ("Boston", "Cambridge")
STUDY_PLACE_NAMES = frozenset(
    {
        "boston",
        "cambridge",
        "dorchester",
        "roxbury",
        "jamaica plain",
        "brighton",
        "allston",
        "charlestown",
        "hyde park",
        "mattapan",
        "roslindale",
        "west roxbury",
        "east boston",
        "south boston",
        "mission hill",
        "roxbury crossing",
    }
)
BUFFER_KM = 3.0

# Union of Boston + Cambridge bounding boxes, then expanded by BUFFER_KM.
# Used only as a cheap GeoParquet predicate; exact clipping uses city polygons.
BBOX = {
    "xmin": -71.227,
    "ymin": 42.201,
    "xmax": -70.886,
    "ymax": 42.431,
}

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

# Overture road classes a pedestrian can typically use. Motorways are excluded;
# walk-denied access_restrictions are filtered at extract time.
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
    "trunk",
    "track",
    "cycleway",
    "bridleway",
    "alley",
}

# Named crossings that must survive in the pedestrian graph.
REQUIRED_BRIDGES = ("Harvard", "Longfellow", "BU")

# Hand-check walking pairs used in the spike report (origin_name, dest_hint).
WALK_CHECKS = (
    ("Boston City Hall", "CVS"),
    ("Harvard Square", "CVS"),
    ("Central Square", "pharmacy"),
    ("Nubian Square", "pharmacy"),
    ("Kendall Square", "pharmacy"),
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


def ensure_dirs() -> None:
    for path in (DATA_RAW, DATA_PROCESSED, DATA_REPORTS, WEB_DATA):
        path.mkdir(parents=True, exist_ok=True)
