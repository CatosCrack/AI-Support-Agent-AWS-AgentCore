"""
Customer Support AI Agent — Starter Code
==========================================
Your task is to complete this file by implementing all sections marked
with # TODO comments.

Reference the project instructions and rubric for guidance.
Work through each section yourself.

Run locally (after filling in config values):
  uv run main.py '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'

Deploy to AgentCore:
  agentcore deploy

Invoke deployed agent:
  agentcore invoke '{"prompt": "Hello", "customer_id": "CUST-123", "session_id": "s1"}'
"""

# ── Imports ───────────────────────────────────────────────────────────────────
# These imports are provided. Do not remove them.
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from bedrock_agentcore.memory import MemoryClient
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamable_http_client
import argparse, json
import os, asyncio, boto3
from strands.hooks import (
    HookProvider, 
    AfterInvocationEvent, 
    HookRegistry, 
    MessageAddedEvent,
)
import logging
import uuid
from typing import Dict
from bedrock_agentcore.tools.code_interpreter_client import code_session
from strands_tools.browser import AgentCoreBrowser


logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("CSAI_Agent")

# ── App Initialisation ───────────────────────────────────────────────
# Create a BedrockAgentCoreApp instance.
# This registers the ASGI server for AgentCore deployment.
# There must be exactly one instance per deployment.
app = BedrockAgentCoreApp()


# Suppress interactive tool-consent prompts (required in headless deployments).
os.environ["BYPASS_TOOL_CONSENT"] = "true"


# ── Configuration ────────────────────────────────────────────────────
# GATEWAY_URL format: https://<alias>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
# This starter uses an unsigned MCP connection and therefore assumes the
# project Gateway is configured with the NONE authorizer.
# KB_ID       format: 10-character alphanumeric string from the KB console
# REGION:     your AWS region, e.g. "us-east-1"
# MEMORY_ID   format: shown in the AgentCore Memory console

GATEWAY_URL = "https://customersupportgateway-aatzyps3re.gateway.bedrock-agentcore.us-east-1.amazonaws.com/mcp"
KB_ID       = "DHEWHXKYRG"
REGION      = "us-east-1"
MEMORY_ID   = "CustomerSupportMemory-K1mAcZBIAn"


# ── Model and Clients ────────────────────────────────────────────────

model_id = "global.amazon.nova-2-lite-v1:0"

# Create the BedrockModel instance
model = BedrockModel(model_id=model_id)

# Create the MemoryClient instance
memory_client = MemoryClient(region_name=REGION)

# Create the boto3 bedrock-agent-runtime client
_bedrock_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)


# ── Namespace Helper ─────────────────────────────────────────────────
# Implement get_namespaces() to return a dict mapping strategy type to
# namespace template string.

def get_namespaces(mem_client: MemoryClient, memory_id: str) -> Dict:
    """Return a dict mapping strategy type → namespace template string."""
    strategies = mem_client.get_memory_strategies(memory_id=memory_id)
    return { strategy["type"]: strategy["namespaces"][0] for strategy in strategies}

# ── Memory Hook ──────────────────────────────────────────────────────
# Implement MemoryHook, a HookProvider subclass that adds long-term memory.

