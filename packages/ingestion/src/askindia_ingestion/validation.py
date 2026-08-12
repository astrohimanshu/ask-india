"""Validation suite applied to every parsed frame before it can touch the database.

Checks: declared columns present, no unexpected nulls, numeric ranges, allowed values, uniqueness
of the natural key, minimum row count. All checks run; the report lists every failure so a
quarantined batch can be diagnosed in one pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pandas as pd

if TYPE_CHECKING:
    from askindia_ingestion.contracts import DatasetSpec


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    row_count: int
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict[str, Any]:
        return {
            "row_count": self.row_count,
            "passed": self.passed,
            "checks": [c.__dict__ for c in self.checks],
        }


class ValidationFailedError(Exception):
    def __init__(self, report: ValidationReport) -> None:
        self.report = report
        names = ", ".join(f"{c.name} ({c.detail})" for c in report.failures)
        super().__init__(f"validation failed: {names}")


def validate_frame(frame: pd.DataFrame, spec: DatasetSpec) -> ValidationReport:
    report = ValidationReport(row_count=len(frame))
    checks = report.checks

    missing = [c for c in spec.column_names if c not in frame.columns]
    checks.append(Check("columns_present", not missing, f"missing: {missing}" if missing else ""))
    if missing:
        raise ValidationFailedError(report)

    checks.append(
        Check(
            "min_rows",
            len(frame) >= spec.min_rows,
            f"{len(frame)} rows < required {spec.min_rows}" if len(frame) < spec.min_rows else "",
        )
    )

    for col in spec.columns:
        series = frame[col.name]
        nulls = int(series.isna().sum())
        if not col.nullable:
            checks.append(
                Check(f"not_null:{col.name}", nulls == 0, f"{nulls} nulls" if nulls else "")
            )
        if col.min is not None or col.max is not None:
            numeric = pd.to_numeric(series, errors="coerce")
            bad_num = int((numeric.isna() & series.notna()).sum())
            checks.append(
                Check(
                    f"numeric:{col.name}", bad_num == 0, f"{bad_num} non-numeric" if bad_num else ""
                )
            )
            out = pd.Series(False, index=series.index)
            if col.min is not None:
                out |= numeric < col.min
            if col.max is not None:
                out |= numeric > col.max
            n_out = int(out.sum())
            checks.append(
                Check(
                    f"range:{col.name}",
                    n_out == 0,
                    f"{n_out} values outside [{col.min}, {col.max}]" if n_out else "",
                )
            )
        if col.allowed is not None:
            bad = series.dropna().astype(str)
            bad = bad[~bad.isin(col.allowed)]
            checks.append(
                Check(
                    f"allowed:{col.name}",
                    bad.empty,
                    f"{len(bad)} disallowed, e.g. {bad.unique()[:3].tolist()}"
                    if not bad.empty
                    else "",
                )
            )

    if spec.unique_key:
        dupes = int(frame.duplicated(subset=list(spec.unique_key)).sum())
        checks.append(
            Check(
                "unique_key",
                dupes == 0,
                f"{dupes} duplicate rows on {spec.unique_key}" if dupes else "",
            )
        )

    if not report.passed:
        raise ValidationFailedError(report)
    return report
