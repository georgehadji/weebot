"""
Source Credibility Assessment System for Weebot

This module provides capabilities for assessing the credibility of information sources
to ensure reliable research and analysis.
"""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Protocol
from datetime import datetime, timedelta
from urllib.parse import urlparse
import logging
import aiohttp
from bs4 import BeautifulSoup

from weebot.application.services.multi_source_research import ResearchSource, ResearchSourceType


class CredibilityIndicator(Enum):
    """Indicators of source credibility."""
    AUTHOR_EXPERTISE = "author_expertise"
    PUBLICATION_REPUTATION = "publication_reputation"
    CITATION_QUALITY = "citation_quality"
    DATE_RELEVANCE = "date_relevance"
    FACT_CHECKING = "fact_checking"
    PEER_REVIEW = "peer_review"
    TRANSPARENCY = "transparency"
    BIAS_DETECTION = "bias_detection"
    DOMAIN_AUTHORITY = "domain_authority"


class CredibilityScore(Enum):
    """Credibility score ratings."""
    HIGHEST = "highest"  # 0.9-1.0
    HIGH = "high"        # 0.7-0.89
    MEDIUM = "medium"    # 0.5-0.69
    LOW = "low"          # 0.3-0.49
    LOWEST = "lowest"    # 0.0-0.29


@dataclass
class CredibilityAssessment:
    """Assessment of a source's credibility."""
    source: ResearchSource
    overall_score: float  # 0.0 to 1.0
    credibility_indicators: Dict[CredibilityIndicator, float]  # Scores for each indicator
    assessment_details: Dict[str, Any]  # Additional assessment details
    timestamp: datetime
    potential_biases: List[str]
    reliability_factors: List[str]
    verification_status: str  # "verified", "partially_verified", "unverified", "disputed"