class MemoryHook(HookProvider):
    """Long-term memory hook for the customer support agent."""

    def __init__(
        self,
        actor_id: str,
        session_id: str,
        memory_client: MemoryClient,
        memory_id: str,
    ):
        self.actor_id = actor_id
        self.session_id = session_id
        self.memory_client = memory_client
        self.memory_id = memory_id
        self.namespaces = get_namespaces(self.memory_client, self.memory_id)

    def retrieve_customer_context(self, event: MessageAddedEvent):
        """Retrieve relevant memories and prepend them to the user message."""
        last_message_text = ""
        
        if event.agent.messages[-1]["role"] == "user":
            first_block = event.agent.messages[-1]["content"][0]
            if "text" in first_block:
                last_message_text = first_block["text"]
            else:
                return
            
        context = []
        if last_message_text.strip():
            for type, namespace in self.namespaces.items():
                formatted_namespace = namespace.format(actorId=self.actor_id)
                memories = self.memory_client.retrieve_memories(
                    self.memory_id,
                    formatted_namespace,
                    last_message_text,
                    self.actor_id,
                    5
                )
                for memory in memories:
                    text = memory.get("content", {}).get("text", "").strip()
                    if text:
                        context.append(f"[{type}]: {text}")
            if context:
                context_string = "\n".join(context)
                event.agent.messages[-1]["content"][0]["text"] = (
                    f"User Context:\n {context_string}" + 
                    f"\n\nUser Message: {last_message_text}"
                )

    def save_support_interaction(self, event: AfterInvocationEvent):
        """Save the completed turn to memory after the agent responds."""
        found_user = False
        found_assistant = False
        messages = {
            "user":"",
            "assistant":""
        }
        for i in range(1, len(event.agent.messages)+1):
            msg = event.agent.messages[i*(-1)]
            if msg["role"] == "assistant" and not found_assistant:
                content = msg["content"]
                for block in content:
                    if "text" in block:
                        messages["assistant"] = block["text"]
                        found_assistant = True
                        break
            elif msg["role"] == "user" and not found_user:
                content = msg["content"]
                for block in content:
                    if "text" in block:
                        raw_text = block["text"]
                        if "\n\nUser Message: " in raw_text:
                            messages["user"] = raw_text.split("\n\nUser Message: ")[-1]
                        else:
                            messages["user"] = raw_text
                        found_user = True
                        break
            if found_user and found_assistant:
                break

        if found_assistant and found_user:
            self.memory_client.create_event(
                memory_id=self.memory_id,
                actor_id=self.actor_id,
                session_id=self.session_id,
                messages=[(messages.get("assistant", ""), "ASSISTANT"),(messages.get("user",""), "USER")]
            )

    def register_hooks(self, registry: HookRegistry) -> None:  # type: ignore
        """Register both memory callbacks."""
        registry.add_callback(MessageAddedEvent, self.retrieve_customer_context)
        registry.add_callback(AfterInvocationEvent, self.save_support_interaction)

# ── Knowledge Base Tool ─────────────────────────────────────────────
# Implement search_knowledge_base(query) using the @tool decorator.
#
# The docstring is the tool description — the model uses it to decide when
# to call this tool, so keep it clear and accurate.

@tool
def search_knowledge_base(query: str) -> str:
    """
    Search the Amazon product catalog and support knowledge base.
    Use this for product specifications, return policies, warranty
    information, loyalty program details, and order status definitions.

    Args:
        query: The question or topic to search for

    Returns:
        Relevant information retrieved from the knowledge base
    """
    if not KB_ID:
        return "Knowledge base not configured."

    response = _bedrock_runtime.retrieve(
          knowledgeBaseId=KB_ID,
          retrievalQuery={"text": query}
        )

    results = response.get("retrievalResults", [])

    if not results:
        return "No results found in the knowledge base."

    chunks = [result["content"]["text"] for result in results]
    return "\n---\n".join(chunks)


# ── Loyalty Discount Tool (Code Interpreter) ────────────────────────
# Implement calculate_loyalty_discount() using the @tool decorator.

