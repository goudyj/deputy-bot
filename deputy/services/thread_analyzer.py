import json
import logging
from typing import List, Dict, Any, Optional
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from deputy.models.issue import ThreadMessage, ThreadAnalysis, IssueType, IssuePriority
from deputy.models.llm_config import LLMConfig

logger = logging.getLogger(__name__)


class ThreadState(Dict[str, Any]):
    messages: List[ThreadMessage]
    raw_analysis: Optional[str] = None
    structured_analysis: Optional[ThreadAnalysis] = None
    error: Optional[str] = None


class ThreadAnalyzer:
    def __init__(self, llm_config: LLMConfig):
        self.llm_config = llm_config
        self.llm = self._create_llm()
        self.graph = self._create_graph()
    
    def _create_llm(self):
        if self.llm_config.provider == "openai":
            return ChatOpenAI(
                model=self.llm_config.model,
                api_key=self.llm_config.openai_api_key,
                temperature=self.llm_config.temperature,
                max_tokens=self.llm_config.max_tokens
            )
        elif self.llm_config.provider == "anthropic":
            return ChatAnthropic(
                model=self.llm_config.model,
                api_key=self.llm_config.anthropic_api_key,
                temperature=self.llm_config.temperature,
                max_tokens=self.llm_config.max_tokens
            )
        else:
            raise ValueError(f"Unsupported LLM provider: {self.llm_config.provider}")
    
    def _create_graph(self) -> StateGraph:
        workflow = StateGraph(ThreadState)
        
        workflow.add_node("analyze_thread", self._analyze_thread_node)
        workflow.add_node("structure_analysis", self._structure_analysis_node)
        workflow.add_node("validate_analysis", self._validate_analysis_node)
        
        workflow.set_entry_point("analyze_thread")
        workflow.add_edge("analyze_thread", "structure_analysis")
        workflow.add_edge("structure_analysis", "validate_analysis")
        workflow.add_edge("validate_analysis", END)
        
        return workflow.compile()
    
    async def analyze_thread(self, messages: List[ThreadMessage]) -> ThreadAnalysis:
        """Analyze a thread of messages to extract issue information"""
        initial_state = ThreadState(messages=messages)
        
        try:
            result = await self.graph.ainvoke(initial_state)
            if result.get("error"):
                raise Exception(result["error"])
            return result["structured_analysis"]
        except Exception as e:
            logger.error(f"Error analyzing thread: {e}")
            # Return a default analysis
            return ThreadAnalysis(
                summary="Error analyzing thread",
                issue_type=IssueType.QUESTION,
                priority=IssuePriority.LOW,
                suggested_title="Issue analysis failed",
                detailed_description=f"Failed to analyze thread: {str(e)}",
                confidence_score=0.0
            )
    
    def _analyze_thread_node(self, state: ThreadState) -> ThreadState:
        """First node: Analyze the thread with LLM"""
        try:
            thread_content = self._format_thread_for_analysis(state["messages"])
            logger.info(f"Analyzing thread with {len(state['messages'])} messages")
            
            system_prompt = """You are an expert software engineer analyzing discussion threads to create GitHub issues.

Analyze the conversation and extract:
1. Issue type (bug, feature, enhancement, documentation, question, task)
2. Priority level (low, medium, high, critical)
3. A clear, concise title
4. Detailed description
5. Steps to reproduce (if applicable)
6. Expected vs actual behavior (if applicable)
7. Additional context
8. Suggested labels
9. Confidence score (0-1) in your analysis

Focus on technical details, error messages, and user problems. Consider images/attachments mentioned.

Respond in JSON format with this structure:
{
  "issue_type": "bug|feature|enhancement|documentation|question|task",
  "priority": "low|medium|high|critical",
  "suggested_title": "Clear, specific title",
  "detailed_description": "Comprehensive description",
  "steps_to_reproduce": ["step1", "step2", ...],
  "expected_behavior": "What should happen",
  "actual_behavior": "What actually happens",
  "additional_context": "Any other relevant info",
  "suggested_labels": ["label1", "label2", ...],
  "confidence_score": 0.95
}"""

            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"Thread to analyze:\n{thread_content}")
            ]
            
            response = self.llm.invoke(messages)
            logger.info(f"LLM response received: {len(response.content) if response.content else 0} characters")
            state["raw_analysis"] = response.content
            
        except Exception as e:
            state["error"] = f"LLM analysis failed: {str(e)}"
        
        return state
    
    def _structure_analysis_node(self, state: ThreadState) -> ThreadState:
        """Second node: Parse LLM response into structured data"""
        try:
            if state.get("error"):
                return state
                
            raw_analysis = state["raw_analysis"]
            
            # Extract JSON from response (handle cases where LLM adds extra text)
            start_idx = raw_analysis.find('{')
            end_idx = raw_analysis.rfind('}') + 1
            
            if start_idx == -1 or end_idx == 0:
                raise ValueError("No JSON found in LLM response")
                
            json_str = raw_analysis[start_idx:end_idx]
            analysis_data = json.loads(json_str)
            
            # Create structured analysis
            analysis = ThreadAnalysis(
                summary=analysis_data.get("detailed_description", "No summary available"),
                issue_type=IssueType(analysis_data.get("issue_type", "question")),
                priority=IssuePriority(analysis_data.get("priority", "low")),
                suggested_title=analysis_data.get("suggested_title", "Issue from thread"),
                detailed_description=analysis_data.get("detailed_description", ""),
                steps_to_reproduce=analysis_data.get("steps_to_reproduce", []),
                expected_behavior=analysis_data.get("expected_behavior"),
                actual_behavior=analysis_data.get("actual_behavior"),
                additional_context=analysis_data.get("additional_context"),
                suggested_labels=analysis_data.get("suggested_labels", []),
                confidence_score=analysis_data.get("confidence_score", 0.5)
            )
            
            state["structured_analysis"] = analysis
            
        except Exception as e:
            state["error"] = f"Failed to structure analysis: {str(e)}"
        
        return state
    
    def _validate_analysis_node(self, state: ThreadState) -> ThreadState:
        """Third node: Validate and enhance the analysis"""
        try:
            if state.get("error") or not state.get("structured_analysis"):
                return state
                
            analysis = state["structured_analysis"]
            
            # Basic validation and enhancement
            if len(analysis.suggested_title) < 10:
                analysis.suggested_title = f"Issue: {analysis.suggested_title}"
            
            if not analysis.detailed_description:
                analysis.detailed_description = "No detailed description available from thread analysis."
            
            # Add default labels based on issue type
            type_labels = {
                IssueType.BUG: ["bug"],
                IssueType.FEATURE: ["enhancement", "feature"],
                IssueType.ENHANCEMENT: ["enhancement"],
                IssueType.DOCUMENTATION: ["documentation"],
                IssueType.QUESTION: ["question"],
                IssueType.TASK: ["task"]
            }
            
            default_labels = type_labels.get(analysis.issue_type, [])
            analysis.suggested_labels = list(set(analysis.suggested_labels + default_labels))
            
            state["structured_analysis"] = analysis
            
        except Exception as e:
            state["error"] = f"Failed to validate analysis: {str(e)}"
        
        return state
    
    def _format_thread_for_analysis(self, messages: List[ThreadMessage]) -> str:
        """Format thread messages for LLM analysis"""
        formatted = []
        
        for i, msg in enumerate(messages):
            timestamp_str = msg.timestamp if msg.timestamp else f"Message {i+1}"
            
            formatted.append(f"**{msg.user}** ({timestamp_str}):")
            formatted.append(msg.content)
            
            if msg.attachments:
                formatted.append(f"Attachments: {', '.join(msg.attachments)}")
            
            formatted.append("")  # Empty line between messages
        
        return "\n".join(formatted)