class SourceCredibilityEvaluator:
    """Evaluates the credibility of information sources."""
    
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(f"{__name__}.SourceCredibilityEvaluator")
        
        # Define credibility weights for different source types
        self.source_type_weights = {
            ResearchSourceType.ACADEMIC_DATABASE: {"weight": 0.95, "indicators": [CredibilityIndicator.PEER_REVIEW, CredibilityIndicator.AUTHOR_EXPERTISE]},
            ResearchSourceType.WIKIPEDIA: {"weight": 0.75, "indicators": [CredibilityIndicator.COLLABORATIVE_EDITING, CredibilityIndicator.TRANSPARENCY]},
            ResearchSourceType.NEWS_API: {"weight": 0.7, "indicators": [CredibilityIndicator.PUBLICATION_REPUTATION, CredibilityIndicator.DATE_RELEVANCE]},
            ResearchSourceType.WEB_SEARCH: {"weight": 0.5, "indicators": [CredibilityIndicator.DOMAIN_AUTHORITY, CredibilityIndicator.CITATION_QUALITY]},
            ResearchSourceType.SOCIAL_MEDIA: {"weight": 0.2, "indicators": [CredibilityIndicator.BIAS_DETECTION]},
            ResearchSourceType.DOCUMENT: {"weight": 0.8, "indicators": [CredibilityIndicator.AUTHOR_EXPERTISE, CredibilityIndicator.TRANSPARENCY]},
            ResearchSourceType.DATABASE: {"weight": 0.9, "indicators": [CredibilityIndicator.AUTHOR_EXPERTISE, CredibilityIndicator.PEER_REVIEW]},
            ResearchSourceType.CUSTOM_API: {"weight": 0.6, "indicators": [CredibilityIndicator.TRANSPARENCY, CredibilityIndicator.AUTHOR_EXPERTISE]},
        }
        
        # Known credible domains
        self.credible_domains = {
            "edu", "gov", "org", "ac.uk", "nih.gov", "who.int", "nature.com", 
            "science.org", "arxiv.org", "ieee.org", "acm.org", "springer.com",
            "cambridge.org", "oxford.ac.uk", "harvard.edu", "stanford.edu",
            "mit.edu", "wikipedia.org", "britannica.com"
        }
        
        # Known potentially unreliable domains
        self.unreliable_domains = {
            "unreliable-news.com", "fake-news.net", "rumor-site.org"
        }
    
    async def initialize(self):
        """Initialize the HTTP session."""
        if not self.session:
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10)
            )
    
    async def assess_source_credibility(self, source: ResearchSource) -> CredibilityAssessment:
        """Assess the credibility of a research source."""
        await self.initialize()
        
        # Initialize scores for each indicator
        indicator_scores = {}
        
        # Evaluate each credibility indicator
        indicator_scores[CredibilityIndicator.AUTHOR_EXPERTISE] = await self._assess_author_expertise(source)
        indicator_scores[CredibilityIndicator.PUBLICATION_REPUTATION] = await self._assess_publication_reputation(source)
        indicator_scores[CredibilityIndicator.CITATION_QUALITY] = await self._assess_citation_quality(source)
        indicator_scores[CredibilityIndicator.DATE_RELEVANCE] = await self._assess_date_relevance(source)
        indicator_scores[CredibilityIndicator.PEER_REVIEW] = await self._assess_peer_review_status(source)
        indicator_scores[CredibilityIndicator.TRANSPARENCY] = await self._assess_transparency(source)
        indicator_scores[CredibilityIndicator.BIAS_DETECTION] = await self._assess_bias_detection(source)
        indicator_scores[CredibilityIndicator.DOMAIN_AUTHORITY] = await self._assess_domain_authority(source)
        
        # Calculate overall score based on source type and individual indicators
        source_type_info = self.source_type_weights.get(source.source_type, {"weight": 0.5, "indicators": []})
        base_weight = source_type_info["weight"]
        
        # Adjust score based on individual indicators
        adjusted_score = base_weight
        for indicator, score in indicator_scores.items():
            if indicator in source_type_info["indicators"]:
                # Give extra weight to indicators relevant to this source type
                adjusted_score = (adjusted_score + score) / 2
        
        # Ensure score is between 0 and 1
        overall_score = max(0.0, min(1.0, adjusted_score))
        
        # Determine potential biases
        potential_biases = await self._detect_potential_biases(source)
        
        # Determine reliability factors
        reliability_factors = await self._determine_reliability_factors(source)
        
        # Determine verification status
        verification_status = await self._determine_verification_status(source)
        
        return CredibilityAssessment(
            source=source,
            overall_score=overall_score,
            credibility_indicators=indicator_scores,
            assessment_details={
                "source_type_base_weight": base_weight,
                "individual_indicator_scores": {k.value: v for k, v in indicator_scores.items()},
            },
            timestamp=datetime.now(),
            potential_biases=potential_biases,
            reliability_factors=reliability_factors,
            verification_status=verification_status
        )
    
    async def _assess_author_expertise(self, source: ResearchSource) -> float:
        """Assess the expertise of the author/source."""
        # For academic databases, news from reputable organizations, etc., score higher
        if source.source_type in [ResearchSourceType.ACADEMIC_DATABASE, ResearchSourceType.DATABASE]:
            return 0.9
        
        # For web search results, check if we can extract author information
        if source.source_type == ResearchSourceType.WEB_SEARCH:
            # In a real implementation, we would fetch the page and analyze authorship
            # For now, return a moderate score
            return 0.6
        
        # For Wikipedia, score moderately high due to collaborative editing
        if source.source_type == ResearchSourceType.WIKIPEDIA:
            return 0.75
        
        # Default score
        return 0.5
    
    async def _assess_publication_reputation(self, source: ResearchSource) -> float:
        """Assess the reputation of the publication/source."""
        # Check if the domain is in our list of credible domains
        parsed_url = urlparse(source.url)
        domain_parts = parsed_url.netloc.split('.')
        
        # Check for credible domain endings
        for credible_domain in self.credible_domains:
            if '.'.join(domain_parts[-len(credible_domain.split('.')):]) == credible_domain:
                return 0.9
        
        # Check for potentially unreliable domains
        for unreliable_domain in self.unreliable_domains:
            if '.'.join(domain_parts[-len(unreliable_domain.split('.')):]) == unreliable_domain:
                return 0.1
        
        # Default score based on source type
        if source.source_type == ResearchSourceType.NEWS_API:
            # Check if it's a known reputable news source
            news_sources = ["bbc.co.uk", "reuters.com", "apnews.com", "nytimes.com", "washingtonpost.com"]
            for news_source in news_sources:
                if news_source in parsed_url.netloc:
                    return 0.85
        
        return 0.5
    
    async def _assess_citation_quality(self, source: ResearchSource) -> float:
        """Assess the quality of citations/references."""
        # Academic sources typically have good citations
        if source.source_type in [ResearchSourceType.ACADEMIC_DATABASE, ResearchSourceType.DATABASE]:
            return 0.9
        
        # Wikipedia articles usually have citations
        if source.source_type == ResearchSourceType.WIKIPEDIA:
            return 0.8
        
        # Web search results vary widely
        if source.source_type == ResearchSourceType.WEB_SEARCH:
            # In a real implementation, we would analyze the page for citation quality
            return 0.5
        
        return 0.4
    
    async def _assess_date_relevance(self, source: ResearchSource) -> float:
        """Assess the relevance of the publication date."""
        # If there's metadata with a date, evaluate it
        if "date" in source.metadata:
            try:
                pub_date = datetime.fromisoformat(str(source.metadata["date"]))
                # Check if the date is within the last 5 years (for most topics)
                if datetime.now() - pub_date < timedelta(days=5*365):
                    return 0.9
                elif datetime.now() - pub_date < timedelta(days=10*365):
                    return 0.7
                else:
                    return 0.4  # Older sources may be less relevant
            except Exception:
                pass  # Date parsing failed, use default score
        
        # Default score
        return 0.6
    
    async def _assess_peer_review_status(self, source: ResearchSource) -> float:
        """Assess if the source has undergone peer review."""
        # Academic databases and journals typically have peer review
        if source.source_type in [ResearchSourceType.ACADEMIC_DATABASE, ResearchSourceType.DATABASE]:
            return 0.95
        
        # Wikipedia has a form of collaborative review
        if source.source_type == ResearchSourceType.WIKIPEDIA:
            return 0.7
        
        # Most web sources don't have formal peer review
        if source.source_type == ResearchSourceType.WEB_SEARCH:
            return 0.2
        
        return 0.3
    
    async def _assess_transparency(self, source: ResearchSource) -> float:
        """Assess the transparency of the source."""
        # Wikipedia is transparent about its editing process
        if source.source_type == ResearchSourceType.WIKIPEDIA:
            return 0.9
        
        # Academic sources are typically transparent about methodology
        if source.source_type in [ResearchSourceType.ACADEMIC_DATABASE, ResearchSourceType.DATABASE]:
            return 0.85
        
        # News sources from reputable outlets are generally transparent
        if source.source_type == ResearchSourceType.NEWS_API:
            return 0.75
        
        # Default score
        return 0.5
    
    async def _assess_bias_detection(self, source: ResearchSource) -> float:
        """Assess potential bias in the source."""
        # Social media sources are more prone to bias
        if source.source_type == ResearchSourceType.SOCIAL_MEDIA:
            return 0.3
        
        # Academic sources aim to be objective
        if source.source_type in [ResearchSourceType.ACADEMIC_DATABASE, ResearchSourceType.DATABASE]:
            return 0.8
        
        # Wikipedia aims for neutral point of view
        if source.source_type == ResearchSourceType.WIKIPEDIA:
            return 0.75
        
        # Default score
        return 0.6
    
    async def _assess_domain_authority(self, source: ResearchSource) -> float:
        """Assess the authority of the domain."""
        parsed_url = urlparse(source.url)
        domain = parsed_url.netloc.lower()
        
        # Check for high-authority domains
        if any(auth_domain in domain for auth_domain in [
            "edu", "gov", "org", "ac.uk", "nih.gov", "who.int", "nature.com", 
            "science.org", "arxiv.org", "ieee.org", "acm.org", "springer.com",
            "cambridge.org", "oxford.ac.uk", "harvard.edu", "stanford.edu",
            "mit.edu", "wikipedia.org", "britannica.com"
        ]):
            return 0.9
        
        # Check for commercial domains (neutral authority)
        if "com" in domain.split('.'):
            return 0.5
        
        # Default score
        return 0.4
    
    async def _detect_potential_biases(self, source: ResearchSource) -> List[str]:
        """Detect potential biases in the source."""
        biases = []
        
        # Check source type for inherent biases
        if source.source_type == ResearchSourceType.SOCIAL_MEDIA:
            biases.append("potential_social_media_bias")
        
        if source.source_type == ResearchSourceType.NEWS_API:
            # Could analyze for political or corporate bias
            biases.append("potential_news_bias")
        
        # Check for funding sources or conflicts of interest in metadata
        if "funding" in source.metadata or "sponsor" in source.metadata:
            biases.append("potential_funding_bias")
        
        # Check for emotional language or sensationalism in title/url
        title = source.metadata.get("title", source.name).lower()
        if any(word in title for word in ["shocking", "unbelievable", "you won't believe", "incredible"]):
            biases.append("potential_sensationalism")
        
        return biases
    
    async def _determine_reliability_factors(self, source: ResearchSource) -> List[str]:
        """Determine factors that contribute to reliability."""
        factors = []
        
        # Add factors based on source type
        if source.source_type in [ResearchSourceType.ACADEMIC_DATABASE, ResearchSourceType.DATABASE]:
            factors.extend(["peer_reviewed", "expert_authors", "methodology_documented"])
        
        if source.source_type == ResearchSourceType.WIKIPEDIA:
            factors.extend(["collaborative_editing", "citation_requirement", "transparent_history"])
        
        if source.source_type == ResearchSourceType.NEWS_API:
            factors.extend(["professional_journalism", "editorial_review", "correction_policy"])
        
        # Check for presence of citations
        if source.metadata.get("has_citations"):
            factors.append("references_cited")
        
        # Check for publication date
        if "date" in source.metadata:
            factors.append("dated_publication")
        
        return factors
    
    async def _determine_verification_status(self, source: ResearchSource) -> str:
        """Determine the verification status of the source."""
        # Check if this is from a known verified source
        parsed_url = urlparse(source.url)
        domain = parsed_url.netloc.lower()
        
        if any(ver_domain in domain for ver_domain in [
            "nature.com", "science.org", "arxiv.org", "nih.gov", "who.int",
            "wikipedia.org", "britannica.com", "reuters.com", "apnews.com"
        ]):
            return "verified"
        
        # For academic sources
        if source.source_type in [ResearchSourceType.ACADEMIC_DATABASE, ResearchSourceType.DATABASE]:
            return "verified"
        
        # Default status
        return "unverified"
    
    async def batch_assess_sources(self, sources: List[ResearchSource]) -> List[CredibilityAssessment]:
        """Assess credibility for multiple sources concurrently."""
        assessments = []
        
        # Create tasks for concurrent assessment
        tasks = [self.assess_source_credibility(source) for source in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"Error assessing source {sources[i].name}: {result}")
                # Create a default assessment in case of error
                assessments.append(CredibilityAssessment(
                    source=sources[i],
                    overall_score=0.0,
                    credibility_indicators={},
                    assessment_details={"error": str(result)},
                    timestamp=datetime.now(),
                    potential_biases=["assessment_error"],
                    reliability_factors=[],
                    verification_status="error"
                ))
            else:
                assessments.append(result)
        
        return assessments
    
    async def get_credibility_summary(self, assessments: List[CredibilityAssessment]) -> Dict[str, Any]:
        """Get a summary of credibility assessments."""
        if not assessments:
            return {"message": "No assessments provided"}
        
        total_score = sum(ass.overall_score for ass in assessments)
        avg_score = total_score / len(assessments)
        
        # Count by credibility level
        highest_count = sum(1 for ass in assessments if ass.overall_score >= 0.9)
        high_count = sum(1 for ass in assessments if 0.7 <= ass.overall_score < 0.9)
        medium_count = sum(1 for ass in assessments if 0.5 <= ass.overall_score < 0.7)
        low_count = sum(1 for ass in assessments if 0.3 <= ass.overall_score < 0.5)
        lowest_count = sum(1 for ass in assessments if ass.overall_score < 0.3)
        
        # Collect all potential biases
        all_biases = []
        for assessment in assessments:
            all_biases.extend(assessment.potential_biases)
        
        # Get most common biases
        from collections import Counter
        bias_counts = Counter(all_biases)
        
        return {
            "total_sources": len(assessments),
            "average_credibility_score": avg_score,
            "credibility_distribution": {
                "highest": highest_count,
                "high": high_count,
                "medium": medium_count,
                "low": low_count,
                "lowest": lowest_count
            },
            "most_common_biases": dict(bias_counts.most_common(5)),
            "reliable_sources_count": sum(1 for ass in assessments if ass.overall_score >= 0.7),
            "unreliable_sources_count": sum(1 for ass in assessments if ass.overall_score < 0.4)
        }
    
    async def close(self):
        """Close the HTTP session."""
        if self.session:
            await self.session.close()