@tool
def calculate_loyalty_discount(
    loyalty_points: int,
    tier: str,
    order_total: float,
    product_category: str = "standard",
) -> str:
    """
    Calculate the loyalty discount for a customer order using the
    AgentCore Code Interpreter. Runs exact arithmetic in a secure sandbox.

    Args:
        loyalty_points:   Customer's current points balance
        tier:             Customer tier — Silver, Gold, or Platinum
        order_total:      Order total in USD
        product_category: standard, device, or fresh

    Returns:
        Full discount breakdown and final price
    """
    code = f"""
        import json

        loyalty_points = {loyalty_points}
        tier = "{tier}"
        order_total = {order_total}
        product_category = "{product_category}"
        earn_rates = {{"standard": 1, "device": 2, "fresh": 5}}
        tier_rates = {{"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}}

        floor_order_cap_in_points = ((order_total*0.5*0.01)//500)*500
        floor_points = (loyalty_points//500)*500

        if floor_order_cap_in_points <= loyalty_points:
            points_redeemed = min(floor_order_cap_in_points, floor_points)
        else:
            points_redeemed = floor_points

        tier_discount = tier_rates.get(tier, 0)
        order_subtotal = order_total - (points_redeemed*0.01)

        final_total = order_subtotal * (1-tier_discount)
        total_savings = order_total-final_total
        points_earned = (final_total*0.01)*earn_rates.get(product_category,1)
        remaining_points = loyalty_points - points_redeemed + points_earned

        response = {{
            "final_total":round(final_total, 2),
            "total_savings":round(total_savings, 2),
            "tier_discount":tier_discount,
            "points_earned":int(points_earned),
            "remaining_points":int(remaining_points)
        }}
        
        print(json.dumps(response, indent=4))
    """

    try:
        with code_session(REGION) as code_client:
            response = code_client.invoke("executeCode", {
                "code":code,
                "language":"python",
                "clearContext":True
            })

        for event in response["stream"]:
            return json.dumps(event["result"])

    except Exception as e:
        tier_rates = {"Silver": 0.00, "Gold": 0.10, "Platinum": 0.15}
        tier_discount = tier_rates.get("tier", 0)
        final_total = order_total * (1-tier_discount)

        response = {
                    "final_total":round(final_total, 2),
                    "total_savings":round(order_total-final_total, 2),
                    "points_earned":0,
                    "remaining_points":0
        }


# ─— Agent Entrypoint ─────────────────────────────────────────────────
# Implement the invoke() function decorated with @app.entrypoint.


SYSTEM_PROMPT = """
    You are an intelligent customer support agent for an e-commerce store.

    To answer to a questions about product specifications, return policies, warranty
    information, loyalty program details, and order status definitions you can use the search_knowledge_base tool.

    To calculate a loyalty discount for a discount, call the calculate_loyalty_discount. This will run code to give 
    you an accurate calculation of the purchase total, the total savings, the points earned with the transacion
    and the left over points.

    For information about the client or the client current orders, always look up with the client id.

    For information about specific orders, always look up using the order id.
"""

@app.entrypoint
async def invoke(payload, context=None):
    """
    Main handler called by AgentCore for every incoming request.

    Expected payload keys:
      prompt      (str, required) — the customer's message
      customer_id (str, optional) — unique customer identifier
      session_id  (str, optional) — session identifier; generated if absent
    """
    session_id = payload.get("session_id") or str(uuid.uuid4())
    actor_id = payload.get("customer_id", "test-user")
    user_input = payload.get("prompt", "")

    memory_hook = MemoryHook(actor_id,session_id, memory_client,MEMORY_ID)
    browser_client = AgentCoreBrowser(REGION, session_timeout=600)

    tools = [search_knowledge_base, calculate_loyalty_discount, browser_client.browser]

    mcp_client = MCPClient(
        lambda: streamable_http_client(url=GATEWAY_URL)
    )

    with mcp_client:
        tools.extend(mcp_client.list_tools_sync())
        agent = Agent(
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
            hooks=[memory_hook]
        )
        response = agent(user_input)
    
    return response.message["content"][0]["text"]


# ── CLI entry point (do not modify) ──────────────────────────────────────────
def main():
    """Run one invocation from the command line for local testing."""
    parser = argparse.ArgumentParser()
    parser.add_argument("payload", type=str)
    args = parser.parse_args()
    response = asyncio.run(invoke(json.loads(args.payload)))
    print(response)

if __name__ == "__main__":
    app.run()
    # Uncomment the line below and comment app.run() for local CLI testing:
    # main()
