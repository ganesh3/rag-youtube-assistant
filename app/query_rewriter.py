import os
import ollama
import logging

logger = logging.getLogger(__name__)

class QueryRewriter:
    def __init__(self):
        self.model = os.getenv('OLLAMA_MODEL', "phi3")
        self.ollama_host = os.getenv('OLLAMA_HOST', 'http://ollama:11434')

    def generate(self, prompt):
        try:
            response = ollama.chat(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )
            return response['message']['content']
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return f"Error: {str(e)}"

    def rewrite_cot(self, query):
        prompt = f"""
        Rewrite the following query using Chain-of-Thought reasoning:
        Query: {query}
        
        Rewritten query:
        """
        rewritten_query = self.generate(prompt)
        if rewritten_query.startswith("Error:"):
            logger.error(f"Error in CoT rewriting: {rewritten_query}")
            return query, prompt  # Return original query if rewriting fails
        return rewritten_query, prompt

    def rewrite_react(self, query):
        prompt = f"""
        Rewrite the following query using the ReAct framework (Reasoning and Acting):
        Query: {query}
        
        Thought 1:
        Action 1:
        Observation 1:
        
        Thought 2:
        Action 2:
        Observation 2:
        
        Final rewritten query:
        """
        rewritten_query = self.generate(prompt)
        if rewritten_query.startswith("Error:"):
            logger.error(f"Error in ReAct rewriting: {rewritten_query}")
            return query, prompt  # Return original query if rewriting fails
        return rewritten_query, prompt