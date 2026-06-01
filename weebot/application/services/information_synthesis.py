"""
Information Synthesis System for Weebot

This module provides capabilities for synthesizing information from multiple sources
into coherent, well-structured outputs.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
from datetime import datetime
import logging
from abc import ABC, abstractmethod
import re
from collections import defaultdict

from weebot.application.services.multi_source_research import ResearchResult
from weebot.application.services.source_credibility_assessment import CredibilityAssessment, CredibilityScore


class SynthesisType(Enum):
    """Types of information synthesis."""
    SUMMARY = "summary"
    COMPARISON = "comparison"
    ANALYSIS = "analysis"
    REPORT = "report"
    ARGUMENT_SYNTHESIS = "argument_synthesis"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    TIMELINE = "timeline"
    FAQ = "faq"


class SynthesisQuality(Enum):
    """Quality levels for synthesized information."""
    EXCELLENT = "excellent"  # 0.9-1.0
    GOOD = "good"           # 0.7-0.89
    FAIR = "fair"           # 0.5-0.69
    POOR = "poor"           # 0.3-0.49
    VERY_POOR = "very_poor"  # 0.0-0.29


@dataclass
class SynthesizedInformation:
    """Result of information synthesis."""
    synthesis_type: SynthesisType
    original_query: str
    synthesized_content: str
    supporting_evidence: List[Dict[str, Any]]  # Sources and evidence for claims
    confidence_score: float  # 0.0 to 1.0
    quality_rating: SynthesisQuality
    sources_used: List[str]  # Names of sources used
    contradictions_identified: List[Dict[str, Any]]  # Contradictions found
    gaps_identified: List[str]  # Information gaps identified
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class InformationSynthesizer(ABC):
    """Abstract base class for information synthesizers."""
    
    @abstractmethod
    async def synthesize(
        self, 
        research_results: List[ResearchResult], 
        synthesis_type: SynthesisType,
        query: str
    ) -> SynthesizedInformation:
        """Synthesize information from research results."""
        pass


class TextSummarizationSynthesizer(InformationSynthesizer):
    """Synthesizer for creating text summaries."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def synthesize(
        self, 
        research_results: List[ResearchResult], 
        synthesis_type: SynthesisType,
        query: str
    ) -> SynthesizedInformation:
        """Create a summary of the research results."""
        if not research_results:
            return SynthesizedInformation(
                synthesis_type=SynthesisType.SUMMARY,
                original_query=query,
                synthesized_content="No results to summarize.",
                supporting_evidence=[],
                confidence_score=0.0,
                quality_rating=SynthesisQuality.VERY_POOR,
                sources_used=[],
                contradictions_identified=[],
                gaps_identified=["No research results provided"],
                timestamp=datetime.now()
            )
        
        # Combine all results into a single text
        combined_text = ""
        sources_used = set()
        supporting_evidence = []
        credibility_scores = []
        
        for result in research_results:
            sources_used.update([s.name for s in result.sources_used])
            
            # Add result content to combined text
            for res_item in result.results:
                title = res_item.get("title", "")
                snippet = res_item.get("snippet", "")
                source = res_item.get("source", "unknown")
                
                if title or snippet:
                    combined_text += f"\nFrom {source}: {title} - {snippet}\n"
                    
                    # Add to supporting evidence
                    supporting_evidence.append({
                        "source": source,
                        "title": title,
                        "content": snippet,
                        "confidence": res_item.get("confidence", 0.5)
                    })
                    
                    # Track credibility scores
                    credibility_scores.append(result.confidence_score)
        
        # Generate a summary of the combined information
        summary = await self._generate_summary(combined_text, query)
        
        # Calculate overall confidence based on source credibility
        avg_credibility = sum(credibility_scores) / len(credibility_scores) if credibility_scores else 0.5
        
        # Identify contradictions
        contradictions = await self._identify_contradictions(research_results)
        
        # Identify gaps
        gaps = await self._identify_gaps(query, research_results)
        
        # Determine quality rating
        quality_rating = self._determine_quality_rating(avg_credibility, len(supporting_evidence), len(contradictions))
        
        return SynthesizedInformation(
            synthesis_type=SynthesisType.SUMMARY,
            original_query=query,
            synthesized_content=summary,
            supporting_evidence=supporting_evidence,
            confidence_score=avg_credibility,
            quality_rating=quality_rating,
            sources_used=list(sources_used),
            contradictions_identified=contradictions,
            gaps_identified=gaps,
            timestamp=datetime.now()
        )
    
    async def _generate_summary(self, text: str, query: str) -> str:
        """Generate a summary of the text relevant to the query."""
        # This is a simplified implementation
        # In a real implementation, this would use more sophisticated NLP techniques
        
        # Split text into sentences
        sentences = re.split(r'[.!?]+', text)
        
        # Filter sentences that are relevant to the query
        query_lower = query.lower()
        relevant_sentences = [
            s.strip() for s in sentences 
            if s.strip() and any(term in s.lower() for term in query_lower.split())
        ]
        
        # Limit to top 10 sentences for summary
        summary_sentences = relevant_sentences[:10]
        
        # Join sentences to form summary
        summary = ". ".join(summary_sentences) + "."
        
        # If no relevant sentences found, return a general summary
        if not summary.strip() or len(summary) < 10:
            # Just take the first few sentences as a general summary
            summary = ". ".join(sentences[:5]) + "."
        
        return summary
    
    async def _identify_contradictions(self, research_results: List[ResearchResult]) -> List[Dict[str, Any]]:
        """Identify contradictions in the research results."""
        contradictions = []
        
        # This is a simplified implementation
        # In a real implementation, this would use more sophisticated comparison techniques
        
        # For now, we'll look for opposing viewpoints in snippets
        all_snippets = []
        for result in research_results:
            for res_item in result.results:
                snippet = res_item.get("snippet", "")
                if snippet:
                    all_snippets.append({
                        "source": res_item.get("source", "unknown"),
                        "title": res_item.get("title", ""),
                        "snippet": snippet,
                        "result": result
                    })
        
        # Look for contradictory terms in snippets
        contradiction_keywords = [
            ("supports", "opposes"),
            ("increases", "decreases"),
            ("beneficial", "harmful"),
            ("effective", "ineffective"),
            ("true", "false"),
            ("correct", "incorrect"),
            ("positive", "negative")
        ]
        
        for i, item1 in enumerate(all_snippets):
            for j, item2 in enumerate(all_snippets[i+1:], i+1):
                for pos_term, neg_term in contradiction_keywords:
                    if (pos_term in item1["snippet"].lower() and neg_term in item2["snippet"].lower()) or \
                       (neg_term in item1["snippet"].lower() and pos_term in item2["snippet"].lower()):
                        contradictions.append({
                            "type": f"{pos_term} vs {neg_term}",
                            "source1": item1["source"],
                            "source2": item2["source"],
                            "content1": item1["snippet"][:100] + "...",
                            "content2": item2["snippet"][:100] + "...",
                            "confidence": 0.7  # Default confidence for detected contradiction
                        })
        
        return contradictions
    
    async def _identify_gaps(self, query: str, research_results: List[ResearchResult]) -> List[str]:
        """Identify gaps in the research."""
        gaps = []
        
        # Check if the query terms are adequately covered
        query_terms = set(query.lower().split())
        covered_terms = set()
        
        for result in research_results:
            for res_item in result.results:
                content = f"{res_item.get('title', '')} {res_item.get('snippet', '')}".lower()
                for term in query_terms:
                    if term in content:
                        covered_terms.add(term)
        
        uncovered_terms = query_terms - covered_terms
        if uncovered_terms:
            gaps.append(f"Terms not adequately covered: {', '.join(uncovered_terms)}")
        
        # Check if there are enough sources
        total_sources = sum(len(result.sources_used) for result in research_results)
        if total_sources < 3:
            gaps.append("Limited number of sources used (< 3)")
        
        # Check for temporal gaps
        dates_mentioned = []
        for result in research_results:
            for res_item in result.results:
                # Look for year patterns in content
                years = re.findall(r'\b(19|20)\d{2}\b', res_item.get('snippet', ''))
                dates_mentioned.extend(years)
        
        if not dates_mentioned:
            gaps.append("No specific dates or timeframes mentioned")
        
        return gaps
    
    def _determine_quality_rating(self, avg_credibility: float, evidence_count: int, contradiction_count: int) -> SynthesisQuality:
        """Determine quality rating based on various factors."""
        # Base rating on average credibility
        if avg_credibility >= 0.9:
            base_rating = SynthesisQuality.EXCELLENT
        elif avg_credibility >= 0.7:
            base_rating = SynthesisQuality.GOOD
        elif avg_credibility >= 0.5:
            base_rating = SynthesisQuality.FAIR
        elif avg_credibility >= 0.3:
            base_rating = SynthesisQuality.POOR
        else:
            base_rating = SynthesisQuality.VERY_POOR
        
        # Adjust for evidence count
        if evidence_count < 2:
            # Reduce rating if insufficient evidence
            if base_rating == SynthesisQuality.EXCELLENT:
                base_rating = SynthesisQuality.GOOD
            elif base_rating == SynthesisQuality.GOOD:
                base_rating = SynthesisQuality.FAIR
            elif base_rating == SynthesisQuality.FAIR:
                base_rating = SynthesisQuality.POOR
            elif base_rating == SynthesisQuality.POOR:
                base_rating = SynthesisQuality.VERY_POOR
        
        # Adjust for contradictions
        if contradiction_count > 0:
            # Reduce rating if contradictions exist
            if base_rating == SynthesisQuality.EXCELLENT:
                base_rating = SynthesisQuality.GOOD
            elif base_rating == SynthesisQuality.GOOD:
                base_rating = SynthesisQuality.FAIR
            elif base_rating == SynthesisQuality.FAIR:
                base_rating = SynthesisQuality.POOR
        
        return base_rating


