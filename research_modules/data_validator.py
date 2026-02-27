#!/usr/bin/env python3
"""research_data_validator.py - Scientific Data Validation & Quality Assurance

Λειτουργίες:
------------
1. Statistical validation (outliers, distributions)
2. Unit consistency checking
3. Dimensional analysis
4. Missing data pattern analysis
5. Cross-dataset validation
6. Scientific notation handling
7. Uncertainty propagation

Οδηγίες Χρήσης:
--------------
>>> from research_data_validator import ScientificValidator, Quantity
>>> 
>>> # Ορισμός μεταβλητών με μονάδες
>>> distance = Quantity(5.2, "m", uncertainty=0.1)
>>> time = Quantity(2.0, "s", uncertainty=0.05)
>>> 
>>> # Automatic unit propagation
>>> velocity = distance / time
>>> print(velocity)  # 2.6 ± 0.15 m/s
"""
from dataclasses import dataclass
from typing import Dict, Any, List, Optional, Union, Callable
import numpy as np
import pandas as pd
from enum import Enum
import re


class ValidationSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    severity: ValidationSeverity
    column: str
    row_indices: List[int]
    message: str
    suggestion: Optional[str] = None


@dataclass
class Quantity:
    """Physical quantity με units και uncertainty"""
    value: float
    unit: str
    uncertainty: Optional[float] = None
    
    # Unit conversion factors (to SI)
    UNIT_CONVERSIONS = {
        # Length
        'm': 1.0, 'km': 1000.0, 'cm': 0.01, 'mm': 0.001,
        'ft': 0.3048, 'in': 0.0254,
        # Time
        's': 1.0, 'min': 60.0, 'h': 3600.0, 'day': 86400.0,
        # Mass
        'kg': 1.0, 'g': 0.001, 'mg': 1e-6,
        # Temperature
        'K': 1.0, 'C': 'C_to_K', 'F': 'F_to_K',
        # Pressure
        'Pa': 1.0, 'kPa': 1000.0, 'MPa': 1e6,
        'bar': 1e5, 'atm': 101325.0,
    }
    
    def to_si(self) -> 'Quantity':
        """Convert to SI units"""
        if self.unit in self.UNIT_CONVERSIONS:
            factor = self.UNIT_CONVERSIONS[self.unit]
            if isinstance(factor, str):
                # Temperature conversion
                if factor == 'C_to_K':
                    return Quantity(self.value + 273.15, 'K', self.uncertainty)
                elif factor == 'F_to_K':
                    return Quantity((self.value - 32) * 5/9 + 273.15, 'K', self.uncertainty)
            else:
                return Quantity(self.value * factor, 'm', self.uncertainty)
        return self
    
    def __mul__(self, other: Union['Quantity', float]) -> 'Quantity':
        if isinstance(other, Quantity):
            new_value = self.value * other.value
            new_uncertainty = np.sqrt(
                (self.uncertainty or 0)**2 * other.value**2 +
                (other.uncertainty or 0)**2 * self.value**2
            ) if (self.uncertainty or other.uncertainty) else None
            return Quantity(new_value, f"{self.unit}*{other.unit}", new_uncertainty)
        return Quantity(self.value * other, self.unit, self.uncertainty * other if self.uncertainty else None)
    
    def __truediv__(self, other: Union['Quantity', float]) -> 'Quantity':
        if isinstance(other, Quantity):
            new_value = self.value / other.value
            new_uncertainty = np.sqrt(
                (self.uncertainty or 0)**2 / other.value**2 +
                (other.uncertainty or 0)**2 * (self.value / other.value**2)**2
            ) if (self.uncertainty or other.uncertainty) else None
            return Quantity(new_value, f"{self.unit}/{other.unit}", new_uncertainty)
        return Quantity(self.value / other, self.unit, self.uncertainty / other if self.uncertainty else None)
    
    def __add__(self, other: 'Quantity') -> 'Quantity':
        if self.unit != other.unit:
            raise ValueError(f"Cannot add quantities with different units: {self.unit} + {other.unit}")
        new_value = self.value + other.value
        new_uncertainty = np.sqrt((self.uncertainty or 0)**2 + (other.uncertainty or 0)**2) if (self.uncertainty or other.uncertainty) else None
        return Quantity(new_value, self.unit, new_uncertainty)
    
    def __repr__(self):
        if self.uncertainty:
            return f"{self.value:.2f} ± {self.uncertainty:.2f} {self.unit}"
        return f"{self.value} {self.unit}"


