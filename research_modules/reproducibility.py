#!/usr/bin/env python3
"""reproducibility.py - Reproducible Research Framework

Λειτουργίες:
------------
1. Automatic environment capture (dependencies, versions, seeds)
2. Computational graph tracking (data lineage)
3. Deterministic execution (controlled randomness)
4. Provenance recording (who, when, what, why)
5. Reproducibility reports (methods section generation)
6. Container integration (Docker/Singularity export)

Οδηγίες Χρήσης:
--------------
>>> from research_reproducibility import ReproducibilityManager, Experiment
>>> 
>>> with Experiment(
...     title="Quantum State Analysis",
...     description="Analysis of entanglement measures",
...     tags=["quantum", "entanglement", "python"]
... ) as exp:
...     # Ολα τα βήματα καταγράφονται αυτόματα
...     data = load_data("measurements.csv")
...     result = analyze(data)
...     
>>> # Generate methods section
>>> print(exp.generate_methods())
"""
import hashlib
import json
import os
import sys
import subprocess
import platform
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable
from dataclasses import dataclass, field, asdict
from contextlib import contextmanager
import inspect
import importlib
import random
import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class ProvenanceRecord:
    """Record για κάθε operation στο experiment"""
    timestamp: str
    operation: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    code_snippet: str
    file_hashes: Dict[str, str]
    execution_time_ms: float
    software_versions: Dict[str, str]


@dataclass
class ExperimentConfig:
    """Configuration για reproducible experiment"""
    title: str
    description: str
    tags: List[str] = field(default_factory=list)
    random_seed: Optional[int] = None
    capture_stdout: bool = True
    capture_packages: bool = True
    track_file_access: bool = True


