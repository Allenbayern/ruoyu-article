#!/usr/bin/env python3
"""Validate completed article drafts for controlled-004."""
import json, os, sys, re
from pathlib import Path

RUN_DIR = Path("/home/allen/Projects/ruoyu-film-daily/runs/2026-07-27/controlled-004")
SLOTS = ["A", "B", "C"]
OK = 0; ERR = 1

def chinese_count(text: str) -> int:
    return len(re.sub(r"[^\u4e00-\u9fff]", "", text))

def validate_slot(slot: str) -> dict:
    results = {"slot": slot, "errors": [], "char_count": 0}
    art_dir = RUN_DIR / "articles" / slot
    
    md_path = art_dir / "article-draft.md"
    gate_path = art_dir / "article-gate.json"
    
    if not md_path.exists():
        results["errors"].append("MISSING: article-draft.md")
        return results
    if not gate_path.exists():
        results["errors"].append("MISSING: article-gate.json")
        return results
    
    # Read and check character count
    text = md_path.read_text(encoding="utf-8")
    char_count = chinese_count(text)
    results["char_count"] = char_count
    
    if char_count < 1500:
        results["errors"].append(f"CHAR_COUNT_TOO_LOW: {char_count} (need >= 1500)")
    elif char_count > 2200:
        results["errors"].append(f"CHAR_COUNT_TOO_HIGH: {char_count} (need <= 2200)")
    
    # Read gate
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    
    # Check required fields
    for field in ["article_id", "slot", "title", "claim_coverage", "claim_mappings", "concrete_support_types", "html_delivery_state", "publication_authorization"]:
        if field not in gate:
            results["errors"].append(f"MISSING_GATE_FIELD: {field}")
    
    # Title length
    title = gate.get("title", "")
    title_chars = chinese_count(title)
    if title_chars > 30:
        results["errors"].append(f"TITLE_TOO_LONG: {title_chars} chars")
    
    # Claim coverage
    if gate.get("claim_coverage") != "complete":
        results["errors"].append("CLAIM_COVERAGE_NOT_COMPLETE")
    
    # Claim mappings
    mappings = gate.get("claim_mappings", [])
    if not isinstance(mappings, list) or len(mappings) == 0:
        results["errors"].append("CLAIM_MAPPINGS_EMPTY")
    
    # Concrete support types
    support = gate.get("concrete_support_types", [])
    if len(support) < 2:
        results["errors"].append(f"INSUFFICIENT_CONCRETE_SUPPORT: {len(support)} types")
    
    # HTML delivery state
    if gate.get("html_delivery_state") not in ("withheld", "not_requested"):
        results["errors"].append("HTML_NOT_WITHHELD")
    
    # Publication authorization
    if gate.get("publication_authorization") != "not_authorized":
        results["errors"].append("PUBLICATION_NOT_UNAUTHORIZED")
    
    return results

def main():
    all_errors = 0
    for slot in SLOTS:
        r = validate_slot(slot)
        status = "PASS" if not r["errors"] else "FAIL"
        print(f"Slot {slot}: {status} ({r['char_count']} chars)")
        for e in r["errors"]:
            print(f"  - {e}")
            all_errors += 1
    
    if all_errors > 0:
        print(f"\nTOTAL ERRORS: {all_errors}")
        sys.exit(ERR)
    else:
        print("\nALL SLOTS VALID")
        sys.exit(OK)

if __name__ == "__main__":
    main()