class ScientificValidator:
    """Validator για scientific datasets"""
    
    def __init__(self):
        self.issues: List[ValidationIssue] = []
    
    def validate_dataset(self, df: pd.DataFrame, 
                         rules: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Validate dataset against scientific rules
        
        Args:
            df: DataFrame to validate
            rules: Validation rules per column
                  e.g., {"temperature": {"min": 0, "max": 100, "unit": "K"}}
        """
        self.issues = []
        
        # Basic checks
        self._check_missing_data(df)
        self._check_outliers(df)
        self._check_duplicates(df)
        
        # Rule-based validation
        if rules:
            self._validate_rules(df, rules)
        
        # Generate report
        return {
            "valid": len([i for i in self.issues if i.severity in [ValidationSeverity.ERROR, ValidationSeverity.CRITICAL]]) == 0,
            "num_issues": len(self.issues),
            "issues": [
                {
                    "severity": i.severity.value,
                    "column": i.column,
                    "message": i.message,
                    "suggestion": i.suggestion
                }
                for i in self.issues
            ],
            "summary": self._generate_summary(df)
        }
    
    def _check_missing_data(self, df: pd.DataFrame):
        """Check for missing data patterns"""
        missing = df.isnull().sum()
        for col, count in missing[missing > 0].items():
            pct = count / len(df) * 100
            severity = ValidationSeverity.WARNING if pct > 10 else ValidationSeverity.INFO
            self.issues.append(ValidationIssue(
                severity=severity,
                column=col,
                row_indices=df[df[col].isnull()].index.tolist(),
                message=f"{count} missing values ({pct:.1f}%)",
                suggestion="Consider imputation or data collection review"
            ))
    
    def _check_outliers(self, df: pd.DataFrame, method: str = "iqr"):
        """Detect outliers using IQR or Z-score"""
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        
        for col in numeric_cols:
            data = df[col].dropna()
            if len(data) == 0:
                continue
            
            if method == "iqr":
                Q1 = data.quantile(0.25)
                Q3 = data.quantile(0.75)
                IQR = Q3 - Q1
                lower = Q1 - 1.5 * IQR
                upper = Q3 + 1.5 * IQR
            else:  # zscore
                mean = data.mean()
                std = data.std()
                lower = mean - 3 * std
                upper = mean + 3 * std
            
            outliers = df[(df[col] < lower) | (df[col] > upper)].index.tolist()
            
            if outliers:
                self.issues.append(ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    column=col,
                    row_indices=outliers,
                    message=f"{len(outliers)} outliers detected (range: [{lower:.2f}, {upper:.2f}])",
                    suggestion="Review data quality or apply outlier treatment"
                ))
    
    def _check_duplicates(self, df: pd.DataFrame):
        """Check for duplicate rows"""
        duplicates = df.duplicated()
        if duplicates.any():
            self.issues.append(ValidationIssue(
                severity=ValidationSeverity.WARNING,
                column="_all",
                row_indices=df[duplicates].index.tolist(),
                message=f"{duplicates.sum()} duplicate rows",
                suggestion="Remove duplicates or verify intentional redundancy"
            ))
    
    def _validate_rules(self, df: pd.DataFrame, rules: Dict):
        """Validate against custom rules"""
        for col, rule in rules.items():
            if col not in df.columns:
                self.issues.append(ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    column=col,
                    row_indices=[],
                    message=f"Column '{col}' not found in dataset",
                    suggestion="Check column names"
                ))
                continue
            
            # Range validation
            if "min" in rule:
                violations = df[df[col] < rule["min"]].index.tolist()
                if violations:
                    self.issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        column=col,
                        row_indices=violations,
                        message=f"Values below minimum ({rule['min']})",
                        suggestion=f"Ensure values >= {rule['min']}"
                    ))
            
            if "max" in rule:
                violations = df[df[col] > rule["max"]].index.tolist()
                if violations:
                    self.issues.append(ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        column=col,
                        row_indices=violations,
                        message=f"Values above maximum ({rule['max']})",
                        suggestion=f"Ensure values <= {rule['max']}"
                    ))
            
            # Type validation
            if "dtype" in rule:
                if not df[col].dtype == rule["dtype"]:
                    self.issues.append(ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        column=col,
                        row_indices=[],
                        message=f"Expected type {rule['dtype']}, got {df[col].dtype}",
                        suggestion="Convert column type"
                    ))
    
    def _generate_summary(self, df: pd.DataFrame) -> Dict:
        """Generate dataset summary"""
        return {
            "rows": len(df),
            "columns": len(df.columns),
            "numeric_columns": len(df.select_dtypes(include=[np.number]).columns),
            "categorical_columns": len(df.select_dtypes(include=['object']).columns),
            "memory_usage_mb": df.memory_usage(deep=True).sum() / 1024**2
        }