class ComparativeAnalysisSynthesizer(InformationSynthesizer):
    """Synthesizer for creating comparative analyses."""
    
    def __init__(self):
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")
    
    async def synthesize(
        self, 
        research_results: List[ResearchResult], 
        synthesis_type: SynthesisType,
        query: str
    ) -> SynthesizedInformation:
        """Create a comparative analysis of the research results."""
        if not research_results:
            return SynthesizedInformation(
                synthesis_type=SynthesisType.COMPARISON,
                original_query=query,
                synthesized_content="No results to compare.",
                supporting_evidence=[],
                confidence_score=0.0,
                quality_rating=SynthesisQuality.VERY_POOR,
                sources_used=[],
                contradictions_identified=[],
                gaps_identified=["No research results provided"],
                timestamp=datetime.now()
            )
        
        # Group results by source or topic for comparison
        comparison_groups = defaultdict(list)
        sources_used = set()
        supporting_evidence = []
        
        for result in research_results:
            sources_used.update([s.name for s in result.sources_used])
            
            for res_item in result.results:
                source = res_item.get("source", "unknown")
                comparison_groups[source].append(res_item)
                
                supporting_evidence.append({
                    "source": source,
                    "title": res_item.get("title", ""),
                    "content": res_item.get("snippet", ""),
                    "confidence": res_item.get("confidence", 0.5)
                })
        
        # Generate comparative analysis
        comparison_content = await self._generate_comparison(comparison_groups, query)
        
        # Calculate confidence based on number of sources compared
        avg_credibility = sum(r.confidence_score for r in research_results) / len(research_results) if research_results else 0.5
        confidence_score = min(1.0, avg_credibility * (len(comparison_groups) / max(1, len(research_results))))
        
        # Identify contradictions between sources
        contradictions = await self._identify_comparison_contradictions(comparison_groups)
        
        # Identify gaps in comparison
        gaps = await self._identify_comparison_gaps(comparison_groups, query)
        
        # Determine quality rating
        quality_rating = self._determine_quality_rating(confidence_score, len(supporting_evidence), len(contradictions))
        
        return SynthesizedInformation(
            synthesis_type=SynthesisType.COMPARISON,
            original_query=query,
            synthesized_content=comparison_content,
            supporting_evidence=supporting_evidence,
            confidence_score=confidence_score,
            quality_rating=quality_rating,
            sources_used=list(sources_used),
            contradictions_identified=contradictions,
            gaps_identified=gaps,
            timestamp=datetime.now()
        )
    
    async def _generate_comparison(self, comparison_groups: Dict[str, List[Dict]], query: str) -> str:
        """Generate a comparative analysis of different sources."""
        comparison_parts = []
        
        # Add header
        comparison_parts.append(f"Comparative Analysis for: {query}\n")
        
        # Compare each source
        for source, items in comparison_groups.items():
            comparison_parts.append(f"\n{source.upper()}:\n")
            
            for item in items[:3]:  # Limit to first 3 items per source
                title = item.get("title", "No title")
                snippet = item.get("snippet", "No content")
                comparison_parts.append(f"  - {title}: {snippet[:200]}{'...' if len(snippet) > 200 else ''}\n")
        
        # Add comparison summary
        comparison_parts.append(f"\nSUMMARY OF DIFFERENCES:\n")
        sources = list(comparison_groups.keys())
        if len(sources) >= 2:
            comparison_parts.append(f"The {len(sources)} sources provide different perspectives on {query}:\n")
            for i, source in enumerate(sources):
                comparison_parts.append(f"  {i+1}. {source}: {len(comparison_groups[source])} references\n")
        else:
            comparison_parts.append("Only one source found, no meaningful comparison possible.\n")
        
        return "".join(comparison_parts)
    
    async def _identify_comparison_contradictions(self, comparison_groups: Dict[str, List[Dict]]) -> List[Dict[str, Any]]:
        """Identify contradictions between different sources."""
        contradictions = []
        
        sources = list(comparison_groups.keys())
        for i in range(len(sources)):
            for j in range(i+1, len(sources)):
                source1, source2 = sources[i], sources[j]
                
                # Look for contradictory statements between sources
                items1 = comparison_groups[source1]
                items2 = comparison_groups[source2]
                
                # This is a simplified check - in practice, this would require more sophisticated NLP
                for item1 in items1[:2]:  # Check first 2 items
                    for item2 in items2[:2]:  # Check first 2 items
                        content1 = item1.get("snippet", "").lower()
                        content2 = item2.get("snippet", "").lower()
                        
                        # Look for opposing claims
                        opposing_pairs = [
                            ("supports", "opposes"),
                            ("increases", "decreases"),
                            ("beneficial", "harmful")
                        ]
                        
                        for pos, neg in opposing_pairs:
                            if (pos in content1 and neg in content2) or (neg in content1 and pos in content2):
                                contradictions.append({
                                    "type": f"Contradictory claims between sources",
                                    "source1": source1,
                                    "source2": source2,
                                    "claim1": content1[:100] + "...",
                                    "claim2": content2[:100] + "...",
                                    "confidence": 0.6
                                })
        
        return contradictions
    
    async def _identify_comparison_gaps(self, comparison_groups: Dict[str, List[Dict]], query: str) -> List[str]:
        """Identify gaps in the comparative analysis."""
        gaps = []
        
        sources = list(comparison_groups.keys())
        if len(sources) < 2:
            gaps.append("Insufficient sources for meaningful comparison (< 2 sources)")
        
        # Check if all sources cover the same aspects
        all_titles = []
        for items in comparison_groups.values():
            all_titles.extend([item.get("title", "") for item in items])
        
        unique_titles_ratio = len(set(all_titles)) / len(all_titles) if all_titles else 0
        if unique_titles_ratio < 0.3:  # Less than 30% unique content
            gaps.append("High similarity between sources, limited diverse perspectives")
        
        return gaps
    
    def _determine_quality_rating(self, avg_credibility: float, evidence_count: int, contradiction_count: int) -> SynthesisQuality:
        """Determine quality rating for comparison."""
        # Similar logic to summary synthesizer but adapted for comparisons
        if avg_credibility >= 0.9:
            base_rating = SynthesisQuality.EXCELLENT
        elif avg_credibility >= 0.7:
            base_rating = SynthesisQuality.GOOD
        elif avg_credibility >= 0.5:
            base_rating = SynthesisQuality.FAIR
        elif avg_credibility >= 0.3:
            base_rating = SynthesisQuality.POOR
        else:
            base_rating = SynthesisQuality.VERY_POOR
        
        # Adjust for number of sources compared
        if len([k for k, v in locals().items() if k == 'comparison_groups']) < 2:
            if base_rating != SynthesisQuality.VERY_POOR:
                base_rating = SynthesisQuality.POOR
        
        return base_rating


