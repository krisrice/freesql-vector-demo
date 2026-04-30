from __future__ import annotations

import argparse
import array
import json
import os
import sys
import threading
import time
import uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

import oracledb

os.environ.setdefault("HF_HOME", os.path.join(os.path.dirname(__file__), ".cache", "huggingface"))
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")


def load_dotenv() -> None:
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, encoding="utf-8") as env_file:
        for line in env_file:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            name, value = stripped.split("=", 1)
            os.environ.setdefault(name.strip(), value.strip().strip("\"'"))


load_dotenv()

USERNAME = os.environ.get("ORACLE_USER")
PASSWORD = os.environ.get("ORACLE_PASSWORD")
DSN = os.environ.get("ORACLE_DSN")

MODEL_NAME = os.environ.get("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
EMBEDDING_DIMS = 384
EMBEDDING_VECTOR_TYPE = "int8"
TABLE_NAME = "AUTOMOTIVE_PARTS"
INVENTORY_TARGET = max(1000, int(os.environ.get("INVENTORY_TARGET", "1000")))
INSTALL_STATUS_LOCK = threading.Lock()
INSTALL_STATUS: dict[str, Any] = {
    "ok": True,
    "job_id": None,
    "status": "idle",
    "step": "idle",
    "embeddings_generated": 0,
    "rows_inserted": 0,
    "target_count": INVENTORY_TARGET,
    "message": "No install job has run.",
}


SAMPLE_PARTS = [
    {
        "part_number": "ENG-OIL-5W30",
        "name": "Synthetic Engine Oil 5W-30",
        "category": "Fluids",
        "description": "Full synthetic motor oil for modern gasoline engines, improves cold starts and wear protection.",
        "unit_price": 38.99,
    },
    {
        "part_number": "BRK-PAD-CER-F",
        "name": "Ceramic Front Brake Pad Set",
        "category": "Brakes",
        "description": "Low dust ceramic brake pads for front axle service with quiet stopping performance.",
        "unit_price": 64.5,
    },
    {
        "part_number": "FLT-AIR-STD",
        "name": "Engine Air Filter",
        "category": "Filters",
        "description": "Pleated air intake filter that traps dust and debris before air reaches the throttle body.",
        "unit_price": 18.75,
    },
    {
        "part_number": "FLT-CAB-CARBON",
        "name": "Activated Carbon Cabin Filter",
        "category": "Filters",
        "description": "Cabin air filter with activated carbon media to reduce pollen, odors, and road pollutants.",
        "unit_price": 24.25,
    },
    {
        "part_number": "IGN-PLUG-IR",
        "name": "Iridium Spark Plug",
        "category": "Ignition",
        "description": "Long life iridium spark plug for efficient combustion, stable idle, and reliable cold starts.",
        "unit_price": 13.49,
    },
    {
        "part_number": "BAT-AGM-48",
        "name": "Group 48 AGM Battery",
        "category": "Electrical",
        "description": "Absorbent glass mat battery for vehicles with start-stop systems and high accessory loads.",
        "unit_price": 219.0,
    },
    {
        "part_number": "SUS-STRUT-FL",
        "name": "Front Left Complete Strut Assembly",
        "category": "Suspension",
        "description": "Loaded strut assembly with coil spring and mount to restore ride control and steering stability.",
        "unit_price": 146.99,
    },
    {
        "part_number": "COOL-RAD-AL",
        "name": "Aluminum Radiator",
        "category": "Cooling",
        "description": "Direct fit aluminum radiator that dissipates engine heat and helps prevent overheating.",
        "unit_price": 185.25,
    },
    {
        "part_number": "DRV-CV-AXLE-R",
        "name": "Right CV Axle Shaft",
        "category": "Drivetrain",
        "description": "Constant velocity axle shaft for transferring torque smoothly to the drive wheel.",
        "unit_price": 98.8,
    },
    {
        "part_number": "LGT-LED-H11",
        "name": "H11 LED Headlight Bulb Pair",
        "category": "Lighting",
        "description": "LED replacement headlight bulbs with bright white output for improved nighttime visibility.",
        "unit_price": 52.0,
    },
    {
        "part_number": "WIP-BLD-22",
        "name": "22 Inch Beam Wiper Blade",
        "category": "Exterior",
        "description": "All weather beam style windshield wiper blade for streak free rain and snow clearing.",
        "unit_price": 16.95,
    },
    {
        "part_number": "FUEL-PUMP-IN",
        "name": "In-Tank Electric Fuel Pump",
        "category": "Fuel",
        "description": "Electric fuel pump module that maintains pressure delivery from the tank to the injectors.",
        "unit_price": 132.4,
    },
]

VEHICLE_APPLICATIONS = [
    ("2018-2024", "Toyota", "Camry", "2.5L I4"),
    ("2016-2023", "Toyota", "Tacoma", "3.5L V6"),
    ("2019-2024", "Toyota", "RAV4", "2.5L I4"),
    ("2018-2023", "Honda", "Accord", "1.5L Turbo"),
    ("2016-2024", "Honda", "Civic", "2.0L I4"),
    ("2017-2024", "Honda", "CR-V", "1.5L Turbo"),
    ("2015-2023", "Ford", "F-150", "3.5L EcoBoost"),
    ("2018-2024", "Ford", "Explorer", "2.3L EcoBoost"),
    ("2017-2024", "Ford", "Escape", "1.5L EcoBoost"),
    ("2016-2024", "Chevrolet", "Silverado 1500", "5.3L V8"),
    ("2017-2024", "Chevrolet", "Equinox", "1.5L Turbo"),
    ("2016-2023", "Chevrolet", "Malibu", "1.5L Turbo"),
    ("2017-2024", "GMC", "Sierra 1500", "5.3L V8"),
    ("2019-2024", "Ram", "1500", "5.7L HEMI V8"),
    ("2018-2024", "Jeep", "Wrangler", "3.6L V6"),
    ("2017-2024", "Jeep", "Grand Cherokee", "3.6L V6"),
    ("2018-2024", "Subaru", "Outback", "2.5L H4"),
    ("2017-2024", "Subaru", "Forester", "2.5L H4"),
    ("2018-2024", "Nissan", "Altima", "2.5L I4"),
    ("2017-2024", "Nissan", "Rogue", "2.5L I4"),
    ("2016-2023", "Nissan", "Frontier", "3.8L V6"),
    ("2017-2024", "Hyundai", "Elantra", "2.0L I4"),
    ("2018-2024", "Hyundai", "Tucson", "2.5L I4"),
    ("2016-2023", "Hyundai", "Santa Fe", "2.4L I4"),
    ("2017-2024", "Kia", "Sorento", "2.5L I4"),
    ("2018-2024", "Kia", "Sportage", "2.4L I4"),
    ("2016-2024", "Mazda", "CX-5", "2.5L I4"),
    ("2017-2024", "Mazda", "Mazda3", "2.5L I4"),
    ("2018-2024", "Volkswagen", "Jetta", "1.4L Turbo"),
    ("2018-2024", "Volkswagen", "Tiguan", "2.0L Turbo"),
    ("2016-2024", "BMW", "330i", "2.0L Turbo"),
    ("2017-2024", "BMW", "X3", "2.0L Turbo"),
    ("2016-2024", "Mercedes-Benz", "C300", "2.0L Turbo"),
    ("2017-2024", "Mercedes-Benz", "GLC300", "2.0L Turbo"),
    ("2017-2024", "Audi", "A4", "2.0L Turbo"),
    ("2018-2024", "Audi", "Q5", "2.0L Turbo"),
    ("2017-2024", "Lexus", "RX350", "3.5L V6"),
    ("2018-2024", "Lexus", "ES350", "3.5L V6"),
    ("2016-2024", "Acura", "MDX", "3.5L V6"),
    ("2018-2024", "Volvo", "XC60", "2.0L Turbo"),
    ("2017-2024", "Tesla", "Model 3", "Electric"),
    ("2020-2024", "Tesla", "Model Y", "Electric"),
]

PART_CATALOG = [
    ("BRKPADF", "Brakes", "Front Ceramic Brake Pad Set", "low dust ceramic friction material for quiet front axle braking", 66.99),
    ("BRKPARR", "Brakes", "Rear Ceramic Brake Pad Set", "low noise ceramic rear brake pads with stable pedal feel", 58.99),
    ("ROTORF", "Brakes", "Front Coated Brake Rotor Pair", "corrosion resistant vented rotors for front brake service", 112.99),
    ("ROTORR", "Brakes", "Rear Coated Brake Rotor Pair", "coated rear rotors for smooth braking and reduced pulsation", 98.99),
    ("CALIPFL", "Brakes", "Front Left Brake Caliper", "remanufactured caliper with bracket for restoring hydraulic clamping force", 92.5),
    ("CALIPFR", "Brakes", "Front Right Brake Caliper", "remanufactured caliper with bracket for seized or leaking brake repairs", 92.5),
    ("AIFILT", "Filters", "Engine Air Filter", "pleated intake filter that blocks dust before it reaches the engine", 19.25),
    ("CABFIL", "Filters", "Activated Carbon Cabin Air Filter", "carbon cabin filter for pollen odor and road pollutant reduction", 25.5),
    ("OILFIL", "Filters", "Spin-On Oil Filter", "engine oil filter with anti-drainback valve for clean lubrication", 10.75),
    ("FUELFI", "Fuel", "Fuel Filter", "inline fuel filter for trapping sediment before injectors and pump rails", 21.99),
    ("SPARKI", "Ignition", "Iridium Spark Plug Set", "long life iridium plugs for reliable combustion and smooth idle", 46.99),
    ("IGNCOI", "Ignition", "Ignition Coil", "direct fit coil for misfire rough idle and weak spark diagnostics", 54.75),
    ("BATAGM", "Electrical", "AGM Battery", "absorbent glass mat starting battery for high accessory electrical loads", 218.99),
    ("ALTNEW", "Electrical", "Alternator", "charging system alternator for low voltage battery warning repairs", 245.0),
    ("STARTM", "Electrical", "Starter Motor", "replacement starter motor for slow crank or no crank conditions", 179.99),
    ("ABSENS", "Electrical", "ABS Wheel Speed Sensor", "wheel speed sensor for traction control and anti-lock brake faults", 38.5),
    ("HEADLH", "Lighting", "LED Headlight Bulb Pair", "bright white LED headlight bulbs for improved nighttime visibility", 52.0),
    ("TAILLA", "Lighting", "Tail Lamp Assembly", "direct fit rear lamp assembly with clear lens and sealed housing", 88.25),
    ("STRUTL", "Suspension", "Front Left Complete Strut Assembly", "loaded strut with spring mount and bearing for restoring ride control", 148.99),
    ("STRUTR", "Suspension", "Front Right Complete Strut Assembly", "loaded strut assembly for stable steering and reduced nose dive", 148.99),
    ("SHOCKR", "Suspension", "Rear Shock Absorber Pair", "gas charged rear shocks for improved damping and tire contact", 84.99),
    ("CTRLAR", "Suspension", "Lower Control Arm", "control arm with bushings and ball joint for alignment stability", 118.5),
    ("TIEROD", "Steering", "Outer Tie Rod End", "steering linkage end for looseness wandering or uneven tire wear", 31.75),
    ("HUBASM", "Wheel End", "Front Wheel Hub Assembly", "sealed hub and bearing assembly for wheel growl and ABS faults", 124.99),
    ("CVAXLE", "Drivetrain", "CV Axle Shaft", "constant velocity axle shaft for clicking on turns or torn boot service", 101.5),
    ("RADALU", "Cooling", "Aluminum Radiator", "direct fit radiator for coolant leaks and overheating protection", 188.99),
    ("WATPMP", "Cooling", "Engine Water Pump", "water pump for coolant circulation leaks and overheating repairs", 76.25),
    ("THERMO", "Cooling", "Thermostat Housing Assembly", "thermostat and housing for regulating engine operating temperature", 42.99),
    ("OXYUP", "Emission", "Upstream Oxygen Sensor", "air fuel ratio sensor for fuel trim and emissions diagnostics", 69.99),
    ("CATCON", "Emission", "Catalytic Converter", "direct fit converter for emissions efficiency fault repair", 329.0),
    ("MUFFLR", "Exhaust", "Rear Muffler Assembly", "quiet replacement muffler for rusted or noisy exhaust systems", 154.25),
    ("BELTSR", "Engine", "Serpentine Belt", "multi-rib accessory belt for alternator compressor and water pump drive", 28.75),
    ("TENSNR", "Engine", "Belt Tensioner Assembly", "automatic belt tensioner for chirping slipping or worn pulley bearings", 64.5),
    ("GASKVC", "Engine", "Valve Cover Gasket Set", "gasket set for oil seepage around the cylinder head cover", 36.99),
    ("WIPERB", "Exterior", "Beam Wiper Blade Set", "all weather beam wipers for streak free windshield clearing", 29.99),
    ("MIRROR", "Exterior", "Power Door Mirror", "heated power mirror assembly for visibility and body repair", 119.99),
    ("WINDOW", "Interior", "Window Regulator with Motor", "door window regulator and motor for stuck or slow glass operation", 87.99),
    ("BLOWER", "HVAC", "HVAC Blower Motor", "cabin blower motor for weak airflow noise or failed fan speeds", 72.5),
]


def make_part_number(make: str, model: str, years: str, code: str) -> str:
    prefix = "".join(character for character in f"{make[:3]}{model[:5]}".upper() if character.isalnum())
    year_code = years.split("-")[0][-2:] + years.split("-")[1][-2:]
    return f"{prefix}-{year_code}-{code}"


def build_inventory_parts() -> list[dict[str, Any]]:
    parts = list(SAMPLE_PARTS)
    seen_part_numbers = {part["part_number"] for part in parts}

    for years, make, model, engine in VEHICLE_APPLICATIONS:
        application = f"{years} {make} {model} {engine}"
        for code, category, part_name, detail, price in PART_CATALOG:
            part_number = make_part_number(make, model, years, code)
            if part_number in seen_part_numbers:
                continue
            seen_part_numbers.add(part_number)
            multiplier = 1 + (len(make) % 5) * 0.03 + (len(model) % 7) * 0.025
            parts.append(
                {
                    "part_number": part_number,
                    "name": f"{application} {part_name}",
                    "category": category,
                    "description": f"Aftermarket direct fit {part_name.lower()} for {application}; {detail}.",
                    "unit_price": round(price * multiplier, 2),
                }
            )
            if len(parts) >= INVENTORY_TARGET:
                return parts

    if len(parts) < 1000:
        raise RuntimeError(f"Inventory seed generated only {len(parts)} parts")
    return parts


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Automotive Parts Vector Search</title>
  <script crossorigin src="https://unpkg.com/react@18/umd/react.development.js"></script>
  <script crossorigin src="https://unpkg.com/react-dom@18/umd/react-dom.development.js"></script>
  <script crossorigin src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    :root {
      color-scheme: light;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: #f6f7f9;
      color: #172026;
    }
    * { box-sizing: border-box; }
    body { margin: 0; }
    button, input, select { font: inherit; }
    button { cursor: pointer; }
    button:disabled { cursor: wait; opacity: .65; }
    .shell { max-width: 1160px; margin: 0 auto; padding: 28px 18px 44px; }
    .topbar { display: flex; justify-content: space-between; gap: 16px; align-items: end; margin-bottom: 16px; }
    h1 { margin: 0; font-size: clamp(28px, 4vw, 42px); letter-spacing: 0; }
    h2 { margin: 0 0 12px; font-size: 22px; letter-spacing: 0; }
    h3 { margin: 0; font-size: 16px; letter-spacing: 0; }
    .meta { margin: 6px 0 0; color: #52616b; }
    .pill { display: inline-flex; align-items: center; gap: 6px; border: 1px solid #cfd7df; border-radius: 999px; padding: 6px 10px; background: white; color: #33424c; font-size: 13px; }
    .tabs { display: flex; gap: 8px; border-bottom: 1px solid #d7dee5; margin-bottom: 20px; overflow-x: auto; }
    .tab {
      border: 0; border-bottom: 3px solid transparent; background: transparent; padding: 12px 10px 10px;
      color: #52616b;
    }
    .tab.active { border-color: #125e54; color: #172026; font-weight: 750; }
    .panel { margin-top: 18px; }
    .search { display: grid; grid-template-columns: 1fr 96px 120px; gap: 10px; margin: 0 0 16px; }
    .search input, .search select, .input {
      border: 1px solid #cfd7df; border-radius: 8px; padding: 12px 14px; background: white; min-width: 0;
    }
    .primary {
      border: 0; border-radius: 8px; padding: 12px 14px; background: #125e54; color: white;
    }
    .secondary {
      border: 1px solid #b8c4ce; border-radius: 8px; padding: 12px 14px; background: white; color: #172026;
    }
    .danger {
      border: 1px solid #c5564a; border-radius: 8px; padding: 12px 14px; background: #fff7f5; color: #922b21;
    }
    .status { min-height: 24px; color: #52616b; margin-bottom: 14px; }
    .notice {
      display: flex; justify-content: space-between; align-items: center; gap: 12px; border: 1px solid #d5b55f;
      background: #fff8e1; border-radius: 8px; padding: 14px; margin-bottom: 16px;
    }
    .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 12px; }
    .card {
      background: white; border: 1px solid #dfe5eb; border-radius: 8px; padding: 16px;
      display: flex; flex-direction: column; gap: 10px;
    }
    .card header { display: flex; justify-content: space-between; gap: 12px; align-items: start; }
    .name { font-weight: 750; line-height: 1.25; }
    .distance { color: #125e54; font-variant-numeric: tabular-nums; white-space: nowrap; }
    .part { color: #52616b; font-size: 13px; }
    .category { width: fit-content; background: #e8eef3; border-radius: 999px; padding: 4px 9px; font-size: 12px; }
    .desc { color: #33424c; line-height: 1.45; margin: 0; }
    .price { margin-top: auto; font-weight: 700; }
    .install-layout { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 16px; align-items: start; }
    .toolbar { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }
    .progress-wrap { margin: 12px 0 8px; height: 12px; border-radius: 999px; background: #dfe5eb; overflow: hidden; }
    .progress-bar { height: 100%; background: #2f7d32; transition: width .2s ease; }
    .kv { display: grid; grid-template-columns: 140px 1fr; gap: 8px 12px; font-size: 14px; }
    .kv dt { color: #52616b; }
    .kv dd { margin: 0; overflow-wrap: anywhere; }
    .details-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
    .sql {
      background: #111820; color: #e8eef3; border-radius: 8px; padding: 14px; overflow-x: auto; font-size: 13px; line-height: 1.45;
    }
    .vector {
      background: #f1f4f7; border: 1px solid #dbe2e8; border-radius: 8px; padding: 10px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 12px; line-height: 1.5; overflow-wrap: anywhere;
    }
    .vector-toggle { border: 0; background: transparent; color: #125e54; padding: 4px 0; font-weight: 700; }
    @media (max-width: 820px) {
      .topbar, .notice { display: block; }
      .search, .install-layout, .details-layout { grid-template-columns: 1fr; }
      .notice .secondary, .notice .primary { margin-top: 10px; width: 100%; }
    }
  </style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
    const { useEffect, useMemo, useState } = React;

    const EXAMPLES = [
      "Toyota Camry front brake pads quiet",
      "2019 F-150 misfire rough idle coil",
      "overheating coolant leak radiator",
      "weak cabin airflow blower motor",
      "wheel growl ABS sensor hub",
    ];

    function TabButton({ id, activeTab, setActiveTab, children }) {
      return <button className={activeTab === id ? "tab active" : "tab"} onClick={() => setActiveTab(id)}>{children}</button>;
    }

    function SearchForm({ query, setQuery, limit, setLimit, onSubmit, loading, buttonLabel = "Search" }) {
      return (
        <form className="search" onSubmit={onSubmit}>
          <input value={query} onChange={event => setQuery(event.target.value)} placeholder="Search by meaning, symptom, or job..." />
          <select value={limit} onChange={event => setLimit(event.target.value)}>
            {[3, 6, 9, 12].map(value => <option key={value} value={value}>{value}</option>)}
          </select>
          <button className="primary" disabled={loading}>{loading ? "Searching" : buttonLabel}</button>
        </form>
      );
    }

    function ResultCard({ part, details = false }) {
      return (
        <article className="card">
          <header>
            <div>
              <div className="name">{part.name}</div>
              <div className="part">{part.part_number}</div>
            </div>
            <div className="distance">{part.distance.toFixed(4)}</div>
          </header>
          <span className="category">{part.category}</span>
          <p className="desc">{part.description}</p>
          {details && <VectorPreview label="Row vector" vector={part.embedding || []} />}
          <div className="price">${part.unit_price.toFixed(2)}</div>
        </article>
      );
    }

    function VectorPreview({ label, vector }) {
      const [expanded, setExpanded] = useState(false);
      const values = expanded ? vector : vector.slice(0, 32);
      const suffix = expanded || vector.length <= 32 ? "" : " ...";
      return (
        <div>
          <div className="part">{label}: {vector.length} values</div>
          <div className="vector">[{values.join(", ")}{suffix}]</div>
          {vector.length > 32 && (
            <button className="vector-toggle" onClick={() => setExpanded(!expanded)}>
              {expanded ? "Collapse vector" : "Show full vector"}
            </button>
          )}
        </div>
      );
    }

    function InstallNotice({ health, startInstall }) {
      if (health?.installed) return null;
      return (
        <div className="notice">
          <div>
            <strong>Sample data is not installed.</strong>
            <div className="meta">
              {health ? `${health.part_count || 0} of ${health.target_count || 1000} rows are indexed.` : "Table status is unknown."}
            </div>
          </div>
          <button className="primary" onClick={() => startInstall(false)}>Install Now</button>
        </div>
      );
    }

    function ProgressBar({ label, value, target }) {
      const pct = Math.max(0, Math.min(100, Math.round((value / target) * 100)));
      return (
        <div>
          <div className="part">{label}: {value} of {target} ({pct}%)</div>
          <div className="progress-wrap"><div className="progress-bar" style={{ width: pct + "%" }} /></div>
        </div>
      );
    }

    function Progress({ status }) {
      const target = status?.target_count || 1000;
      const rows = status?.rows_inserted || 0;
      const embeddings = status?.embeddings_generated || 0;
      return (
        <div>
          <ProgressBar label="Embeddings generated" value={embeddings} target={target} />
          <ProgressBar label="Rows inserted" value={rows} target={target} />
          <div className="meta">
            {status?.step || "idle"}{status?.elapsed_seconds != null ? `, ${status.elapsed_seconds}s elapsed` : ""}
          </div>
        </div>
      );
    }

    function App() {
      const [activeTab, setActiveTab] = useState("search");
      const [query, setQuery] = useState("quiet brake pads for front wheels");
      const [limit, setLimit] = useState("6");
      const [results, setResults] = useState([]);
      const [detailsPayload, setDetailsPayload] = useState(null);
      const [health, setHealth] = useState(null);
      const [installStatus, setInstallStatus] = useState(null);
      const [loading, setLoading] = useState(false);
      const [detailsLoading, setDetailsLoading] = useState(false);
      const [error, setError] = useState("");

      const installRunning = installStatus?.status === "queued" || installStatus?.status === "running";

      async function loadHealth() {
        const response = await fetch("/api/health");
        const payload = await response.json();
        setHealth(payload);
        if (!response.ok || payload.ok === false) throw new Error(payload.error || "Health check failed");
        return payload;
      }

      async function pollInstallStatus() {
        const response = await fetch("/api/admin/install-status");
        const payload = await response.json();
        setInstallStatus(payload);
        if (payload.status === "complete" || payload.status === "failed") {
          loadHealth().catch(err => setError(err.message));
        }
        return payload;
      }

      async function search(event) {
        event?.preventDefault();
        setLoading(true);
        setError("");
        try {
          const response = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, limit: Number(limit) }),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Search failed");
          setResults(payload.results);
        } catch (err) {
          setError(err.message);
          setResults([]);
        } finally {
          setLoading(false);
        }
      }

      async function detailsSearch(event) {
        event?.preventDefault();
        setDetailsLoading(true);
        setError("");
        try {
          const response = await fetch("/api/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, limit: Number(limit), include_vectors: true }),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Details search failed");
          setDetailsPayload(payload);
        } catch (err) {
          setError(err.message);
          setDetailsPayload(null);
        } finally {
          setDetailsLoading(false);
        }
      }

      async function startInstall(reset) {
        if (reset && !window.confirm("Reinstalling drops and recreates AUTOMOTIVE_PARTS. Continue?")) return;
        setActiveTab("install");
        setError("");
        try {
          const response = await fetch("/api/admin/install", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reset }),
          });
          const payload = await response.json();
          if (!response.ok) throw new Error(payload.error || "Install failed to start");
          setInstallStatus(payload);
          pollInstallStatus();
        } catch (err) {
          setError(err.message);
        }
      }

      function useExample(value) {
        setQuery(value);
        setActiveTab("search");
      }

      useEffect(() => {
        loadHealth()
          .then(payload => {
            if (payload.installed) search();
          })
          .catch(err => setError(err.message));
        pollInstallStatus().catch(() => {});
      }, []);

      useEffect(() => {
        if (!installRunning) return;
        const timer = setInterval(() => pollInstallStatus().catch(err => setError(err.message)), 1500);
        return () => clearInterval(timer);
      }, [installRunning]);

      const sqlText = `select *
from (
    select
        id,
        part_number,
        name,
        category,
        description,
        unit_price,
        vector_distance(embedding, :query_vector, cosine) as distance
    from automotive_parts
    order by distance
)
where rownum <= :result_limit`;

      return (
        <main className="shell">
          <section className="topbar">
            <div>
              <h1>Automotive Parts Vector Search</h1>
              <p className="meta">
                Oracle VECTOR search using {health?.model || "all-MiniLM-L6-v2"} embeddings
              </p>
            </div>
            <div className="pill">
              {health ? `${health.part_count || 0}/${health.target_count || 1000} rows indexed` : "Checking index"}
            </div>
          </section>

          <nav className="tabs" aria-label="App sections">
            <TabButton id="search" activeTab={activeTab} setActiveTab={setActiveTab}>Search</TabButton>
            <TabButton id="install" activeTab={activeTab} setActiveTab={setActiveTab}>Install/Reinstall</TabButton>
            <TabButton id="details" activeTab={activeTab} setActiveTab={setActiveTab}>Details</TabButton>
          </nav>

          {error && <div className="notice"><div><strong>Error</strong><div className="meta">{error}</div></div></div>}

          {activeTab === "search" && (
            <section className="panel">
              <InstallNotice health={health} startInstall={startInstall} />
              <SearchForm query={query} setQuery={setQuery} limit={limit} setLimit={setLimit} onSubmit={search} loading={loading || !health?.installed} />
              <div className="toolbar">
                {EXAMPLES.map(example => <button key={example} className="secondary" onClick={() => useExample(example)}>{example}</button>)}
              </div>
              <div className="status">{results.length ? `${results.length} nearest parts by cosine distance` : ""}</div>
              <section className="grid">
                {results.map(part => <ResultCard key={part.id} part={part} />)}
              </section>
            </section>
          )}

          {activeTab === "install" && (
            <section className="panel install-layout">
              <div className="card">
                <h2>Install/Reinstall Data</h2>
                <p className="desc">
                  Create the demo table, generate local embeddings, and seed at least 1,000 automotive parts.
                  Reinstall drops and rebuilds only the demo table.
                </p>
                <div className="toolbar">
                  <button className="primary" disabled={installRunning} onClick={() => startInstall(false)}>Install Data</button>
                  <button className="danger" disabled={installRunning} onClick={() => startInstall(true)}>Reinstall Data</button>
                </div>
                {installStatus && (
                  <div>
                    <Progress status={installStatus} />
                    <p className="meta">{installStatus.message || installStatus.status}</p>
                  </div>
                )}
              </div>
              <aside className="card">
                <h3>Status</h3>
                <dl className="kv">
                  <dt>Table</dt><dd>{health?.table_name || "AUTOMOTIVE_PARTS"}</dd>
                  <dt>State</dt><dd>{health?.installed ? "Installed" : "Not installed"}</dd>
                  <dt>Rows</dt><dd>{health ? `${health.part_count || 0} of ${health.target_count || 1000}` : "Unknown"}</dd>
                  <dt>Job</dt><dd>{installStatus?.status || "idle"}</dd>
                  <dt>Step</dt><dd>{installStatus?.step || "idle"}</dd>
                  <dt>Vectorized</dt><dd>{installStatus?.embeddings_generated || 0}</dd>
                  <dt>Elapsed</dt><dd>{installStatus?.elapsed_seconds != null ? `${installStatus.elapsed_seconds}s` : "0s"}</dd>
                </dl>
              </aside>
            </section>
          )}

          {activeTab === "details" && (
            <section className="panel">
              <InstallNotice health={health} startInstall={startInstall} />
              <div className="details-layout">
                <div>
                  <SearchForm query={query} setQuery={setQuery} limit={limit} setLimit={setLimit} onSubmit={detailsSearch} loading={detailsLoading || !health?.installed} buttonLabel="Inspect" />
                  {detailsPayload?.query_vector && (
                    <div className="card">
                      <h3>Query Vector</h3>
                      <p className="desc">
                        Lower cosine distance means the returned row is closer to this query embedding.
                        Vectors are normalized, quantized, and stored as VECTOR({detailsPayload.embedding_dims}, {detailsPayload.embedding_vector_type}).
                      </p>
                      <VectorPreview label="Query vector" vector={detailsPayload.query_vector} />
                    </div>
                  )}
                  <section className="grid" style={{ marginTop: "12px" }}>
                    {(detailsPayload?.results || []).map(part => <ResultCard key={part.id} part={part} details />)}
                  </section>
                </div>
                <aside>
                  <div className="card">
                    <h3>Dataset</h3>
                    <dl className="kv">
                      <dt>Model</dt><dd>{health?.model || "all-MiniLM-L6-v2"}</dd>
                      <dt>Dimensions</dt><dd>{health?.embedding_dims || 384}</dd>
                      <dt>Vector type</dt><dd>{health?.embedding_vector_type || "int8"}</dd>
                      <dt>Rows</dt><dd>{health ? `${health.part_count || 0}` : "Unknown"}</dd>
                    </dl>
                  </div>
                  <pre className="sql">{sqlText}</pre>
                </aside>
              </div>
            </section>
          )}
        </main>
      );
    }

    ReactDOM.createRoot(document.getElementById("root")).render(<App />);
  </script>
</body>
</html>
"""


def get_connection() -> oracledb.Connection:
    missing = [name for name, value in (("ORACLE_USER", USERNAME), ("ORACLE_PASSWORD", PASSWORD), ("ORACLE_DSN", DSN)) if not value]
    if missing:
        raise RuntimeError(f"Missing required environment variable(s): {', '.join(missing)}")
    return oracledb.connect(user=USERNAME, password=PASSWORD, dsn=DSN)


def embedding_text(part: dict[str, Any]) -> str:
    return f"{part['name']}. Category: {part['category']}. Description: {part['description']}"


class Embedder:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self._model: Any | None = None

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def encode(self, text: str) -> array.array:
        vector = self.model.encode(text, normalize_embeddings=True)
        return quantize_embedding(vector.tolist())

    def encode_many(self, texts: list[str]) -> list[array.array]:
        vectors = self.model.encode(texts, normalize_embeddings=True, batch_size=64, show_progress_bar=False)
        return [quantize_embedding(vector.tolist()) for vector in vectors]


embedder = Embedder(MODEL_NAME)


def quantize_embedding(vector: list[float]) -> array.array:
    return array.array("b", [max(-127, min(127, round(value * 127))) for value in vector])


def vector_to_json(vector: Any) -> list[int]:
    if vector is None:
        return []
    if isinstance(vector, array.array):
        return list(vector)
    if isinstance(vector, bytes):
        return [value - 256 if value > 127 else value for value in vector]
    if isinstance(vector, memoryview):
        return vector_to_json(vector.tobytes())
    if isinstance(vector, list):
        return [int(value) for value in vector]
    if isinstance(vector, tuple):
        return [int(value) for value in vector]
    return [int(value) for value in vector]


def execute_ddl(cursor: oracledb.Cursor, ddl: str, ignored_errors: tuple[str, ...] = ()) -> None:
    try:
        cursor.execute(ddl)
    except oracledb.Error as exc:
        message = str(exc)
        if not any(error in message for error in ignored_errors):
            raise


def reset_schema(connection: oracledb.Connection) -> None:
    with connection.cursor() as cursor:
        execute_ddl(cursor, f"drop table {TABLE_NAME} purge", ("ORA-00942",))
    connection.commit()


def ensure_schema(connection: oracledb.Connection) -> None:
    with connection.cursor() as cursor:
        execute_ddl(
            cursor,
            f"""
            create table {TABLE_NAME} (
                id number generated by default on null as identity primary key,
                part_number varchar2(40) not null unique,
                name varchar2(200) not null,
                category varchar2(80) not null,
                description varchar2(1000) not null,
                unit_price number(10, 2) not null,
                embedding vector({EMBEDDING_DIMS}, {EMBEDDING_VECTOR_TYPE}) not null
            )
            """,
            ("ORA-00955",),
        )
    connection.commit()


def table_exists(connection: oracledb.Connection) -> bool:
    with connection.cursor() as cursor:
        cursor.execute(
            "select count(*) from user_tables where table_name = :table_name",
            table_name=TABLE_NAME.upper(),
        )
        return int(cursor.fetchone()[0]) > 0


def seed_parts(connection: oracledb.Connection, progress: Callable[[str, int, int, str], None] | None = None) -> int:
    parts = build_inventory_parts()
    rows_inserted = 0
    embeddings_generated = 0
    batch_size = 64
    merge_sql = f"""
        merge into {TABLE_NAME} dest
        using (
            select
                :part_number part_number,
                :name name,
                :category category,
                :description description,
                :unit_price unit_price,
                :embedding embedding
            from dual
        ) src
        on (dest.part_number = src.part_number)
        when matched then update set
            dest.name = src.name,
            dest.category = src.category,
            dest.description = src.description,
            dest.unit_price = src.unit_price,
            dest.embedding = src.embedding
        when not matched then insert (
            part_number, name, category, description, unit_price, embedding
        ) values (
            src.part_number, src.name, src.category, src.description, src.unit_price, src.embedding
        )
    """
    for start in range(0, len(parts), batch_size):
        batch = parts[start : start + batch_size]
        if progress:
            progress(
                "generating embeddings",
                embeddings_generated,
                rows_inserted,
                f"Vectorizing rows {start + 1}-{start + len(batch)}",
            )
        embeddings = embedder.encode_many([embedding_text(part) for part in batch])
        embeddings_generated += len(embeddings)
        if progress:
            progress(
                "generating embeddings",
                embeddings_generated,
                rows_inserted,
                f"Generated embeddings for {embeddings_generated} of {len(parts)} rows",
            )
        rows = [
            {
                **part,
                "embedding": embedding,
            }
            for part, embedding in zip(batch, embeddings)
        ]
        if progress:
            progress("inserting rows", embeddings_generated, rows_inserted, f"Inserting rows {start + 1}-{start + len(batch)}")
        with connection.cursor() as cursor:
            cursor.executemany(merge_sql, rows)
        connection.commit()
        rows_inserted += len(rows)
        if progress:
            progress("inserting rows", embeddings_generated, rows_inserted, f"Inserted {rows_inserted} of {len(parts)} rows")
    return rows_inserted


def count_parts(connection: oracledb.Connection) -> int:
    if not table_exists(connection):
        return 0
    with connection.cursor() as cursor:
        cursor.execute(f"select count(*) from {TABLE_NAME}")
        return int(cursor.fetchone()[0])


def search_parts(connection: oracledb.Connection, query: str, limit: int, include_vectors: bool = False) -> dict[str, Any]:
    if not table_exists(connection) or count_parts(connection) < INVENTORY_TARGET:
        raise RuntimeError(f"{TABLE_NAME} is not installed. Install data before searching.")
    vector = embedder.encode(query)
    embedding_select = ", embedding" if include_vectors else ""
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            select *
            from (
                select
                    id,
                    part_number,
                    name,
                    category,
                    description,
                    unit_price,
                    vector_distance(embedding, :query_vector, cosine) as distance
                    {embedding_select}
                from {TABLE_NAME}
                order by distance
            )
            where rownum <= :result_limit
            """,
            query_vector=vector,
            result_limit=max(1, min(limit, 25)),
        )
        results = []
        for row in cursor.fetchall():
            result = {
                "id": int(row[0]),
                "part_number": row[1],
                "name": row[2],
                "category": row[3],
                "description": row[4],
                "unit_price": float(row[5]),
                "distance": float(row[6]),
            }
            if include_vectors:
                result["embedding"] = vector_to_json(row[7])
            results.append(result)
        payload = {
            "query": query,
            "score_type": "cosine_distance",
            "results": results,
        }
        if include_vectors:
            payload["query_vector"] = vector_to_json(vector)
            payload["embedding_dims"] = EMBEDDING_DIMS
            payload["embedding_vector_type"] = EMBEDDING_VECTOR_TYPE
        return payload


def initialize_database(reset: bool) -> None:
    with get_connection() as connection:
        if reset:
            reset_schema(connection)
        ensure_schema(connection)
        if not reset and count_parts(connection) >= INVENTORY_TARGET:
            return
        seed_parts(connection)


def health_payload(connection: oracledb.Connection) -> dict[str, Any]:
    part_count = count_parts(connection)
    return {
        "ok": True,
        "model": MODEL_NAME,
        "embedding_dims": EMBEDDING_DIMS,
        "embedding_vector_type": EMBEDDING_VECTOR_TYPE,
        "table_name": TABLE_NAME,
        "installed": table_exists(connection) and part_count >= INVENTORY_TARGET,
        "part_count": part_count,
        "target_count": INVENTORY_TARGET,
    }


def update_install_status(**values: Any) -> None:
    with INSTALL_STATUS_LOCK:
        INSTALL_STATUS.update(values)


def current_install_status() -> dict[str, Any]:
    with INSTALL_STATUS_LOCK:
        return dict(INSTALL_STATUS)


def start_install_job(reset: bool) -> dict[str, Any]:
    status = current_install_status()
    if status.get("status") in {"queued", "running"}:
        return {
            "ok": False,
            "status": status.get("status"),
            "job_id": status.get("job_id"),
            "error": "An install job is already running.",
        }

    job_id = f"install-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    update_install_status(
        ok=True,
        job_id=job_id,
        status="queued",
        step="queued",
        rows_inserted=0,
        embeddings_generated=0,
        target_count=INVENTORY_TARGET,
        part_count=0,
        message="Install job queued.",
        error=None,
        reset=reset,
    )
    thread = threading.Thread(target=run_install_job, args=(job_id, reset), daemon=True)
    thread.start()
    return {"ok": True, "job_id": job_id, "status": "queued"}


def run_install_job(job_id: str, reset: bool) -> None:
    started_at = time.time()

    def progress(step: str, embeddings_generated: int, rows_inserted: int, message: str) -> None:
        elapsed_seconds = round(time.time() - started_at, 1)
        update_install_status(
            ok=True,
            job_id=job_id,
            status="running",
            step=step,
            embeddings_generated=embeddings_generated,
            rows_inserted=rows_inserted,
            target_count=INVENTORY_TARGET,
            elapsed_seconds=elapsed_seconds,
            message=message,
            reset=reset,
        )

    try:
        progress("connecting", 0, 0, "Connecting to Oracle Database")
        with get_connection() as connection:
            if reset:
                progress("dropping table", 0, 0, f"Dropping {TABLE_NAME}")
                reset_schema(connection)
            progress("creating table", 0, 0, f"Creating {TABLE_NAME} if needed")
            ensure_schema(connection)
            current_count = count_parts(connection)
            if not reset and current_count >= INVENTORY_TARGET:
                update_install_status(
                    ok=True,
                    job_id=job_id,
                    status="complete",
                    step="complete",
                    embeddings_generated=current_count,
                    rows_inserted=current_count,
                    target_count=INVENTORY_TARGET,
                    part_count=current_count,
                    elapsed_seconds=round(time.time() - started_at, 1),
                    message=f"{TABLE_NAME} already has {current_count} rows.",
                    reset=reset,
                    error=None,
                )
                return
            seed_parts(connection, progress)
            final_count = count_parts(connection)
            update_install_status(
                ok=True,
                job_id=job_id,
                status="complete",
                step="complete",
                embeddings_generated=final_count,
                rows_inserted=final_count,
                target_count=INVENTORY_TARGET,
                part_count=final_count,
                elapsed_seconds=round(time.time() - started_at, 1),
                message=f"Installed {final_count} rows.",
                reset=reset,
                error=None,
            )
    except Exception as exc:
        update_install_status(
            ok=False,
            job_id=job_id,
            status="failed",
            elapsed_seconds=round(time.time() - started_at, 1),
            error=str(exc),
            message=str(exc),
            reset=reset,
        )


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "AutomotivePartsVectorSearch/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), format % args))

    def read_json(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length == 0:
            return {}
        return json.loads(self.rfile.read(content_length).decode("utf-8"))

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self) -> None:
        body = HTML.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html()
            return
        if parsed.path == "/api/health":
            try:
                with get_connection() as connection:
                    self.send_json(health_payload(connection))
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if parsed.path == "/api/admin/install-status":
            self.send_json(current_install_status())
            return
        if parsed.path == "/api/search":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0].strip()
            limit = int(params.get("limit", ["6"])[0])
            if not query:
                self.send_json({"error": "Missing q query parameter"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_search(query, limit, include_vectors=params.get("include_vectors", ["false"])[0].lower() == "true")
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/admin/install":
            try:
                payload = self.read_json()
                response = start_install_job(reset=bool(payload.get("reset", False)))
                status = HTTPStatus.OK if response["ok"] else HTTPStatus.CONFLICT
                self.send_json(response, status)
            except json.JSONDecodeError:
                self.send_json({"ok": False, "error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                self.send_json({"ok": False, "error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path != "/api/search":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            payload = self.read_json()
            query = str(payload.get("query", "")).strip()
            limit = int(payload.get("limit", 6))
            include_vectors = bool(payload.get("include_vectors", False))
            if not query:
                self.send_json({"error": "Missing query"}, HTTPStatus.BAD_REQUEST)
                return
            self.handle_search(query, limit, include_vectors)
        except json.JSONDecodeError:
            self.send_json({"error": "Invalid JSON"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def handle_search(self, query: str, limit: int, include_vectors: bool = False) -> None:
        with get_connection() as connection:
            self.send_json(search_parts(connection, query, limit, include_vectors))


def serve(host: str, port: int) -> None:
    server = ThreadingHTTPServer((host, port), RequestHandler)
    print(f"Serving Automotive Parts Vector Search at http://{host}:{port}")
    print("REST endpoints: GET /api/health, POST /api/search, POST /api/admin/install")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server")
    finally:
        server.server_close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Automotive parts vector search sample for Oracle Database 26ai.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8088)
    parser.add_argument("--reset", action="store_true", help="Drop and recreate the sample table before seeding.")
    parser.add_argument("--init-only", action="store_true", help="Create and seed the table, then exit.")
    parser.add_argument("--auto-init", action="store_true", help="Create and seed the table before serving the web app.")
    args = parser.parse_args()

    try:
        if args.init_only or args.reset or args.auto_init:
            initialize_database(reset=args.reset)
        if args.init_only:
            with get_connection() as connection:
                print(f"Initialized {TABLE_NAME} with {count_parts(connection)} parts.")
            return 0
        serve(args.host, args.port)
        return 0
    except oracledb.Error as exc:
        print(f"Oracle error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
