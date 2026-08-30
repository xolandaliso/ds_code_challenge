'''
    schema_conformance.py
    
        - scores the structure (schema) of the extracted GeoJSON features against the expected schema.
        - expected schema is defined in the `expected_schema` variable - not guessed but defined from reference data.
'''

import re
import yaml
from typing import Any
from pathlib import Path
from dataclasses import dataclass, field
from src.settings import Settings, logger
from src.extract import extract_hex_resolution8


@dataclass
class ConformanceResult:
    total_records: int
    mean_score: float
    pass_count: int
    warn_count: int
    fail_count: int
    violations: dict[str, int] = field(default_factory=dict)

    def band(self, thresholds: dict[str, float] = None) -> str:
        '''
            returns a band based on the mean score and thresholds.
            thresholds is a dict with keys 'pass', 'warn', 'fail' and values as the score thresholds.
            default thresholds are:
                pass: 0.98
                warn: 0.9
                fail: 0.0
        '''

        if thresholds is None:
            thresholds = {'pass': 0.98, 'warn': 0.9, 'fail': 0.0}
        if self.mean_score >= thresholds.get('pass', 0.98):
            return 'pass'
        elif self.mean_score >= thresholds.get('warn', 0.9):
            return 'warn'
        else:
            return 'fail'
        
    def summary(self, thresholds: dict[str, float] = None) -> str:
        '''
            returns a summary string of the conformance result.
        '''
        lines = [
            f"conformance score: {self.mean_score:.4f} ({self.band(thresholds)})",
            f"records checked: {self.total_records}",
            f"pass count: {self.pass_count}",
            f"warn count: {self.warn_count}",
            f"fail count: {self.fail_count}",
        ]
        if self.violations:
            lines.append("top violation reasons:")
            for reason, count in sorted(self.violations.items() ,key=lambda x: x[1], reverse=True):
                lines.append(f"  {reason}: {count}")
        
        return "\n".join(lines)
    
def load_schema(path: str) -> dict[str, Any]:
    '''
        load the expected schema from a yaml file.
    '''
    with open(path, 'r') as f:
        schema = yaml.safe_load(f)
    return schema


def check_property_rules(props: dict[str, Any], rules: dict[str, Any], violations: dict[str, int]) -> tuple[int, int]:
    '''
        check the properties of a feature against the rules.
        returns a score and a list of violation reasons.
    '''
    passed, total = 0, 0
    for field_name, rule in rules.items():
        total += 1
        value = props.get(field_name)

        ok = True
        if rule.get("nullable") is False and value is None:
            ok = False
            violations[f"{field_name}: missing/null"] = violations.get(f"{field_name}: missing/null", 0) + 1
        elif value is not None:
            expected_type = rule.get("type")
            type_ok = {
                "string": isinstance(value, str),
                "integer": isinstance(value, int) and not isinstance(value, bool),
                "float": isinstance(value, (int, float)) and not isinstance(value, bool),
                "boolean": isinstance(value, bool),
            }.get(expected_type, True)
            if not type_ok:
                ok = False
                violations[f"{field_name}: wrong type"] = violations.get(
                    f"{field_name}: wrong type", 0
                ) + 1
            if "allowed_values" in rule and value not in rule["allowed_values"]:
                ok = False
                violations[f"{field_name}: unexpected value"] = violations.get(f"{field_name}: unexpected value", 0) + 1
            if "pattern" in rule and isinstance(value, str) and not re.match(rule["pattern"], value):
                ok = False
                violations[f"{field_name}: pattern mismatch"] = violations.get(f"{field_name}: pattern mismatch", 0) + 1
            if "min" in rule and isinstance(value, (int, float)) and value < rule["min"]:
                ok = False
                violations[f"{field_name}: below min"] = violations.get(f"{field_name}: below min", 0) + 1
            if "max" in rule and isinstance(value, (int, float)) and value > rule["max"]:
                ok = False
                violations[f"{field_name}: above max"] = violations.get(f"{field_name}: above max", 0) + 1

        if ok:
            passed += 1
    return passed, total

def check_geometry_rules(geometry: dict[str, Any], rules: dict[str, Any], violations: dict[str, int]) -> tuple[int, int]:
    '''
        check the geometry of a feature against the rules.
        returns a score and a list of violation reasons.
    '''

    passed, total = 0, 1
    geom_type = geometry.get("type") if geometry else None
    allowed = rules.get("type", {}).get("allowed_values", [])

    if geometry is None:
        violations["geometry: missing"] = violations.get("geometry: missing", 0) + 1
        return 0, total

    coords = geometry.get("coordinates")
    min_points = rules.get("coordinates", {}).get("min_points", 3)

    def _count_points(c):
        # Polygon: [ [ [x,y], ... ] ], MultiPolygon adds one more level.
        if geom_type == "Polygon" and c:
            ring = c[0]
            return len({tuple(point) for point in ring})
        if geom_type == "MultiPolygon" and c:
            ring = c[0][0]
            return len({tuple(point) for point in ring})
        return 0

    ok = geom_type in allowed and coords is not None and _count_points(coords) >= min_points
    if not ok:
        violations["geometry: invalid/insufficient"] = violations.get("geometry: invalid/insufficient", 0) + 1
    if ok:
        passed = 1
    return passed, total

def score_features(features: list[dict[str, Any]], schema: dict[str, Any]) -> ConformanceResult:
    prop_rules = schema.get("feature_properties", {})
    geom_rules = schema.get("geometry", {})

    scores = []
    violations: dict[str, int] = {}

    for feature in features:
        props = feature.get("properties", {}) or {}
        geometry = feature.get("geometry")

        p_passed, p_total = check_property_rules(props, prop_rules, violations)
        g_passed, g_total = check_geometry_rules(geometry, geom_rules, violations)

        total_rules = p_total + g_total
        passed_rules = p_passed + g_passed
        scores.append(passed_rules / total_rules if total_rules else 1.0)

    total = len(scores)
    mean_score = sum(scores) / total if total else 0.0
    pass_count = sum(1 for s in scores if s == 1.0)
    fail_count = sum(1 for s in scores if s == 0.0)
    warn_count = total - pass_count - fail_count

    result = ConformanceResult(
        total_records=total,
        mean_score=mean_score,
        pass_count=pass_count,
        warn_count=warn_count,
        fail_count=fail_count,
        violations=violations,
    )
    logger.info("Conformance check complete: %.4f mean score over %d records", mean_score, total)
    return result


if __name__ == "__main__":

    schema = load_schema("config/hex_schema.yml")
    feats = extract_hex_resolution8()
    result = score_features(feats, schema)
    logger.info(f"Conformance summary:\n {result.summary(schema.get("score_bands"))}")

    