class ReproducibilityManager:
    """Manager για reproducible experiments"""
    
    def __init__(self, base_dir: str = "./experiments"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.active_experiments: Dict[str, 'Experiment'] = {}
    
    def create_experiment(self, config: ExperimentConfig) -> 'Experiment':
        """Create new experiment"""
        exp = Experiment(config, self.base_dir)
        self.active_experiments[exp.exp_id] = exp
        return exp
    
    def load_experiment(self, exp_id: str) -> Optional['Experiment']:
        """Load existing experiment"""
        exp_dir = self.base_dir / exp_id
        if not exp_dir.exists():
            return None
        
        # Load configuration
        config_path = exp_dir / "config.json"
        if config_path.exists():
            config_data = json.loads(config_path.read_text())
            config = ExperimentConfig(**config_data)
            return Experiment(config, self.base_dir, exp_id=exp_id)
        return None


class Experiment:
    """Reproducible experiment context"""
    
    def __init__(self, config: ExperimentConfig, base_dir: Path, exp_id: Optional[str] = None):
        self.config = config
        self.base_dir = base_dir
        self.exp_id = exp_id or self._generate_id()
        self.work_dir = base_dir / self.exp_id
        self.work_dir.mkdir(parents=True, exist_ok=True)
        
        self.records: List[ProvenanceRecord] = []
        self.artifacts: Dict[str, Path] = {}
        self.start_time: Optional[datetime] = None
        
        # Initialize environment
        if config.random_seed:
            self._set_random_seeds(config.random_seed)
        
        # Save configuration
        self._save_config()
    
    def _generate_id(self) -> str:
        """Generate unique experiment ID"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = hashlib.sha256(
            str(datetime.now().timestamp()).encode()
        ).hexdigest()[:8]
        return f"exp_{timestamp}_{random_suffix}"
    
    def _set_random_seeds(self, seed: int):
        """Set all random seeds for reproducibility"""
        random.seed(seed)
        np.random.seed(seed)
        # Set Python hash seed
        os.environ['PYTHONHASHSEED'] = str(seed)
    
    def _save_config(self):
        """Save experiment configuration"""
        config_path = self.work_dir / "config.json"
        config_path.write_text(json.dumps(asdict(self.config), indent=2))
    
    def __enter__(self):
        """Enter experiment context"""
        self.start_time = datetime.now()
        logger.info(f"Started experiment: {self.exp_id}")
        
        # Capture environment
        if self.config.capture_packages:
            self._capture_environment()
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit experiment context"""
        if exc_type:
            logger.error(f"Experiment failed: {exc_val}")
            self._save_manifest(status="failed", error=str(exc_val))
        else:
            logger.info(f"Completed experiment: {self.exp_id}")
            self._save_manifest(status="completed")
    
    def _capture_environment(self):
        """Capture software environment"""
        env_info = {
            "python_version": sys.version,
            "platform": platform.platform(),
            "packages": self._get_package_versions()
        }
        
        env_path = self.work_dir / "environment.json"
        env_path.write_text(json.dumps(env_info, indent=2, default=str))
    
    def _get_package_versions(self) -> Dict[str, str]:
        """Get installed package versions"""
        packages = {}
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True
            )
            for line in result.stdout.split('\n'):
                if '==' in line:
                    name, version = line.strip().split('==')
                    packages[name] = version
        except Exception as e:
            logger.warning(f"Could not capture packages: {e}")
        return packages
    
    def record(self, operation: str, inputs: Dict, outputs: Dict,
               code: Optional[str] = None):
        """Record an operation"""
        
        # Get calling code if not provided
        if code is None:
            frame = inspect.currentframe().f_back
            code = inspect.getsource(frame.f_code) if frame else ""
        
        # Calculate file hashes
        file_hashes = {}
        for key, value in inputs.items():
            if isinstance(value, (str, Path)) and Path(value).exists():
                file_hashes[key] = self._hash_file(value)
        
        record = ProvenanceRecord(
            timestamp=datetime.now().isoformat(),
            operation=operation,
            inputs=inputs,
            outputs=outputs,
            code_snippet=code[:1000],  # Limit size
            file_hashes=file_hashes,
            execution_time_ms=0,  # Calculate if needed
            software_versions=self._get_package_versions()
        )
        
        self.records.append(record)
        self._save_record(record)
    
    def _hash_file(self, filepath: str) -> str:
        """Calculate file hash"""
        path = Path(filepath)
        if not path.exists():
            return ""
        
        hasher = hashlib.sha256()
        hasher.update(path.read_bytes())
        return hasher.hexdigest()
    
    def _save_record(self, record: ProvenanceRecord):
        """Save record to file"""
        records_dir = self.work_dir / "records"
        records_dir.mkdir(exist_ok=True)
        
        record_path = records_dir / f"record_{len(self.records):04d}.json"
        record_path.write_text(json.dumps(asdict(record), indent=2, default=str))
    
    def record_artifact(self, name: str, data: Any, format: str = "json"):
        """Save experiment artifact"""
        artifacts_dir = self.work_dir / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        
        artifact_path = artifacts_dir / f"{name}.{format}"
        
        if format == "json":
            artifact_path.write_text(json.dumps(data, indent=2, default=str))
        elif format == "npy" and isinstance(data, np.ndarray):
            np.save(artifact_path, data)
        else:
            artifact_path.write_bytes(str(data).encode())
        
        self.artifacts[name] = artifact_path
        return artifact_path
    
    def generate_methods(self) -> str:
        """Generate methods section from experiment records"""
        lines = [
            f"## Methods: {self.config.title}",
            "",
            self.config.description,
            "",
            "### Software Environment",
            f"- Python: {sys.version.split()[0]}",
            f"- Platform: {platform.system()} {platform.release()}",
            "",
            "### Computational Steps",
        ]
        
        for i, record in enumerate(self.records, 1):
            lines.extend([
                "",
                f"**Step {i}: {record.operation}**",
                f"- Timestamp: {record.timestamp}",
                f"- Inputs: {list(record.inputs.keys())}",
                f"- Outputs: {list(record.outputs.keys())}",
            ])
        
        lines.extend([
            "",
            "### Reproducibility",
            f"- Experiment ID: `{self.exp_id}`",
            f"- Random Seed: {self.config.random_seed or 'Not set'}",
        ])
        
        return "\n".join(lines)
    
    def export_package(self, output_path: str):
        """Export experiment as reproducible package"""
        import shutil
        
        output_path = Path(output_path)
        
        # Create archive
        shutil.make_archive(
            output_path.with_suffix(''),
            'zip',
            self.work_dir
        )
        
        logger.info(f"Exported experiment to: {output_path}")
        return output_path
    
    def _save_manifest(self, status: str, error: Optional[str] = None):
        """Save experiment manifest"""
        manifest = {
            "exp_id": self.exp_id,
            "title": self.config.title,
            "description": self.config.description,
            "status": status,
            "created_at": self.start_time.isoformat() if self.start_time else None,
            "completed_at": datetime.now().isoformat(),
            "num_records": len(self.records),
            "artifacts": list(self.artifacts.keys()),
            "error": error
        }
        
        manifest_path = self.work_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))