class CredibilityAssessmentTool:
    """Tool for assessing source credibility."""
    
    def __init__(self, evaluator: SourceCredibilityEvaluator):
        self.evaluator = evaluator
        self.logger = logging.getLogger(f"{__name__}.CredibilityAssessmentTool")
    
    async def assess_source(self, source: ResearchSource) -> Dict[str, Any]:
        """Assess the credibility of a source."""
        try:
            assessment = await self.evaluator.assess_source_credibility(source)
            
            # Format the assessment for output
            formatted_assessment = {
                "source_name": assessment.source.name,
                "overall_credibility_score": assessment.overall_score,
                "credibility_level": self._get_credibility_level(assessment.overall_score),
                "assessment_timestamp": assessment.timestamp.isoformat(),
                "detailed_indicators": {
                    indicator.value: score 
                    for indicator, score in assessment.credibility_indicators.items()
                },
                "potential_biases": assessment.potential_biases,
                "reliability_factors": assessment.reliability_factors,
                "verification_status": assessment.verification_status
            }
            
            return formatted_assessment
        except Exception as e:
            self.logger.error(f"Error assessing source credibility: {e}")
            return {
                "error": f"Error assessing source credibility: {str(e)}",
                "source_name": source.name if source else "Unknown"
            }
    
    def _get_credibility_level(self, score: float) -> str:
        """Convert numerical score to categorical level."""
        if score >= 0.9:
            return CredibilityScore.HIGHEST.value
        elif score >= 0.7:
            return CredibilityScore.HIGH.value
        elif score >= 0.5:
            return CredibilityScore.MEDIUM.value
        elif score >= 0.3:
            return CredibilityScore.LOW.value
        else:
            return CredibilityScore.LOWEST.value
    
    async def batch_assess_sources(self, sources: List[ResearchSource]) -> Dict[str, Any]:
        """Assess credibility for multiple sources."""
        try:
            assessments = await self.evaluator.batch_assess_sources(sources)
            summary = await self.evaluator.get_credibility_summary(assessments)
            
            return {
                "assessments": [
                    {
                        "source_name": assessment.source.name,
                        "credibility_score": assessment.overall_score,
                        "credibility_level": self._get_credibility_level(assessment.overall_score)
                    }
                    for assessment in assessments
                ],
                "summary": summary
            }
        except Exception as e:
            self.logger.error(f"Error in batch assessment: {e}")
            return {"error": f"Error in batch assessment: {str(e)}"}


# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def example():
        # Create an evaluator
        evaluator = SourceCredibilityEvaluator()
        
        # Create sample research sources
        sources = [
            ResearchSource(
                name="Nature Journal Article",
                source_type=ResearchSourceType.ACADEMIC_DATABASE,
                url="https://www.nature.com/article",
                quality=CredibilityScore.HIGH,
                reliability_score=0.95,
                metadata={"date": "2026-01-15", "has_citations": True}
            ),
            ResearchSource(
                name="Wikipedia Entry",
                source_type=ResearchSourceType.WIKIPEDIA,
                url="https://en.wikipedia.org/wiki/Topic",
                quality=CredibilityScore.MEDIUM,
                reliability_score=0.75,
                metadata={"date": "2026-02-20", "has_citations": True}
            ),
            ResearchSource(
                name="News Article",
                source_type=ResearchSourceType.NEWS_API,
                url="https://www.bbc.co.uk/news/topic",
                quality=CredibilityScore.MEDIUM,
                reliability_score=0.7,
                metadata={"date": "2026-03-01", "has_citations": False}
            ),
            ResearchSource(
                name="Blog Post",
                source_type=ResearchSourceType.WEB_SEARCH,
                url="https://random-blog.com/opinion",
                quality=CredibilityScore.LOW,
                reliability_score=0.3,
                metadata={"date": "2024-05-10", "has_citations": False}
            )
        ]
        
        print("Assessing source credibility...")
        
        # Assess individual source
        assessment = await evaluator.assess_source_credibility(sources[0])
        print(f"\nIndividual assessment for '{assessment.source.name}':")
        print(f"  Overall score: {assessment.overall_score:.2f}")
        print(f"  Verification status: {assessment.verification_status}")
        print(f"  Potential biases: {assessment.potential_biases}")
        
        # Batch assess all sources
        assessments = await evaluator.batch_assess_sources(sources)
        summary = await evaluator.get_credibility_summary(assessments)
        
        print(f"\nBatch assessment summary:")
        print(f"  Total sources: {summary['total_sources']}")
        print(f"  Average credibility: {summary['average_credibility_score']:.2f}")
        print(f"  Reliable sources: {summary['reliable_sources_count']}")
        print(f"  Unreliable sources: {summary['unreliable_sources_count']}")
        print(f"  Credibility distribution: {summary['credibility_distribution']}")
        
        # Close resources
        await evaluator.close()
        print("\nEvaluator closed")
    
    asyncio.run(example())