class InformationSynthesisEngine:
    """Main engine for information synthesis."""
    
    def __init__(self):
        self.synthesizers: Dict[SynthesisType, InformationSynthesizer] = {
            SynthesisType.SUMMARY: TextSummarizationSynthesizer(),
            SynthesisType.COMPARISON: ComparativeAnalysisSynthesizer(),
        }
        self.logger = logging.getLogger(f"{__name__}.InformationSynthesisEngine")
    
    async def add_synthesizer(self, synthesis_type: SynthesisType, synthesizer: InformationSynthesizer):
        """Add a new synthesizer for a specific type."""
        self.synthesizers[synthesis_type] = synthesizer
    
    async def synthesize_information(
        self,
        research_results: List[ResearchResult],
        synthesis_type: SynthesisType = SynthesisType.SUMMARY,
        query: str = ""
    ) -> SynthesizedInformation:
        """Synthesize information from research results."""
        if synthesis_type not in self.synthesizers:
            raise ValueError(f"Unsupported synthesis type: {synthesis_type}")
        
        synthesizer = self.synthesizers[synthesis_type]
        
        try:
            result = await synthesizer.synthesize(research_results, synthesis_type, query)
            self.logger.info(f"Successfully synthesized information using {synthesis_type.value} approach")
            return result
        except Exception as e:
            self.logger.error(f"Error during information synthesis: {e}")
            # Return a default result in case of error
            return SynthesizedInformation(
                synthesis_type=synthesis_type,
                original_query=query,
                synthesized_content=f"Error during synthesis: {str(e)}",
                supporting_evidence=[],
                confidence_score=0.0,
                quality_rating=SynthesisQuality.VERY_POOR,
                sources_used=[],
                contradictions_identified=[],
                gaps_identified=["Synthesis failed due to error"],
                timestamp=datetime.now()
            )
    
    async def synthesize_multiple_types(
        self,
        research_results: List[ResearchResult],
        synthesis_types: List[SynthesisType],
        query: str = ""
    ) -> Dict[SynthesisType, SynthesizedInformation]:
        """Synthesize information using multiple approaches."""
        results = {}
        
        # Execute synthesis concurrently for different types
        tasks = []
        for synth_type in synthesis_types:
            task = asyncio.create_task(
                self.synthesize_information(research_results, synth_type, query)
            )
            tasks.append((synth_type, task))
        
        for synth_type, task in tasks:
            try:
                result = await task
                results[synth_type] = result
            except Exception as e:
                self.logger.error(f"Error synthesizing {synth_type.value}: {e}")
                # Add error result
                results[synth_type] = SynthesizedInformation(
                    synthesis_type=synth_type,
                    original_query=query,
                    synthesized_content=f"Error during {synth_type.value} synthesis: {str(e)}",
                    supporting_evidence=[],
                    confidence_score=0.0,
                    quality_rating=SynthesisQuality.VERY_POOR,
                    sources_used=[],
                    contradictions_identified=[],
                    gaps_identified=[f"Synthesis failed due to error: {str(e)}"],
                    timestamp=datetime.now()
                )
        
        return results
    
    async def evaluate_synthesis_quality(
        self,
        synthesized_info: SynthesizedInformation,
        original_research: List[ResearchResult]
    ) -> Dict[str, Any]:
        """Evaluate the quality of synthesized information."""
        quality_indicators = {
            "consistency_with_sources": self._check_consistency_with_sources(synthesized_info, original_research),
            "coverage_of_key_points": self._check_coverage_of_key_points(synthesized_info, original_research),
            "logical_coherence": self._check_logical_coherence(synthesized_info),
            "credibility_of_sources_used": self._check_credibility_of_sources(synthesized_info, original_research),
            "balance_of_perspectives": self._check_balance_of_perspectives(synthesized_info, original_research)
        }
        
        # Calculate overall quality score
        scores = [v for v in quality_indicators.values() if isinstance(v, (int, float))]
        overall_quality = sum(scores) / len(scores) if scores else 0.5
        
        return {
            "quality_indicators": quality_indicators,
            "overall_quality_score": overall_quality,
            "quality_rating": self._convert_score_to_rating(overall_quality),
            "recommendations": self._generate_quality_recommendations(quality_indicators)
        }
    
    def _check_consistency_with_sources(self, synthesized_info: SynthesizedInformation, original_research: List[ResearchResult]) -> float:
        """Check how consistent the synthesis is with original sources."""
        # This would involve comparing the synthesized content with original sources
        # For now, we'll return a basic score based on confidence
        return synthesized_info.confidence_score
    
    def _check_coverage_of_key_points(self, synthesized_info: SynthesizedInformation, original_research: List[ResearchResult]) -> float:
        """Check how well key points from sources are covered."""
        # Count how many of the original results are represented in the synthesis
        original_sources = set()
        for result in original_research:
            original_sources.update([s.name for s in result.sources_used])
        
        if not original_sources:
            return 0.0
        
        covered_sources = set(synthesized_info.sources_used)
        coverage_ratio = len(covered_sources.intersection(original_sources)) / len(original_sources)
        
        return min(1.0, coverage_ratio * 1.5)  # Boost slightly to account for good synthesis
    
    def _check_logical_coherence(self, synthesized_info: SynthesizedInformation) -> float:
        """Check the logical coherence of the synthesis."""
        # This would involve more sophisticated NLP analysis
        # For now, we'll use a simple heuristic based on contradictions
        contradiction_penalty = len(synthesized_info.contradictions_identified) * 0.2
        base_score = 1.0 - contradiction_penalty
        return max(0.1, base_score)
    
    def _check_credibility_of_sources_used(self, synthesized_info: SynthesizedInformation, original_research: List[ResearchResult]) -> float:
        """Check the credibility of sources used in synthesis."""
        # This would require access to credibility assessments
        # For now, we'll return the confidence score which incorporates credibility
        return synthesized_info.confidence_score
    
    def _check_balance_of_perspectives(self, synthesized_info: SynthesizedInformation, original_research: List[ResearchResult]) -> float:
        """Check if multiple perspectives are balanced in the synthesis."""
        # Count different sources to assess perspective diversity
        num_sources = len(synthesized_info.sources_used)
        if num_sources >= 3:
            return 0.9
        elif num_sources == 2:
            return 0.7
        else:
            return 0.4  # Single source = less balanced
    
    def _convert_score_to_rating(self, score: float) -> SynthesisQuality:
        """Convert numerical score to quality rating."""
        if score >= 0.9:
            return SynthesisQuality.EXCELLENT
        elif score >= 0.7:
            return SynthesisQuality.GOOD
        elif score >= 0.5:
            return SynthesisQuality.FAIR
        elif score >= 0.3:
            return SynthesisQuality.POOR
        else:
            return SynthesisQuality.VERY_POOR
    
    def _generate_quality_recommendations(self, quality_indicators: Dict[str, float]) -> List[str]:
        """Generate recommendations for improving synthesis quality."""
        recommendations = []
        
        if quality_indicators.get("consistency_with_sources", 1.0) < 0.7:
            recommendations.append("Ensure synthesized content accurately reflects source material")
        
        if quality_indicators.get("coverage_of_key_points", 1.0) < 0.7:
            recommendations.append("Include more key points from original sources")
        
        if quality_indicators.get("logical_coherence", 1.0) < 0.7:
            recommendations.append("Improve logical flow and coherence of synthesized content")
        
        if quality_indicators.get("balance_of_perspectives", 1.0) < 0.7:
            recommendations.append("Include more diverse perspectives from different sources")
        
        return recommendations


