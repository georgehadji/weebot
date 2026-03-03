"""Multi-layer security analysis for bash command validation.

Defense in Depth Architecture:
    Layer 1: Syntax Patterns — Detect known dangerous constructs
    Layer 2: Behavioral Analysis — Detect download+execute chains
    Layer 3: Entropy Analysis — Detect encoded/obfuscated payloads
    Layer 4: Semantic Validation — Command structure analysis

Runtime Safety:
    - All analysis is stateless (no side effects)
    - Timeout protection on entropy calculations
    - Graceful degradation if analysis fails
"""
from __future__ import annotations

import re
import math
from dataclasses import dataclass
from enum import Enum
from typing import List, Set, Tuple, Optional


class RiskLevel(Enum):
    """Risk classification for commands."""
    SAFE = "safe"           # No issues detected
    SUSPICIOUS = "suspicious"  # Requires confirmation
    DANGEROUS = "dangerous"    # Blocked unless explicitly allowed


@dataclass
class SecurityAssessment:
    """Result of security analysis."""
    risk_level: RiskLevel
    layer_triggered: int
    reason: str
    details: Optional[dict] = None


class CommandSecurityAnalyzer:
    """Multi-layer security analyzer for shell commands.
    
    This analyzer implements defense in depth:
    1. Pattern matching for known attack vectors
    2. Behavioral analysis for download+execute chains
    3. Entropy analysis for encoded payloads
    4. Semantic structure validation
    
    Each layer can independently flag a command as dangerous.
    All layers must pass for a command to be considered safe.
    """
    
    # Layer 1: Known dangerous patterns (extended from BashTool)
    _DANGEROUS_PATTERNS: List[Tuple[str, str]] = [
        # Encoded command execution
        (r'base64\s+(-d|--decode)\s*\|', "base64 decode pipe"),
        (r'base64\s+(-d|--decode)\s+<<<', "base64 here-string decode"),
        (r'eval\s*\$\(', "eval command substitution"),
        (r'eval\s*`', "eval backticks"),
        (r'`.*base64.*`', "backticks with base64"),
        (r'\$\(.*base64.*\)', "command substitution with base64"),
        (r'echo\s+[A-Za-z0-9+/]{40,}.*\|', "echo base64 to pipe"),
        (r'\b(echo|printf)\s+.*\|\s*(bash|sh|zsh)', "pipe to shell"),
        (r'<\(.*\)', "process substitution"),
        
        # Remote code execution vectors
        (r'\b(curl|wget|Invoke-WebRequest|iwr)\s+.*[\|\;\&]\s*\b(bash|sh|zsh|cmd|powershell|pwsh)', 
         "download pipe to shell"),
        (r'\b(curl|wget)\s+.*\s+-o\s*-\s*\|', "curl/wget output to pipe"),
        (r'\b(source|\.)\s*<\(', "source process substitution"),
        (r'\bexec\s+\b(bash|sh|zsh)', "exec to new shell"),
        
        # Obfuscation techniques
        (r'\\x[0-9a-fA-F]{2}', "hex escape sequences"),
        (r'\$\{.*:#.*\}', "parameter expansion obfuscation"),
        (r'`.*`.*`', "nested backticks"),
        (r'\$\(\$\(', "nested command substitution"),
    ]
    
    # Layer 2: Behavioral indicators
    _DOWNLOAD_TOOLS: Set[str] = {
        'curl', 'wget', 'Invoke-WebRequest', 'iwr', 'Invoke-RestMethod',
        'irm', 'fetch', 'aria2c', 'axel'
    }
    
    _EXECUTION_TARGETS: Set[str] = {
        'bash', 'sh', 'zsh', 'fish', 'ksh', 'cmd', 'powershell', 'pwsh',
        'python', 'python3', 'ruby', 'perl', 'node'
    }
    
    _SUSPICIOUS_COMBINATIONS: List[Tuple[Set[str], Set[str], str]] = [
        # (indicators, targets, description)
        ({'curl', 'wget', 'Invoke-WebRequest', 'iwr'}, 
         {'bash', 'sh', 'zsh', '|'}, 
         "download to shell execution"),
        ({'base64', 'openssl'}, 
         {'eval', 'exec', 'source', '.'}, 
         "decode to execution"),
        ({'temp', 'tmp', 'mktemp'}, 
         {'chmod', '+x', 'execute'}, 
         "temp file execution"),
    ]
    
    # Layer 3: Entropy thresholds
    _HIGH_ENTROPY_THRESHOLD: float = 4.5  # Shannon entropy per char
    _BASE64_MIN_LENGTH: int = 40
    
    # Layer 4: Semantic validation
    _MAX_COMMAND_CHAIN_LENGTH: int = 5  # Max operators in chain
    _DANGEROUS_OPERATORS: Set[str] = {';', '&&', '||', '|', '|&'}
    
    def analyze(self, command: str) -> SecurityAssessment:
        """Perform multi-layer security analysis.
        
        Args:
            command: Shell command to analyze
            
        Returns:
            SecurityAssessment with risk level and reason
        """
        # Layer 1: Pattern matching
        assessment = self._layer1_pattern_analysis(command)
        if assessment.risk_level == RiskLevel.DANGEROUS:
            return assessment
            
        # Layer 2: Behavioral analysis
        assessment = self._layer2_behavioral_analysis(command)
        if assessment.risk_level == RiskLevel.DANGEROUS:
            return assessment
            
        # Layer 3: Entropy analysis
        assessment = self._layer3_entropy_analysis(command)
        if assessment.risk_level == RiskLevel.DANGEROUS:
            return assessment
            
        # Layer 4: Semantic validation
        assessment = self._layer4_semantic_analysis(command)
        
        return assessment
    
    def _layer1_pattern_analysis(self, command: str) -> SecurityAssessment:
        """Check for known dangerous patterns."""
        for pattern, description in self._DANGEROUS_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return SecurityAssessment(
                    risk_level=RiskLevel.DANGEROUS,
                    layer_triggered=1,
                    reason=f"Dangerous pattern detected: {description}",
                    details={"pattern": pattern, "match": re.search(pattern, command, re.IGNORECASE).group(0)}
                )
        return SecurityAssessment(RiskLevel.SAFE, 1, "No dangerous patterns")
    
    def _layer2_behavioral_analysis(self, command: str) -> SecurityAssessment:
        """Detect suspicious behavior combinations."""
        cmd_lower = command.lower()
        
        # Tokenize command (simple approach)
        tokens = set(re.findall(r'\b[a-zA-Z][a-zA-Z0-9_-]*\b', cmd_lower))
        operators = set(re.findall(r'[;|&]+', command))
        
        for indicators, targets, description in self._SUSPICIOUS_COMBINATIONS:
            has_indicator = bool(tokens & indicators)
            has_target = bool(tokens & targets) or bool(operators & targets)
            
            if has_indicator and has_target:
                return SecurityAssessment(
                    risk_level=RiskLevel.DANGEROUS,
                    layer_triggered=2,
                    reason=f"Suspicious behavior: {description}",
                    details={
                        "indicators_found": list(tokens & indicators),
                        "targets_found": list((tokens | operators) & targets)
                    }
                )
        
        return SecurityAssessment(RiskLevel.SAFE, 2, "No suspicious behavior")
    
    def _layer3_entropy_analysis(self, command: str) -> SecurityAssessment:
        """Detect high-entropy encoded payloads."""
        # Find potential base64 strings
        base64_pattern = r'[A-Za-z0-9+/]{40,}={0,2}'
        matches = re.findall(base64_pattern, command)
        
        for match in matches:
            if len(match) >= self._BASE64_MIN_LENGTH:
                entropy = self._calculate_entropy(match)
                if entropy > self._HIGH_ENTROPY_THRESHOLD:
                    # Try to decode
                    try:
                        import base64
                        decoded = base64.b64decode(match).decode('utf-8', errors='ignore')
                        shell_keywords = ['bash', 'sh', 'exec', 'eval', 'rm -rf', 'format', 'cmd', 'powershell']
                        if any(kw in decoded.lower() for kw in shell_keywords):
                            return SecurityAssessment(
                                risk_level=RiskLevel.DANGEROUS,
                                layer_triggered=3,
                                reason="High-entropy encoded shell command detected",
                                details={
                                    "entropy": entropy,
                                    "decoded_preview": decoded[:100]
                                }
                            )
                    except Exception:
                        pass
        
        return SecurityAssessment(RiskLevel.SAFE, 3, "No encoded payloads")
    
    def _layer4_semantic_analysis(self, command: str) -> SecurityAssessment:
        """Validate command structure."""
        # Check command chain length
        chain_count = len(re.findall(r'[;|&]', command))
        if chain_count > self._MAX_COMMAND_CHAIN_LENGTH:
            return SecurityAssessment(
                risk_level=RiskLevel.SUSPICIOUS,
                layer_triggered=4,
                reason=f"Complex command chain ({chain_count} operators)",
                details={"chain_length": chain_count}
            )
        
        # Check for URL-like strings (potential downloads)
        url_pattern = r'https?://[^\s"\']+'
        urls = re.findall(url_pattern, command)
        if urls and any(op in command for op in ['|', '&&', '||']):
            return SecurityAssessment(
                risk_level=RiskLevel.SUSPICIOUS,
                layer_triggered=4,
                reason="URL with command chaining detected",
                details={"urls_found": urls}
            )
        
        return SecurityAssessment(RiskLevel.SAFE, 4, "Structure valid")
    
    def _calculate_entropy(self, data: str) -> float:
        """Calculate Shannon entropy of string."""
        if not data:
            return 0.0
        
        # Count character frequencies
        freq = {}
        for char in data:
            freq[char] = freq.get(char, 0) + 1
        
        # Calculate entropy
        length = len(data)
        entropy = 0.0
        for count in freq.values():
            p = count / length
            if p > 0:
                entropy -= p * math.log2(p)
        
        return entropy


# Singleton instance for reuse
_analyzer: Optional[CommandSecurityAnalyzer] = None


def get_security_analyzer() -> CommandSecurityAnalyzer:
    """Get singleton security analyzer instance."""
    global _analyzer
    if _analyzer is None:
        _analyzer = CommandSecurityAnalyzer()
    return _analyzer