class InformationSynthesisTool:
    """Tool for synthesizing information."""
    
    def __init__(self, synthesis_engine: InformationSynthesisEngine):
        self.synthesis_engine = synthesis_engine
        self.logger = logging.getLogger(f"{__name__}.InformationSynthesisTool")
    
    async def synthesize(
        self,
        research_results: List[ResearchResult],
        synthesis_type: str = "summary",
        query: str = ""
    ) -> Dict[str, Any]:
        """Synthesize information from research results."""
        try:
            # Convert string synthesis type to enum
            try:
                synth_type = SynthesisType(synthesis_type.lower())
            except ValueError:
                self.logger.warning(f"Unknown synthesis type: {synthesis_type}, defaulting to SUMMARY")
                synth_type = SynthesisType.SUMMARY
            
            # Perform synthesis
            result = await self.synthesis_engine.synthesize_information(
                research_results=research_results,
                synthesis_type=synth_type,
                query=query
            )
            
            # Evaluate quality
            quality_evaluation = await self.synthesis_engine.evaluate_synthesis_quality(result, research_results)
            
            # Format result
            formatted_result = {
                "synthesis_type": result.synthesis_type.value,
                "original_query": result.original_query,
                "synthesized_content": result.synthesized_content,
                "confidence_score": result.confidence_score,
                "quality_rating": result.quality_rating.value,
                "sources_used": result.sources_used,
                "contradictions_identified": result.contradictions_identified,
                "gaps_identified": result.gaps_identified,
                "quality_evaluation": quality_evaluation,
                "timestamp": result.timestamp.isoformat()
            }
            
            return formatted_result
        except Exception as e:
            self.logger.error(f"Error in information synthesis: {e}")
            return {
                "error": f"Error in information synthesis: {str(e)}",
                "query": query
            }
    
    def to_param(self) -> Dict[str, Any]:
        """Convert to parameter format for tool registration."""
        return {
            "type": "function",
            "function": {
                "name": "synthesize_information",
                "description": "Synthesize information from research results into coherent output",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "research_results": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": "List of research results to synthesize"
                        },
                        "synthesis_type": {
                            "type": "string",
                            "enum": [t.value for t in SynthesisType],
                            "description": "Type of synthesis to perform",
                            "default": "summary"
                        },
                        "query": {
                            "type": "string",
                            "description": "Original query that prompted the research"
                        }
                    },
                    "required": ["research_results"]
                }
            }
        }


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # Create a synthesis engine
        engine = InformationSynthesisEngine()
        
        # Create sample research results (simulated)
        from weebot.application.services.multi_source_research import ResearchSource, ResearchSourceType
        
        sample_results = [
            ResearchResult(
                query="AI developments in 2026",
                sources_used=[
                    ResearchSource(
                        name="Tech Journal",
                        source_type=ResearchSourceType.ACADEMIC_DATABASE,
                        url="https://techjournal.com",
                        quality=SynthesisQuality.GOOD,
                        reliability_score=0.85
                    )
                ],
                results=[
                    {
                        "title": "New AI Models Released",
                        "url": "https://techjournal.com/ai-models",
                        "snippet": "Several new AI models were released in early 2026 with improved efficiency.",
                        "source": "tech_journal",
                        "confidence": 0.8
                    },
                    {
                        "title": "Industry Adoption Trends",
                        "url": "https://techjournal.com/adoption",
                        "snippet": "Companies are increasingly adopting AI solutions for automation tasks.",
                        "source": "tech_journal",
                        "confidence": 0.75
                    }
                ],
                summary="AI developments in 2026 include new models and increased adoption.",
                confidence_score=0.8,
                timestamp=datetime.now()
            )
        ]
        
        print("Performing information synthesis...")
        
        # Perform summary synthesis
        summary_result = await engine.synthesize_information(
            research_results=sample_results,
            synthesis_type=SynthesisType.SUMMARY,
            query="AI developments in 2026"
        )
        
        print(f"\nSummary synthesis result:")
        print(f"Type: {summary_result.synthesis_type.value}")
        print(f"Confidence: {summary_result.confidence_score:.2f}")
        print(f"Quality: {summary_result.quality_rating.value}")
        print(f"Content: {summary_result.synthesized_content}")
        print(f"Sources used: {summary_result.sources_used}")
        print(f"Contradictions: {len(summary_result.contradictions_identified)}")
        print(f"Gaps identified: {summary_result.gaps_identified}")
        
        # Perform comparison synthesis
        comparison_result = await engine.synthesize_information(
            research_results=sample_results,
            synthesis_type=SynthesisType.COMPARISON,
            query="AI developments in 2026"
        )
        
        print(f"\nComparison synthesis result:")
        print(f"Type: {comparison_result.synthesis_type.value}")
        print(f"Confidence: {comparison_result.confidence_score:.2f}")
        print(f"Quality: {comparison_result.quality_rating.value}")
        print(f"Content: {comparison_result.synthesized_content[:200]}...")
        
        # Evaluate synthesis quality
        quality_eval = await engine.evaluate_synthesis_quality(summary_result, sample_results)
        print(f"\nQuality evaluation:")
        print(f"Overall score: {quality_eval['overall_quality_score']:.2f}")
        print(f"Rating: {quality_eval['quality_rating'].value}")
        print(f"Recommendations: {quality_eval['recommendations']}")
    
    asyncio.run(example())